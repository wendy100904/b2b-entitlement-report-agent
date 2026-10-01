from __future__ import annotations

import io
import json
import os
import re
import uuid
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.io as pio
from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel
from sqlalchemy import create_engine, event, text


ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
REACT_DIST = ROOT / "frontend-react" / "dist"

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

HIGH_VALUE = {"简历快读", "智能邀约", "超级聊聊"}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "30"))
MAX_AGENT_ITERATIONS = int(os.getenv("MAX_AGENT_ITERATIONS", "6"))
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{(ROOT / 'entitlement.db').as_posix()}"
IS_SQLITE = DATABASE_URL.startswith("sqlite")

FIELDS = ["customer_id", "data_date", "industry", "company_size", "renewal_type", "active_type", "ownership", "city_tier", "package_products", "used_products", "use_times", "max_cnt", "type_cnt", "use_period", "max_success_day", "renewal_days", "annual_value"]
SEGMENT_FIELDS = ["industry", "company_size", "renewal_type", "active_type"]
DIMENSION_LABELS = {"industry": "行业", "company_size": "企业规模", "renewal_type": "续约类型", "active_type": "活跃类型"}
CANDIDATES = {
    "customer_id": ["customer_id", "企业id", "企业代码", "客户id", "客户代码", "企业用户id"],
    "data_date": ["data_date", "数据日期", "统计日期", "快照日期", "周报日期", "周末日期", "week_date", "snapshot_date"],
    "industry": ["industry", "行业", "企业所属行业"], "company_size": ["company_size", "企业规模", "规模", "员工规模"],
    "renewal_type": ["renewal_type", "续约类型", "续费类型", "签约类型", "合同类型", "客户续约类型"],
    "active_type": ["active_type", "活跃类型", "活跃度", "客户活跃类型", "活跃分层", "使用活跃度"],
    "ownership": ["ownership", "企业性质", "性质"], "city_tier": ["city_tier", "城市层级", "地区发展水平"],
    "package_products": ["package_products", "购买产品", "套餐权益", "发放权益"], "used_products": ["used_products", "已使用产品", "使用产品", "产品名称"],
    "use_times": ["use_times", "使用次数"], "max_cnt": ["max_cnt", "日最大使用次数"], "type_cnt": ["type_cnt", "使用种类"],
    "use_period": ["use_period", "使用时长"], "max_success_day": ["max_success_day", "最大连续使用天数"],
    "renewal_days": ["renewal_days", "距到期天数", "续费倒计时"], "annual_value": ["annual_value", "年合同金额", "合同金额", "合同价值"],
}

# ---- 持久化相关常量 ----
STORAGE_LIST_FIELDS = ["package_products", "used_products"]
STORAGE_NUMERIC_FIELDS = ["use_times", "max_cnt", "type_cnt", "use_period", "max_success_day", "renewal_days", "annual_value", "coverage", "idle_high_value", "two_week_trend", "risk_score"] + [f"week_{i}" for i in range(1, 9)]
DERIVED_FIELDS = ["coverage", "idle_high_value", "two_week_trend", "value_tier", "risk_level", "risk_score"] + [f"week_{i}" for i in range(1, 9)]
USAGE_COLUMNS = ["session_id", "data_date", "customer_id"] + [f for f in FIELDS if f not in ("customer_id", "data_date")] + ["coverage", "idle_high_value", "two_week_trend", "value_tier", "risk_level", "risk_score"] + [f"week_{i}" for i in range(1, 9)]


class AnalyzeRequest(BaseModel):
    session_id: str
    mapping: dict[str, str | None]
    industry: str = "全部"
    renewal_max: int = 90
    value_tier: str = "全部"
    snapshot_date: str = "最新一周"
    filters: dict[str, str] = {}
    focus_dimensions: list[str] = []


class QueryRequest(BaseModel):
    session_id: str
    question: str


class WeeklyReportRequest(BaseModel):
    session_id: str
    mapping: dict[str, str | None]
    report_title: str = "企业权益产品周报"
    week_label: str = "本周"
    industry: str = "全部"
    renewal_max: int = 90
    value_tier: str = "全部"
    snapshot_date: str = "最新一周"
    filters: dict[str, str] = {}
    focus_dimensions: list[str] = []
    analysis_plan: dict[str, Any] = {}


class AutoReportRequest(BaseModel):
    session_id: str
    report_title: str = "企业权益产品周报"
    week_label: str = "本周"


class AnalysisPlanRequest(BaseModel):
    session_id: str
    mapping: dict[str, str | None]
    goal: str


# ============================================================
# 数据库层（默认 SQLite，可通过 DATABASE_URL 切换 PostgreSQL 等）
# ============================================================

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
    pool_pre_ping=True,
)

