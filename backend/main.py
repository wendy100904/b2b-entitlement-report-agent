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
from pydantic import BaseModel


ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
HIGH_VALUE = {"简历快读", "智能邀约", "超级聊聊"}
SESSIONS: dict[str, dict[str, pd.DataFrame]] = {}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "30"))

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
        from openai import OpenAI
        response = OpenAI(api_key=key).responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5"),
            input=[{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
        )
        content = response.output_text.strip()
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
    product_fig = px.bar(product_summary.sort_values("use_times"), x="use_times", y="product", orientation="h", title="五类产品使用情况")
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


def clean_sql(text: str) -> str:
    block = re.search(r"```(?:sql)?\s*(.*?)```", text, flags=re.I | re.S)
    sql = (block.group(1) if block else text).strip().rstrip(";")
    if not re.match(r"^(SELECT|WITH)\b", sql, flags=re.I) or re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|COPY|ATTACH)\b", sql, flags=re.I):
        raise ValueError("仅允许执行只读 SELECT/WITH SQL")
    return sql


def generate_sql(question: str) -> tuple[str, str]:
    schema = "customer_usage_summary(customer_id, industry, company_size, renewal_type, active_type, ownership, city_tier, use_times, max_cnt, type_cnt, use_period, max_success_day, renewal_days, annual_value, coverage, idle_high_value, two_week_trend, value_tier, risk_level, risk_score, package_products, used_products)"
    key = os.getenv("OPENAI_API_KEY")
    if key:
        from openai import OpenAI
        response = OpenAI(api_key=key).responses.create(model=os.getenv("OPENAI_MODEL", "gpt-5"), input=[{"role": "system", "content": f"Generate one DuckDB read-only SQL query only. Use only this schema: {schema}"}, {"role": "user", "content": question}])
        return clean_sql(response.output_text), "openai"
    dimension = "industry"
    if any(token in question for token in ["企业规模", "公司规模", "规模", "员工数"]):
        dimension = "company_size"
    elif any(token in question for token in ["续约类型", "续费类型", "续约", "续费", "到期", "临期"]):
        dimension = "renewal_type"
    elif any(token in question for token in ["活跃类型", "活跃度", "活跃", "使用频率"]):
        dimension = "active_type"
    if "风险" in question or "高危" in question:
        return f"SELECT {dimension}, risk_level, COUNT(*) AS customers, ROUND(AVG(coverage), 3) AS avg_coverage FROM customer_usage_summary WHERE risk_level IN ('高危流失','中危预警') GROUP BY 1,2 ORDER BY customers DESC", "demo_fallback"
    return f"SELECT {dimension}, COUNT(*) AS customers, ROUND(AVG(coverage), 3) AS avg_coverage, ROUND(AVG(type_cnt), 2) AS avg_product_types FROM customer_usage_summary GROUP BY 1 ORDER BY customers DESC", "demo_fallback"


app = FastAPI(
    title="B2B Entitlement Agent API",
    version="1.0.0",
    description="Excel-driven entitlement analytics, weekly-report generation, and read-only SQL Agent.",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def allow_frontend_options(request, call_next):
    if request.method == "OPTIONS" and request.url.path == "/":
        return Response(status_code=204)
    return await call_next(request)


@app.get("/api/v1/health", tags=["platform"])
def health():
    return {"status": "ok", "service": "b2b-entitlement-agent", "time": datetime.now(timezone.utc).isoformat(), "storage": "ephemeral-memory"}


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
    SESSIONS[session_id] = {"raw": df, "mapping": mapping, "created_at": pd.Timestamp.utcnow()}
    normalized = normalise(df, mapping)
    dates = snapshot_dates(normalized)
    return {"upload_id": session_id, "session_id": session_id, "columns": df.columns.tolist(), "mapping": mapping, "preview": df.head(8).fillna("").to_dict(orient="records"), "rows": len(df), "snapshots": dates, "snapshot_count": len(dates), "dimensions": available_dimensions(df, mapping), "auto_ready": True, "expires": "服务重启后失效；生产环境请替换为对象存储和数据库"}


@app.post("/api/v1/agent/analysis-plan", tags=["agent"])
def analysis_plan(request: AnalysisPlanRequest):
    session = SESSIONS.get(request.session_id)
    if not session:
        raise HTTPException(404, "上传会话已失效，请重新上传文件")
    return suggest_analysis_plan(session["raw"], request.mapping, request.goal)


@app.post("/api/analyze", tags=["legacy"])
@app.post("/api/v1/analysis/customer-pool", tags=["analysis"])
def analyze(request: AnalyzeRequest):
    session = SESSIONS.get(request.session_id)
    if not session:
        raise HTTPException(404, "上传会话已失效，请重新上传文件")
    history = normalise(session["raw"], request.mapping)
    df, selected_date = select_snapshot(history, request.snapshot_date)
    df = apply_filters(df, request.industry, request.renewal_max, request.value_tier, request.filters)
    session["diagnostics"] = df
    session["history"] = history
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
    session = SESSIONS.get(request.session_id)
    if not session or "diagnostics" not in session:
        raise HTTPException(400, "请先完成文件分析，再发起 Agent 查询")
    sql, source = generate_sql(request.question)
    con = duckdb.connect(database=":memory:")
    con.register("customer_usage_summary", session["diagnostics"])
    try:
        data = con.execute(sql).df()
    finally:
        con.close()
    return {"source": source, "sql": sql, "columns": data.columns.tolist(), "rows": data.fillna("").to_dict(orient="records"), "summary": f"已执行只读 SQL，返回 {len(data)} 行结果。"}


@app.post("/api/weekly-report", tags=["legacy"])
@app.post("/api/v1/reports/weekly", tags=["reports"])
def weekly_report(request: WeeklyReportRequest):
    session = SESSIONS.get(request.session_id)
    if not session:
        raise HTTPException(404, "上传会话已失效，请重新上传文件")
    history = normalise(session["raw"], request.mapping)
    df, selected_date = select_snapshot(history, request.snapshot_date)
    df = apply_filters(df, request.industry, request.renewal_max, request.value_tier, request.filters)
    focus_dimensions = [field for field in request.focus_dimensions if field in SEGMENT_FIELDS] or ["industry"]
    comparison = build_comparison(history, selected_date, pool_summary(df), request)
    html = weekly_report_html(df, request.report_title, request.week_label, focus_dimensions, request.analysis_plan, comparison)
    return {"title": request.report_title, "week_label": request.week_label, "html": html, "rows": len(df), "snapshot_date": selected_date}


@app.post("/api/v1/reports/auto", tags=["reports"])
def auto_report(request: AutoReportRequest):
    session = SESSIONS.get(request.session_id)
    if not session:
        raise HTTPException(404, "上传会话已失效，请重新上传文件")
    df, selected_date = select_snapshot(normalise(session["raw"], session["mapping"]))
    html = weekly_report_html(df, request.report_title, request.week_label, SEGMENT_FIELDS)
    return {"title": request.report_title, "week_label": request.week_label, "html": html, "rows": len(df), "snapshot_date": selected_date, "mapping": session["mapping"], "detected_fields": [key for key, value in session["mapping"].items() if value]}


@app.options("/", include_in_schema=False)
def frontend_options():
    return Response(status_code=204)


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