if IS_SQLITE:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def init_db() -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS uploads (
                session_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                rows INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                mapping TEXT NOT NULL,
                snapshots TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS upload_raw (
                session_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS customer_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                {", ".join(f"{column} TEXT" for column in USAGE_COLUMNS)}
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_usage_session ON customer_usage(session_id, data_date)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS analysis_snapshot (
                session_id TEXT PRIMARY KEY,
                snapshot_date TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """))


def _serialize_record(record: dict[str, Any]) -> dict[str, Any]:
    row = dict(record)
    for field in STORAGE_LIST_FIELDS:
        value = row.get(field)
        if isinstance(value, (list, tuple)):
            row[field] = json.dumps(list(value), ensure_ascii=False)
        elif value is None or (isinstance(value, float) and np.isnan(value)):
            row[field] = "[]"
    if isinstance(row.get("data_date"), (pd.Timestamp, datetime, np.datetime64)):
        row["data_date"] = pd.Timestamp(row["data_date"]).strftime("%Y-%m-%d")
    return row


def _deserialize_record(record: dict[str, Any]) -> dict[str, Any]:
    row = dict(record)
    for field in STORAGE_LIST_FIELDS:
        value = row.get(field)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                row[field] = parsed if isinstance(parsed, list) else ([str(parsed)] if parsed else [])
            except Exception:
                row[field] = [value] if value else []
    return row


def df_to_db_rows(df: pd.DataFrame, session_id: str) -> list[dict[str, Any]]:
    rows = []
    for record in df.to_dict(orient="records"):
        row = _serialize_record(record)
        row["session_id"] = session_id
        rows.append({column: row.get(column) for column in USAGE_COLUMNS})
    return rows


def df_from_db_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=[column for column in USAGE_COLUMNS if column != "session_id"])
    records = [_deserialize_record(row) for row in rows]
    df = pd.DataFrame(records)
    for field in STORAGE_NUMERIC_FIELDS:
        if field in df.columns:
            df[field] = pd.to_numeric(df[field], errors="coerce")
    if "data_date" in df.columns:
        df["data_date"] = pd.to_datetime(df["data_date"], errors="coerce").dt.normalize()
    return df


def save_upload(session_id: str, filename: str, row_count: int, mapping: dict[str, str | None], snapshots: list[str], raw_df: pd.DataFrame, normalized_df: pd.DataFrame) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO uploads (session_id, filename, rows, created_at, mapping, snapshots) VALUES (:sid, :filename, :rows, :created_at, :mapping, :snapshots)"),
            {"sid": session_id, "filename": filename, "rows": row_count, "created_at": datetime.now(timezone.utc).isoformat(),
             "mapping": json.dumps(mapping, ensure_ascii=False), "snapshots": json.dumps(snapshots)},
        )
        conn.execute(
            text("INSERT INTO upload_raw (session_id, payload) VALUES (:sid, :payload)"),
            {"sid": session_id, "payload": json.dumps(raw_df.to_dict(orient="records"), ensure_ascii=False, default=str)},
        )
        _replace_usage_rows(conn, session_id, normalized_df)


def _replace_usage_rows(conn: Any, session_id: str, normalized_df: pd.DataFrame) -> None:
    conn.execute(text("DELETE FROM customer_usage WHERE session_id = :sid"), {"sid": session_id})
    rows = df_to_db_rows(normalized_df, session_id)
    if rows:
        placeholders = ", ".join(f":{column}" for column in USAGE_COLUMNS)
        conn.execute(text(f"INSERT INTO customer_usage ({', '.join(USAGE_COLUMNS)}) VALUES ({placeholders})"), rows)


def get_upload_meta(session_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM uploads WHERE session_id = :sid"), {"sid": session_id}).mappings().first()
    if not row:
        return None
    return {
        "session_id": row["session_id"],
        "filename": row["filename"],
        "rows": row["rows"],
        "created_at": row["created_at"],
        "mapping": json.loads(row["mapping"]),
        "snapshots": json.loads(row["snapshots"]),
    }


def get_raw_df(session_id: str) -> pd.DataFrame | None:
    with engine.connect() as conn:
        payload = conn.execute(text("SELECT payload FROM upload_raw WHERE session_id = :sid"), {"sid": session_id}).scalar_one_or_none()
    if payload is None:
        return None
    records = json.loads(payload)
    return pd.DataFrame.from_records(records) if records else pd.DataFrame()


def load_customer_usage(session_id: str) -> pd.DataFrame:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM customer_usage WHERE session_id = :sid ORDER BY data_date, customer_id"),
            {"sid": session_id},
        ).mappings().all()
    return df_from_db_rows([dict(row) for row in rows])


def save_analysis_snapshot(session_id: str, snapshot_date: str, df: pd.DataFrame) -> None:
    payload = json.dumps([_serialize_record(record) for record in df.to_dict(orient="records")], ensure_ascii=False, default=str)
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO analysis_snapshot (session_id, snapshot_date, payload, created_at)
                VALUES (:sid, :snapshot_date, :payload, :created_at)
                ON CONFLICT(session_id) DO UPDATE SET snapshot_date = :snapshot_date, payload = :payload, created_at = :created_at
            """),
            {"sid": session_id, "snapshot_date": snapshot_date, "payload": payload, "created_at": datetime.now(timezone.utc).isoformat()},
        )


def load_analysis_snapshot(session_id: str) -> tuple[pd.DataFrame, str] | None:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT snapshot_date, payload FROM analysis_snapshot WHERE session_id = :sid"),
            {"sid": session_id},
        ).mappings().first()
    if not row:
        return None
    records = json.loads(row["payload"])
    df = df_from_db_rows(records) if records else pd.DataFrame()
    return df, row["snapshot_date"]


def count_uploads() -> int:
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM uploads")).scalar_one())


def resolve_session(session_id: str) -> dict[str, Any]:
    meta = get_upload_meta(session_id)
    if not meta:
        raise HTTPException(404, "上传会话不存在或已被清理，请重新上传文件")
    return meta


def resolve_normalized(session_id: str, mapping: dict[str, str | None]) -> pd.DataFrame:
    """返回规范化后的客户数据。若映射与落库时不同，则基于原始数据重新规范化并刷新数据库。"""
    meta = resolve_session(session_id)
    if mapping != meta["mapping"]:
        raw = get_raw_df(session_id)
        normalized = normalise(raw, mapping)
        with engine.begin() as conn:
            _replace_usage_rows(conn, session_id, normalized)
            conn.execute(text("UPDATE uploads SET mapping = :mapping WHERE session_id = :sid"),
                         {"mapping": json.dumps(mapping, ensure_ascii=False), "sid": session_id})
        return normalized
    return load_customer_usage(session_id)


# ============================================================
# 数据清洗与风险模型（与原实现保持一致）
# ============================================================

def infer_mapping(columns: list[str]) -> dict[str, str | None]:
    lowered = {re.sub(r"[\s_\-()（）]", "", c.lower()): c for c in columns}
    result = {}
    used_columns: set[str] = set()
    for field, options in CANDIDATES.items():
        normalized_options = [re.sub(r"[\s_\-()（）]", "", o.lower()) for o in options]
        result[field] = next((lowered[o] for o in normalized_options if o in lowered and lowered[o] not in used_columns), None)
        if result[field] is None and columns:
            scored = [(SequenceMatcher(None, option, col).ratio(), col) for option in normalized_options for col in lowered if lowered[col] not in used_columns]
            score, col = max(scored, default=(0, ""))
            if score >= 0.72:
                result[field] = lowered[col]
        if result[field]:
            used_columns.add(result[field])
    return result


def parse_products(value: Any) -> list[str]:
    if isinstance(value, list):
        return value
    if pd.isna(value) or str(value).strip() == "":
        return []
    return [part.strip() for part in re.split(r"[,，、;/|]+", str(value)) if part.strip()]


def normalise(df: pd.DataFrame, mapping: dict[str, str | None]) -> pd.DataFrame:
    result = pd.DataFrame(index=df.index)
    for field in FIELDS:
        source = mapping.get(field)
        result[field] = df[source] if source and source in df.columns else np.nan
    result["customer_id"] = result["customer_id"].fillna(pd.Series([f"ROW-{i+1}" for i in range(len(result))], index=result.index)).astype(str)
    default_snapshot = pd.Timestamp(datetime.now(timezone.utc).date())
    result["data_date"] = pd.to_datetime(result["data_date"], errors="coerce").dt.normalize().fillna(default_snapshot)
    for field in ["industry", "company_size", "ownership", "city_tier"]:
        result[field] = result[field].fillna("未提供").astype(str)
    for field in ["package_products", "used_products"]:
        result[field] = result[field].map(parse_products)
    result["package_products"] = result.apply(lambda r: r.package_products or r.used_products, axis=1)
    result["type_cnt"] = pd.to_numeric(result.type_cnt, errors="coerce").fillna(result.used_products.map(len))
    for field in ["use_times", "max_cnt", "use_period", "max_success_day", "renewal_days", "annual_value"]:
        result[field] = pd.to_numeric(result[field], errors="coerce").fillna(0)
    result["coverage"] = result.type_cnt / result.package_products.map(len).replace(0, np.nan)
    result["coverage"] = result.coverage.fillna(0).clip(0, 1)
    result["idle_high_value"] = result.apply(lambda r: len((set(r.package_products) & HIGH_VALUE) - set(r.used_products)), axis=1)
    result["two_week_trend"] = 0.0
    for i in range(1, 9):
        source = mapping.get(f"week_{i}")
        result[f"week_{i}"] = pd.to_numeric(df[source], errors="coerce").fillna(0) if source and source in df.columns else 0
    previous = result[["week_5", "week_6"]].sum(axis=1).replace(0, np.nan)
    result["two_week_trend"] = ((result[["week_7", "week_8"]].sum(axis=1) - previous) / previous).replace([np.inf, -np.inf], np.nan).fillna(0)
    renewal_source = result["renewal_type"]
    derived_renewal = pd.cut(result.renewal_days, bins=[-1, 30, 90, np.inf], labels=["临期续约", "近期续约", "远期续约"]).astype(str)
    result["renewal_type"] = renewal_source.where(renewal_source.notna() & renewal_source.astype(str).str.strip().ne(""), derived_renewal).astype(str)
    active_source = result["active_type"]
    derived_active = np.select(
        [result.use_times <= 0, result.coverage < .35, result.coverage < .7],
        ["未活跃", "低活跃", "中活跃"],
        default="高活跃",
    )
    result["active_type"] = active_source.where(active_source.notna() & active_source.astype(str).str.strip().ne(""), derived_active).astype(str)
    result["value_tier"] = pd.cut(result.groupby("data_date").annual_value.rank(pct=True), bins=[-0.01, .5, .8, 1.01], labels=["普通", "重点", "高价值"]).astype(str)
    result["risk_level"] = result.apply(classify_risk, axis=1)
    result["risk_score"] = result.apply(score_risk, axis=1)
    group_keys = ["customer_id", "data_date"]
    if result.duplicated(group_keys).any():
        grouped = result.groupby(group_keys, as_index=False)
        collapsed = grouped[["industry", "company_size", "renewal_type", "active_type", "ownership", "city_tier"]].first()
        for field in ["package_products", "used_products"]:
            product_lists = result.groupby(group_keys, as_index=False)[field].agg(lambda values: sorted({p for items in values for p in items}))
            collapsed = collapsed.merge(product_lists, on=group_keys)
        for field, agg in [("use_times", "sum"), ("max_cnt", "max"), ("type_cnt", "max"), ("use_period", "max"), ("max_success_day", "max"), ("renewal_days", "min"), ("annual_value", "max"), ("coverage", "mean"), ("idle_high_value", "max"), ("two_week_trend", "mean")]:
            values = result.groupby(group_keys, as_index=False)[field].agg(agg)
            collapsed = collapsed.merge(values, on=group_keys)
        collapsed["value_tier"] = pd.cut(collapsed.groupby("data_date").annual_value.rank(pct=True), bins=[-0.01, .5, .8, 1.01], labels=["普通", "重点", "高价值"]).astype(str)
        collapsed["risk_level"] = collapsed.apply(classify_risk, axis=1)
        collapsed["risk_score"] = collapsed.apply(score_risk, axis=1)
        result = collapsed
    return result


def snapshot_dates(df: pd.DataFrame) -> list[str]:
    return [pd.Timestamp(date).strftime("%Y-%m-%d") for date in sorted(pd.to_datetime(df["data_date"]).dropna().unique(), reverse=True)]


def select_snapshot(df: pd.DataFrame, snapshot_date: str = "最新一周") -> tuple[pd.DataFrame, str]:
    dates = snapshot_dates(df)
    if not dates:
        return df.copy(), "未提供"
    selected = dates[0] if snapshot_date in {"", "最新一周", "最新快照"} else snapshot_date
    if selected not in dates:
        raise HTTPException(400, f"未找到数据日期 {selected}，可选日期：{', '.join(dates)}")
    return df[pd.to_datetime(df["data_date"]).dt.strftime("%Y-%m-%d") == selected].copy(), selected


def available_dimensions(df: pd.DataFrame, mapping: dict[str, str | None]) -> list[dict[str, Any]]:
    normalized, _ = select_snapshot(normalise(df, mapping))
    dimensions = []
    for field in SEGMENT_FIELDS:
        values = [str(value) for value in normalized[field].dropna().unique().tolist() if str(value).strip() and str(value) != "未提供"]
        if values:
            dimensions.append({
                "field": field,
                "label": DIMENSION_LABELS[field],
                "source": "上传字段" if mapping.get(field) else "自动派生",
                "values": sorted(values)[:40],
            })
    return dimensions


def customer_pool_profile(df: pd.DataFrame, mapping: dict[str, str | None]) -> dict[str, Any]:
    normalized, selected_date = select_snapshot(normalise(df, mapping))
    dimensions = available_dimensions(df, mapping)
    for item in dimensions:
        field = item["field"]
        item["customer_coverage"] = round(float((normalized[field].astype(str) != "未提供").mean()), 3)
        item["cardinality"] = int(normalized[field].nunique())
    return {
        "customers": int(len(normalized)),
        "snapshot_date": selected_date,
        "available_dimensions": dimensions,
        "metrics": {
            "expiring_within_90_days": int((normalized.renewal_days <= 90).sum()),
            "high_medium_risk": int(normalized.risk_level.isin(["高危流失", "中危预警"]).sum()),
            "average_coverage": round(float(normalized.coverage.mean()), 3) if len(normalized) else 0,
            "silent_or_low_active": int(normalized.active_type.isin(["沉默客户", "未活跃", "低活跃"]).sum()),
        },
    }


def fallback_analysis_plan(profile: dict[str, Any], goal: str) -> dict[str, Any]:
    dimensions = profile["available_dimensions"]
    available = {item["field"] for item in dimensions}
    values_by_field = {item["field"]: item["values"] for item in dimensions}
    text = goal.lower()
    keywords = {
        "industry": ["行业", "赛道", "领域"],
        "company_size": ["企业规模", "公司规模", "规模", "员工数"],
        "renewal_type": ["续约类型", "续费类型", "续约", "续费", "到期", "临期"],
        "active_type": ["活跃类型", "活跃度", "活跃", "使用频率", "低活跃", "沉默"],
    }
    relevance = {field: sum(term in text for term in terms) for field, terms in keywords.items() if field in available}
    intent = "risk" if any(term in text for term in ["风险", "流失", "续约", "续费", "到期", "临期"]) else "activation" if any(term in text for term in ["活跃", "使用", "激活", "闲置"]) else "upsell" if any(term in text for term in ["增购", "升级", "机会", "交叉销售"]) else "overview"
    preferred = {
        "risk": ["renewal_type", "active_type", "company_size", "industry"],
        "activation": ["active_type", "industry", "company_size", "renewal_type"],
        "upsell": ["renewal_type", "company_size", "industry", "active_type"],
        "overview": ["industry", "company_size", "renewal_type", "active_type"],
    }[intent]
    ranked = sorted(available, key=lambda field: (relevance.get(field, 0), -preferred.index(field) if field in preferred else -99), reverse=True)
    focus = ranked[:min(3, len(ranked))]
    primary = focus[0] if focus else "industry"
    renewal_max = 30 if "30天" in text or "30 天" in text else 60 if "60天" in text or "60 天" in text else 180 if "180天" in text or "180 天" in text else 90
    filters: dict[str, str] = {}
    for field, values in values_by_field.items():
        matched_value = next((value for value in values if value in goal), None)
        if matched_value:
            filters[field] = matched_value
    mode_map = {"risk": "临期续费风险作战图", "activation": "权益激活与使用提升", "upsell": "续费与增购机会识别", "overview": "综合商业化周报"}
    metric_map = {
        "risk": ["高/中危客户数", "风险客户占比", "平均权益覆盖率", "闲置高价值权益数"],
        "activation": ["活跃客户数", "平均使用次数", "平均权益覆盖率", "沉默/低活跃客户数"],
        "upsell": ["续费/增购机会数", "高价值客户数", "权益覆盖率", "高粘性临期客户数"],
        "overview": ["客户池规模", "高/中危客户数", "平均权益覆盖率", "续费/增购机会数"],
    }
    action_map = {
        "risk": ["优先处理临期且低覆盖的客户", "按主分群分配 CSM 跟进名单", "对闲置效率权益安排定向激活"],
        "activation": ["识别沉默和低活跃客户的闲置权益", "按分群安排产品培训或使用提醒", "跟踪激活后使用次数变化"],
        "upsell": ["筛选临期且高覆盖的客户", "用实际使用成果组织续约复盘", "匹配相邻权益组合推进增购"],
        "overview": ["先核查风险池", "再复盘行业和规模差异", "输出本周优先运营动作"],
    }
    return {
        "mode": mode_map[intent],
        "goal": goal,
        "primary_dimension": primary,
        "focus_dimensions": focus,
        "renewal_max": renewal_max,
        "filters": filters,
        "metrics": metric_map[intent],
        "ranking_rule": "高/中危客户数降序" if intent == "risk" else "客户数与权益覆盖率联合排序",
        "report_sections": ["经营结论", "主分群对比", "风险/机会池", "行动建议"],
        "actions": action_map[intent],
        "source": "rule_planner",
        "available_dimensions": dimensions,
    }


def validate_analysis_plan(candidate: dict[str, Any], profile: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    dimensions = profile["available_dimensions"]
    available = {item["field"] for item in dimensions}
    values_by_field = {item["field"]: set(item["values"]) for item in dimensions}
    focus = [field for field in candidate.get("focus_dimensions", []) if field in available]
    primary = candidate.get("primary_dimension") if candidate.get("primary_dimension") in available else (focus[0] if focus else fallback["primary_dimension"])
    if primary not in focus:
        focus.insert(0, primary)
    focus = list(dict.fromkeys(focus))[:3] or fallback["focus_dimensions"]
    raw_filters = candidate.get("filters", {}) if isinstance(candidate.get("filters", {}), dict) else {}
    filters = {field: value for field, value in raw_filters.items() if field in available and value in values_by_field[field]}
    renewal_max = candidate.get("renewal_max", fallback["renewal_max"])
    renewal_max = int(renewal_max) if str(renewal_max).isdigit() else fallback["renewal_max"]
    renewal_max = min([30, 60, 90, 180], key=lambda value: abs(value - renewal_max))
    return {
        **fallback,
        "mode": str(candidate.get("mode") or fallback["mode"])[:50],
        "primary_dimension": primary,
        "focus_dimensions": focus,
        "renewal_max": renewal_max,
        "filters": filters,
        "metrics": [str(item)[:40] for item in candidate.get("metrics", fallback["metrics"])][:5] or fallback["metrics"],
        "ranking_rule": str(candidate.get("ranking_rule") or fallback["ranking_rule"])[:80],
        "report_sections": [str(item)[:40] for item in candidate.get("report_sections", fallback["report_sections"])][:5] or fallback["report_sections"],
        "actions": [str(item)[:80] for item in candidate.get("actions", fallback["actions"])][:4] or fallback["actions"],
        "source": "openai_planner",
    }


def suggest_analysis_plan(df: pd.DataFrame, mapping: dict[str, str | None], goal: str) -> dict[str, Any]:
    profile = customer_pool_profile(df, mapping)
    fallback = fallback_analysis_plan(profile, goal)
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return fallback
    prompt = {
        "business_question": goal,
        "customer_pool_profile": profile,
        "allowed_dimension_ids": [item["field"] for item in profile["available_dimensions"]],
        "instruction": "你是 B2B 商业化数据负责人。只返回 JSON，不要解释。基于经营问题和数据画像，规划一个可执行的批量分析方案。必须输出 mode、primary_dimension、focus_dimensions(最多3个)、renewal_max(30/60/90/180)、filters、metrics、ranking_rule、report_sections、actions。filters 的值只能取画像中已有的分类值。不要针对单个客户给建议。",
    }
    try:
        response = OpenAI(api_key=key, base_url=os.getenv("OPENAI_BASE_URL") or None).chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5"),
            messages=[{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
            temperature=0.3,
        )
        content = response.choices[0].message.content.strip()
        block = re.search(r"```(?:json)?\s*(.*?)```", content, flags=re.I | re.S)
        candidate = json.loads(block.group(1) if block else content)
        return validate_analysis_plan(candidate, profile, fallback)
    except Exception:
        return fallback


def apply_filters(df: pd.DataFrame, industry: str, renewal_max: int, value_tier: str, filters: dict[str, str]) -> pd.DataFrame:
    result = df.copy()
    if industry != "全部":
        result = result[result.industry == industry]
    result = result[result.renewal_days <= renewal_max]
    if value_tier != "全部":
        result = result[result.value_tier == value_tier]
    for field, value in filters.items():
        if field in SEGMENT_FIELDS and value and value != "全部" and field in result.columns:
            result = result[result[field] == value]
    return result


def pool_summary(df: pd.DataFrame) -> dict[str, Any]:
    risk = df.risk_level.value_counts().reindex(["高危流失", "中危预警", "体验引导", "续费/增购", "健康"], fill_value=0).to_dict()
    return {
        "customers": int(len(df)),
        "high_risk": int(risk["高危流失"] + risk["中危预警"]),
        "upsell": int(risk["续费/增购"]),
        "avg_coverage": round(float(df.coverage.mean()), 3) if len(df) else 0,
    }


def previous_snapshot_date(history: pd.DataFrame, selected_date: str) -> str | None:
    dates = snapshot_dates(history)
    if selected_date not in dates:
        return None
    index = dates.index(selected_date)
    return dates[index + 1] if index + 1 < len(dates) else None


def build_comparison(history: pd.DataFrame, selected_date: str, current: dict[str, Any], request: "AnalyzeRequest") -> dict[str, Any] | None:
    prev_date = previous_snapshot_date(history, selected_date)
    if not prev_date:
        return None
    prev_df, _ = select_snapshot(history, prev_date)
    prev_df = apply_filters(prev_df, request.industry, request.renewal_max, request.value_tier, request.filters)
    prev = pool_summary(prev_df)
    deltas = {key: round(current[key] - prev[key], 3) for key in ["customers", "high_risk", "upsell", "avg_coverage"]}
    return {"previous_date": prev_date, "previous": prev, "deltas": deltas}


def segment_breakdowns(df: pd.DataFrame, focus_dimensions: list[str]) -> list[dict[str, Any]]:
    breakdowns = []
    for field in focus_dimensions:
        if field not in SEGMENT_FIELDS or field not in df.columns:
            continue
        rows = df.groupby(field, as_index=False).agg(
            customers=("customer_id", "count"),
            avg_coverage=("coverage", "mean"),
            avg_usage=("use_times", "mean"),
            high_risk=("risk_level", lambda x: int(x.isin(["高危流失", "中危预警"]).sum())),
        ).round(3)
        breakdowns.append({"field": field, "label": DIMENSION_LABELS[field], "rows": rows.to_dict(orient="records")})
    return breakdowns


def classify_risk(row: pd.Series) -> str:
    if row.renewal_days < 30 and row.type_cnt <= 2:
        return "高危流失"
    if row.renewal_days <= 90 and (row.type_cnt <= 2 or row.idle_high_value >= 2 or row.two_week_trend < -.5):
        return "中危预警"
    if row.renewal_days > 90 and row.type_cnt <= 2:
        return "体验引导"
    if row.renewal_days <= 90 and row.type_cnt >= 5:
        return "续费/增购"
    return "健康"


def score_risk(row: pd.Series) -> int:
    return int(min(100, (30 if row.renewal_days < 30 else 18 if row.renewal_days <= 90 else 4) + (25 if row.type_cnt <= 2 else 8 if row.type_cnt <= 4 else 0) + min(20, row.idle_high_value * 7)))


def action_plan(df: pd.DataFrame) -> str:
    if df.empty:
        return "当前筛选范围没有客户。"
    high = int((df.risk_level == "高危流失").sum())
    medium = int((df.risk_level == "中危预警").sum())
    upsell = int((df.risk_level == "续费/增购").sum())
    return (f"本批客户共 {len(df):,} 家：高危流失 {high} 家，中危预警 {medium} 家，续费/增购机会 {upsell} 家。\n"
            "执行顺序：先将高危客户交由 CSM 核查账号分配、HR交接和权益激活；再对中危客户批量安排效率产品演示；"
            "对高粘性临期客户，以实际使用成果复盘推进早鸟续费和组合增购。")


def weekly_report_html(df: pd.DataFrame, title: str, week_label: str, focus_dimensions: list[str] | None = None, analysis_plan: dict[str, Any] | None = None, comparison: dict[str, Any] | None = None) -> str:
    product_rows = []
    for _, row in df.iterrows():
        for product in row.used_products:
            product_rows.append({"product": product, "use_times": max(1, int(row.use_times / max(row.type_cnt, 1))), "industry": row.industry})
    products = pd.DataFrame(product_rows)
    product_summary = products.groupby("product", as_index=False).agg(use_times=("use_times", "sum"), customers=("industry", "size")) if not products.empty else pd.DataFrame(columns=["product", "use_times", "customers"])
    risk = df.risk_level.value_counts().reindex(["高危流失", "中危预警", "体验引导", "续费/增购", "健康"], fill_value=0).reset_index()
    risk.columns = ["risk_level", "customers"]
    focus_dimensions = [field for field in (focus_dimensions or SEGMENT_FIELDS) if field in SEGMENT_FIELDS] or ["industry"]
    breakdowns = segment_breakdowns(df, focus_dimensions)
    kpi = {
        "客户池规模": len(df), "活跃客户数": int((df.use_times > 0).sum()), "总使用次数": int(df.use_times.sum()),
        "平均权益覆盖率": f"{df.coverage.mean():.1%}" if len(df) else "0%", "高/中危客户": int(df.risk_level.isin(["高危流失", "中危预警"]).sum()),
    }
    product_fig = px.bar(product_summary.sort_values("use_times"), x="use_times", y="product", orientation="h", title=f"产品使用情况（共 {len(product_summary)} 种）")
    risk_fig = px.bar(risk, x="risk_level", y="customers", color="risk_level", title="客户风险分布")
    segment_figs = []
    for breakdown in breakdowns:
        segment_df = pd.DataFrame(breakdown["rows"])
        if not segment_df.empty:
            segment_figs.append(px.bar(segment_df.sort_values("high_risk"), x=breakdown["field"], y="high_risk", title=f"{breakdown['label']}高/中危客户数"))
    charts_to_render = [product_fig, risk_fig, *segment_figs]
    for fig in charts_to_render:
        fig.update_layout(height=360, margin=dict(l=30, r=20, t=55, b=50), font=dict(family="Arial, Microsoft YaHei"))
    charts = "".join(pio.to_html(fig, full_html=False, include_plotlyjs="cdn" if i == 0 else False) for i, fig in enumerate(charts_to_render))
    cards = "".join(f"<div class='kpi'><small>{k}</small><strong>{v:,}</strong></div>" if isinstance(v, int) else f"<div class='kpi'><small>{k}</small><strong>{v}</strong></div>" for k, v in kpi.items())
    detail_tables = "".join(
        f"<h3>{breakdown['label']}分群明细</h3>" + pd.DataFrame(breakdown["rows"]).to_html(index=False, formatters={"avg_coverage": lambda x: f"{x:.1%}", "avg_usage": lambda x: f"{x:.1f}"})
        for breakdown in breakdowns
    ) or "<p class='muted'>当前数据没有可用的分群字段。</p>"
    analysis_plan = analysis_plan or {}
    planned_actions = analysis_plan.get("actions") if isinstance(analysis_plan.get("actions"), list) else []
    narrative = (action_plan(df) + ("\nAgent 建议：" + "；".join(str(action) for action in planned_actions) if planned_actions else "")).replace("\n", "<br>")
    mode = str(analysis_plan.get("mode") or "综合客户池诊断")
    primary = DIMENSION_LABELS.get(str(analysis_plan.get("primary_dimension") or ""), "行业")
    ranking_rule = str(analysis_plan.get("ranking_rule") or "高/中危客户数降序")
    comparison_html = ""
    if comparison and comparison.get("deltas"):
        deltas = comparison["deltas"]
        def _seg(label: str, value: float, higher_worse: bool = False, pct: bool = False) -> str:
            if value == 0:
                return f"{label}持平"
            up = value > 0
            good = (not up) if higher_worse else up
            arrow = "▲" if up else "▼"
            color = "#0b8f6a" if good else "#c94b55"
            shown = f"{'+' if up else ''}{value * 100:.1f}pt" if pct else f"{'+' if up else ''}{int(value)}"
            return f"<span style='color:{color};font-weight:700'>{label} {arrow} {shown}</span>"
        segs = [
            _seg("客户池规模", deltas.get("customers", 0)),
            _seg("高/中危客户", deltas.get("high_risk", 0), higher_worse=True),
            _seg("续费/增购机会", deltas.get("upsell", 0)),
            _seg("平均权益覆盖率", deltas.get("avg_coverage", 0), pct=True),
        ]
        comparison_html = f"<div class='plan' style='background:#f6f8fa;border-left-color:#315363'><b>较上周（{comparison.get('previous_date', '')}）环比</b><br>" + " ｜ ".join(segs) + "</div>"
    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>{title}</title><style>body{{font:14px Arial,'Microsoft YaHei',sans-serif;color:#18313f;max-width:1100px;margin:32px auto;padding:0 24px}}h1{{font-size:28px;margin-bottom:4px}}h2{{margin-top:30px;border-bottom:1px solid #d9e3e6;padding-bottom:8px}}h3{{margin:22px 0 8px;color:#315363}}.muted{{color:#6b7c86}}.plan{{background:#f2faf8;border-left:4px solid #087e72;padding:12px 14px;margin:16px 0}}.kpis{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:24px 0}}.kpi{{border:1px solid #d9e3e6;padding:15px;background:#f7fbfa}}.kpi small{{display:block;color:#6b7c86}}.kpi strong{{font-size:24px;display:block;margin-top:7px}}.chart{{margin:14px 0}}table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #d9e3e6;text-align:left;padding:8px}}th{{color:#6b7c86}}.callout{{background:#edf8f5;padding:16px;line-height:1.8}}@media(max-width:700px){{.kpis{{grid-template-columns:1fr 1fr}}}}</style></head><body><h1>{title}</h1><p class='muted'>{week_label} · 自动生成 · 数据范围：当前上传客户池</p><div class='plan'><b>Agent 分析方案：{mode}</b><br>主分群：{primary} · 排序口径：{ranking_rule}</div><div class='kpis'>{cards}</div>{comparison_html}<h2>本周结论</h2><div class='callout'>{narrative}</div><h2>产品使用与风险分布</h2><div class='chart'>{charts}</div><h2>多维客户分群明细</h2>{detail_tables}<p class='muted'>注：本报告由上传的整理结果生成，指标口径和字段映射应在每周上传时复核。</p></body></html>"""


# ============================================================
# SQL 生成与执行
# ============================================================

def clean_sql(text: str) -> str:
    block = re.search(r"```(?:sql)?\s*(.*?)```", text, flags=re.I | re.S)
    sql = (block.group(1) if block else text).strip().rstrip(";")
    if not re.match(r"^(SELECT|WITH)\b", sql, flags=re.I) or re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|COPY|ATTACH)\b", sql, flags=re.I):
        raise ValueError("仅允许执行只读 SELECT/WITH SQL")
    return sql


def execute_sql_on_df(df: pd.DataFrame, sql: str, limit: int = 200) -> pd.DataFrame:
    con = duckdb.connect(database=":memory:")
    try:
        con.register("customer_usage_summary", df)
        return con.execute(sql).df().head(limit)
    finally:
        con.close()


def rule_generate_sql(question: str) -> str:
    dimension = "industry"
    if any(token in question for token in ["企业规模", "公司规模", "规模", "员工数"]):
        dimension = "company_size"
    elif any(token in question for token in ["续约类型", "续费类型", "续约", "续费", "到期", "临期"]):
        dimension = "renewal_type"
    elif any(token in question for token in ["活跃类型", "活跃度", "活跃", "使用频率"]):
        dimension = "active_type"
    if "风险" in question or "高危" in question:
        return f"SELECT {dimension}, risk_level, COUNT(*) AS customers, ROUND(AVG(coverage), 3) AS avg_coverage FROM customer_usage_summary WHERE risk_level IN ('高危流失','中危预警') GROUP BY 1,2 ORDER BY customers DESC"
    return f"SELECT {dimension}, COUNT(*) AS customers, ROUND(AVG(coverage), 3) AS avg_coverage, ROUND(AVG(type_cnt), 2) AS avg_product_types FROM customer_usage_summary GROUP BY 1 ORDER BY customers DESC"


def generate_sql(question: str) -> tuple[str, str]:
    schema = "customer_usage_summary(customer_id, industry, company_size, renewal_type, active_type, ownership, city_tier, use_times, max_cnt, type_cnt, use_period, max_success_day, renewal_days, annual_value, coverage, idle_high_value, two_week_trend, value_tier, risk_level, risk_score, package_products, used_products)"
    key = os.getenv("OPENAI_API_KEY")
    if key:
        response = OpenAI(api_key=key, base_url=os.getenv("OPENAI_BASE_URL") or None).chat.completions.create(model=os.getenv("OPENAI_MODEL", "gpt-5"), messages=[{"role": "system", "content": f"Generate one DuckDB read-only SQL query only. Use only this schema: {schema}"}, {"role": "user", "content": question}], temperature=0.2)
        return clean_sql(response.choices[0].message.content), "openai"
    return rule_generate_sql(question), "demo_fallback"


# ============================================================
# Tool Calling Agent（工具调用模式）
# ============================================================

SCHEMA_DESCRIPTION = """- customer_id: 客户代码（文本）
- data_date: 数据快照日期（YYYY-MM-DD）
- industry: 行业（电商/教育/金融/制造等）
- company_size: 企业规模（大型/中型/小型等）
- renewal_type: 续约类型（临期续约/近期续约/远期续约）
- active_type: 活跃类型（高活跃/中活跃/低活跃/未活跃）
- ownership: 企业性质（民营/国企等）
- city_tier: 城市层级（一线/新一线/二线等）
- package_products: 购买产品（JSON 数组）
- used_products: 已使用产品（JSON 数组）
- use_times: 使用次数
- max_cnt: 日最大使用次数
- type_cnt: 使用产品种类数
- use_period: 使用时长
- max_success_day: 最大连续使用天数
- renewal_days: 距到期天数
- annual_value: 年合同金额
- coverage: 权益覆盖率（0~1）
- idle_high_value: 闲置高价值权益数
- two_week_trend: 近两周使用趋势（正数上升/负数下降）
- value_tier: 价值分层（普通/重点/高价值）
- risk_level: 风险等级（高危流失/中危预警/体验引导/续费增购/健康）
- risk_score: 风险评分（0~100，越高越危险）
- week_1 至 week_8: 过去 8 周的周使用量"""

AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "describe_dataset",
            "description": "查看当前数据集概况：总行数、数据快照日期、全部字段与类型、各分群维度（行业/规模/续约/活跃）的取值。编写 SQL 前建议先调用一次。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_readonly_sql",
            "description": "在当前客户数据集上执行只读 SQL（仅允许 SELECT / WITH 开头），表名为 customer_usage_summary，返回最多 200 行。支持 WHERE / GROUP BY / ORDER BY / 聚合函数（COUNT / AVG / SUM / ROUND / MIN / MAX）。用于计算客户数、均值、占比、排序等具体数值。若执行失败，请根据错误信息修正后重试。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "只读 SELECT/WITH SQL 语句，例如：SELECT industry, COUNT(*) AS customers FROM customer_usage_summary GROUP BY 1 ORDER BY customers DESC"},
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_detail",
            "description": "查询某个客户的完整权益使用快照（含风险等级、风险评分、权益覆盖率、距到期天数、购买/已使用产品列表等）。",
            "parameters": {
                "type": "object",
                "properties": {"customer_id": {"type": "string", "description": "客户代码，例如 C001"}},
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_risk_summary",
            "description": "返回当前数据集的风险总览：风险等级分布、90 天内到期客户数、高/中危客户数、续费增购机会数、平均权益覆盖率、沉默/低活跃客户数、以及风险评分最高的前 10 家客户。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

AGENT_SYSTEM_PROMPT = f"""你是“企业权益周报分析 Agent”，面向 B2B 客户成功团队。你可以通过工具查询当前上传的客户权益数据集，回答关于续约风险、权益使用、增购机会等业务问题。

数据集表名为 customer_usage_summary，字段说明：
{SCHEMA_DESCRIPTION}

工具使用规则：
1. 动手前先调用 describe_dataset 了解数据概况（字段、快照日期、维度取值）。
2. 需要具体数字或聚合结果时，调用 run_readonly_sql 执行只读 SQL；SQL 只允许 SELECT/WITH 开头，禁止 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE。
3. 涉及具体客户时，调用 get_customer_detail。
4. 涉及整体风险概况时，可调用 get_risk_summary 快速获取。
5. 工具返回 error 时，根据错误信息修正参数后重试（例如 SQL 语法错误、字段名写错、客户不存在）。
6. 完成查询后，用自然语言中文给出最终回答：直接说结论、关键数字和可执行建议，不要输出 JSON，不要复述 SQL，不要声称自己执行了未调用的查询。"""


def _dataset_overview(df: pd.DataFrame) -> dict[str, Any]:
    dates = snapshot_dates(df)
    dimensions: dict[str, list[str]] = {}
    for field in SEGMENT_FIELDS:
        values = [str(value) for value in df[field].dropna().unique().tolist() if str(value).strip()]
        if values:
            dimensions[field] = sorted(set(values))[:20]
    return {
        "table": "customer_usage_summary",
        "rows": int(len(df)),
        "snapshot_date": dates[0] if dates else None,
        "columns": [{"name": column, "dtype": str(df[column].dtype)} for column in df.columns],
        "dimension_values": dimensions,
    }


def _risk_summary(df: pd.DataFrame) -> dict[str, Any]:
    risk = df.risk_level.value_counts().reindex(["高危流失", "中危预警", "体验引导", "续费/增购", "健康"], fill_value=0).to_dict()
    top = df.sort_values(["risk_score", "annual_value"], ascending=False).head(10)
    top = top[["customer_id", "industry", "company_size", "risk_level", "risk_score", "renewal_days", "annual_value", "coverage"]].fillna("").to_dict(orient="records")
    return {
        "risk_distribution": risk,
        "expiring_within_90_days": int((df.renewal_days <= 90).sum()),
        "high_or_medium_risk": int(df.risk_level.isin(["高危流失", "中危预警"]).sum()),
        "upsell_opportunities": int((df.risk_level == "续费/增购").sum()),
        "average_coverage": round(float(df.coverage.mean()), 3) if len(df) else 0,
        "silent_or_low_active": int(df.active_type.isin(["沉默客户", "未活跃", "低活跃"]).sum()),
        "top_risk_customers": top,
    }


def _run_readonly_sql(df: pd.DataFrame, sql: str) -> dict[str, Any]:
    cleaned = clean_sql(sql)
    data = execute_sql_on_df(df, cleaned)
    return {
        "columns": data.columns.tolist(),
        "rows": data.fillna("").to_dict(orient="records"),
        "row_count": int(len(data)),
        "truncated": len(data) == 200,
    }


def _customer_detail(df: pd.DataFrame, customer_id: str) -> dict[str, Any]:
    cid = customer_id.strip()
    if not cid:
        return {"error": "缺少 customer_id 参数"}
    matched = df[df.customer_id.astype(str) == cid]
    if matched.empty:
        return {"error": f"未找到客户 {cid}，可先用 get_risk_summary 或 SQL 查看客户列表"}
    row = matched.sort_values("data_date").iloc[-1]
    record = row.dropna().to_dict()
    return {key: (value.strftime("%Y-%m-%d") if isinstance(value, pd.Timestamp) else value) for key, value in record.items()}


def execute_tool(name: str, args: dict[str, Any], df: pd.DataFrame) -> dict[str, Any]:
    try:
        if name == "describe_dataset":
            return _dataset_overview(df)
        if name == "run_readonly_sql":
            return _run_readonly_sql(df, str(args.get("sql", "")))
        if name == "get_customer_detail":
            return _customer_detail(df, str(args.get("customer_id", "")))
        if name == "get_risk_summary":
            return _risk_summary(df)
        return {"error": f"未知工具：{name}"}
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        return {"error": f"工具执行失败：{exc}"}


def _trim_trace_result(result: dict[str, Any], max_rows: int = 8) -> dict[str, Any]:
    if isinstance(result, dict) and isinstance(result.get("rows"), list) and len(result["rows"]) > max_rows:
        trimmed = dict(result)
        trimmed["rows"] = result["rows"][:max_rows]
        trimmed["note"] = f"（仅展示前 {max_rows} 行，共 {len(result['rows'])} 行）"
        return trimmed
    return result


def run_tool_calling_agent(df: pd.DataFrame, question: str) -> dict[str, Any]:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), base_url=os.getenv("OPENAI_BASE_URL") or None)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    trace: list[dict[str, Any]] = []
    last_query: dict[str, Any] = {"sql": "", "columns": [], "rows": []}

    for step in range(1, MAX_AGENT_ITERATIONS + 1):
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5"),
            messages=messages,
            tools=AGENT_TOOLS,
            tool_choice="auto",
        )
        message = response.choices[0].message
        if not message.tool_calls:
            answer = (message.content or "").strip()
            return {
                "answer": answer or "查询完成，但没有生成可读结论。",
                "trace": trace,
                "last_query": last_query,
                "iterations": step,
                "halted": False,
            }
        messages.append(message.model_dump(exclude_none=True))
        for tool_call in message.tool_calls:
            try:
                args = json.loads(tool_call.function.arguments or "{}")
            except Exception:
                args = {}
            result = execute_tool(tool_call.function.name, args, df)
            if tool_call.function.name == "run_readonly_sql" and "error" not in result:
                last_query = {"sql": str(args.get("sql", "")), "columns": result.get("columns", []), "rows": result.get("rows", [])}
            trace.append({"step": step, "tool": tool_call.function.name, "arguments": args, "result": _trim_trace_result(result)})
            content = json.dumps(result, ensure_ascii=False, default=str)
            if len(content) > 80000:
                content = content[:80000] + " ……（结果过长，已截断）"
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": content})

    return {
        "answer": f"已达到最大工具调用轮次（{MAX_AGENT_ITERATIONS} 轮），未能完成查询。请缩小问题范围后重试。",
        "trace": trace,
        "last_query": last_query,
        "iterations": MAX_AGENT_ITERATIONS,
        "halted": True,
    }


# ============================================================
# FastAPI 应用
# ============================================================

init_db()

app = FastAPI(
    title="B2B Entitlement Agent API",
    version="2.0.0",
    description="Excel-driven entitlement analytics, weekly-report generation, tool-calling SQL Agent, and SQLite persistence.",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def allow_frontend_options(request, call_next):
    if request.method == "OPTIONS" and request.url.path == "/":
        return Response(status_code=204)
    return await call_next(request)


@app.get("/api/v1/health", tags=["platform"])
def health():
    return {
        "status": "ok",
        "service": "b2b-entitlement-agent",
        "time": datetime.now(timezone.utc).isoformat(),
        "storage": "sqlite" if IS_SQLITE else "database",
        "database": DATABASE_URL if not IS_SQLITE else str(ROOT / "entitlement.db"),
        "sessions": count_uploads(),
        "agent_mode": "tool-calling" if os.getenv("OPENAI_API_KEY") else "rule-fallback",
        "agent_tools": [tool["function"]["name"] for tool in AGENT_TOOLS],
    }


@app.get("/api/v1/sample-data", tags=["platform"])
def sample_data():
    path = ROOT / "sample_data_multiweek.csv"
    if not path.exists():
        raise HTTPException(404, "样例数据文件不存在")
    content = "\ufeff" + path.read_text(encoding="utf-8")
    return Response(content=content, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=sample_data_multiweek.csv"})


@app.get("/api/v1/sessions", tags=["uploads"])
def list_sessions():
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT session_id, filename, rows, created_at, mapping, snapshots FROM uploads ORDER BY created_at DESC LIMIT 50")).mappings().all()
    return {
        "storage": "sqlite" if IS_SQLITE else "database",
        "sessions": [
            {
                "session_id": row["session_id"],
                "filename": row["filename"],
                "rows": row["rows"],
                "created_at": row["created_at"],
                "snapshot_count": len(json.loads(row["snapshots"])),
                "mapped_fields": sum(1 for value in json.loads(row["mapping"]).values() if value),
            }
            for row in rows
        ],
    }


@app.post("/api/upload", tags=["legacy"])
@app.post("/api/v1/uploads", tags=["uploads"])
async def upload(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"文件超过 {MAX_UPLOAD_MB}MB 上传限制")
    try:
        df = pd.read_excel(io.BytesIO(content)) if file.filename and file.filename.lower().endswith((".xlsx", ".xls")) else pd.read_csv(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(400, f"无法读取文件：{exc}") from exc
    if df.empty:
        raise HTTPException(400, "上传文件没有数据行")
    session_id = uuid.uuid4().hex
    mapping = infer_mapping(df.columns.tolist())
    normalized = normalise(df, mapping)
    dates = snapshot_dates(normalized)
    save_upload(session_id, file.filename or "upload.csv", len(df), mapping, dates, df, normalized)
    return {
        "upload_id": session_id,
        "session_id": session_id,
        "columns": df.columns.tolist(),
        "mapping": mapping,
        "preview": df.head(8).fillna("").to_dict(orient="records"),
        "rows": len(df),
        "snapshots": dates,
        "snapshot_count": len(dates),
        "dimensions": available_dimensions(df, mapping),
        "auto_ready": True,
        "storage": "sqlite" if IS_SQLITE else "database",
        "expires": "数据已持久化到数据库，服务重启后仍可继续使用该会话",
    }


@app.post("/api/v1/agent/analysis-plan", tags=["agent"])
def analysis_plan(request: AnalysisPlanRequest):
    meta = resolve_session(request.session_id)
    raw = get_raw_df(request.session_id)
    return suggest_analysis_plan(raw if raw is not None else pd.DataFrame(), request.mapping, request.goal)


@app.post("/api/analyze", tags=["legacy"])
@app.post("/api/v1/analysis/customer-pool", tags=["analysis"])
def analyze(request: AnalyzeRequest):
    history = resolve_normalized(request.session_id, request.mapping)
    df, selected_date = select_snapshot(history, request.snapshot_date)
    df = apply_filters(df, request.industry, request.renewal_max, request.value_tier, request.filters)
    save_analysis_snapshot(request.session_id, selected_date, df)
    risk = df.risk_level.value_counts().reindex(["高危流失", "中危预警", "体验引导", "续费/增购", "健康"], fill_value=0).to_dict()
    industry = df.groupby("industry", as_index=False).agg(customers=("customer_id", "count"), avg_coverage=("coverage", "mean"), avg_idle=("idle_high_value", "mean"), high_risk=("risk_level", lambda x: int(x.isin(["高危流失", "中危预警"]).sum()))).round(3)
    export = df.sort_values(["risk_score", "annual_value"], ascending=False).head(200)
    focus_dimensions = [field for field in request.focus_dimensions if field in SEGMENT_FIELDS] or ["industry"]
    summary = pool_summary(df)
    comparison = build_comparison(history, selected_date, summary, request)
    return {"snapshot_date": selected_date, "available_snapshots": snapshot_dates(history), "summary": summary, "comparison": comparison, "risk": risk, "industry": industry.to_dict(orient="records"), "breakdowns": segment_breakdowns(df, focus_dimensions), "focus_dimensions": focus_dimensions, "report": action_plan(df), "download_rows": export.to_dict(orient="records")}


@app.post("/api/query", tags=["legacy"])
@app.post("/api/v1/agent/sql-queries", tags=["agent"])
def query(request: QueryRequest):
    snapshot = load_analysis_snapshot(request.session_id)
    if snapshot is None:
        raise HTTPException(400, "请先完成文件分析，再发起 Agent 查询")
    df, snapshot_date = snapshot

    # 1) Tool Calling Agent（有 Key 时优先）
    if os.getenv("OPENAI_API_KEY"):
        try:
            agent_result = run_tool_calling_agent(df, request.question)
            last_query = agent_result.get("last_query") or {}
            return {
                "source": "openai_tool_calling",
                "answer": agent_result.get("answer", ""),
                "sql": last_query.get("sql", ""),
                "columns": last_query.get("columns", []),
                "rows": last_query.get("rows", []),
                "summary": f"Agent 共调用 {len(agent_result.get('trace', []))} 次工具，已完成回答。",
                "tool_calls": agent_result.get("trace", []),
                "iterations": agent_result.get("iterations", 0),
                "halted": agent_result.get("halted", False),
                "snapshot_date": snapshot_date,
            }
        except Exception:
            pass  # 降级到传统 NL2SQL / 规则查询

    # 2) 传统 NL2SQL（有 Key 但工具调用不可用时）
    if os.getenv("OPENAI_API_KEY"):
        try:
            sql, _ = generate_sql(request.question)
            source = "openai_sql"
        except Exception:
            sql = rule_generate_sql(request.question)
            source = "demo_fallback"
    else:
        sql = rule_generate_sql(request.question)
        source = "demo_fallback"

    try:
        data = execute_sql_on_df(df, sql)
    except Exception as exc:
        raise HTTPException(400, f"SQL 执行失败：{exc}") from exc
    return {
        "source": source,
        "answer": f"已执行只读 SQL，返回 {len(data)} 行结果，详见下方表格。",
        "sql": sql,
        "columns": data.columns.tolist(),
        "rows": data.fillna("").to_dict(orient="records"),
        "summary": f"已执行只读 SQL，返回 {len(data)} 行结果。",
        "tool_calls": [],
        "iterations": 0,
        "halted": False,
        "snapshot_date": snapshot_date,
    }


@app.post("/api/weekly-report", tags=["legacy"])
@app.post("/api/v1/reports/weekly", tags=["reports"])
def weekly_report(request: WeeklyReportRequest):
    history = resolve_normalized(request.session_id, request.mapping)
    df, selected_date = select_snapshot(history, request.snapshot_date)
    df = apply_filters(df, request.industry, request.renewal_max, request.value_tier, request.filters)
    focus_dimensions = [field for field in request.focus_dimensions if field in SEGMENT_FIELDS] or ["industry"]
    comparison = build_comparison(history, selected_date, pool_summary(df), request)
    html = weekly_report_html(df, request.report_title, request.week_label, focus_dimensions, request.analysis_plan, comparison)
    return {"title": request.report_title, "week_label": request.week_label, "html": html, "rows": len(df), "snapshot_date": selected_date}


@app.post("/api/v1/reports/auto", tags=["reports"])
def auto_report(request: AutoReportRequest):
    meta = resolve_session(request.session_id)
    history = resolve_normalized(request.session_id, meta["mapping"])
    df, selected_date = select_snapshot(history)
    html = weekly_report_html(df, request.report_title, request.week_label, SEGMENT_FIELDS)
    return {"title": request.report_title, "week_label": request.week_label, "html": html, "rows": len(df), "snapshot_date": selected_date, "mapping": meta["mapping"], "detected_fields": [key for key, value in meta["mapping"].items() if value]}


@app.options("/", include_in_schema=False)
def frontend_options():
    return Response(status_code=204)


# 优先托管 React 构建产物（frontend-react/dist），未构建时回退到原生版（frontend/）
STATIC_DIR = REACT_DIST if REACT_DIST.is_dir() else FRONTEND
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")
