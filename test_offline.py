"""离线验证脚本：不依赖真实 API Key，验证 Tool Calling 循环与数据库持久化。"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np

import backend.main as m


def make_fake_openai(script):
    """构造一个假 OpenAI 客户端：按脚本依次返回工具调用或最终回答。"""
    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            step = self.calls
            self.calls += 1
            messages = kwargs["messages"]
            tools = kwargs.get("tools", [])
            assert tools, "tools 参数必须传入"
            if step >= len(script):
                raise AssertionError("脚本用尽")
            return FakeResponse(script[step], tools)

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeClient:
        def __init__(self):
            self.chat = FakeChat()

    return FakeClient()


class FakeToolCall:
    def __init__(self, name, arguments):
        self.id = f"call_{name}"
        self.type = "function"
        self.function = type("F", (), {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)})()


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none=True):
        data = {"role": "assistant"}
        if self.content:
            data["content"] = self.content
        if self.tool_calls:
            data["tool_calls"] = [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in self.tool_calls
            ]
        return data


class FakeChoice:
    def __init__(self, message):
        self.message = message


class FakeResponse:
    def __init__(self, spec, tools):
        self.choices = [FakeChoice(FakeMessage(
            content=spec.get("content"),
            tool_calls=[FakeToolCall(t["name"], t.get("arguments", {})) for t in spec.get("tool_calls", [])],
        ))]


def make_sample_df():
    rows = [
        {"customer_id": "C001", "data_date": "2026-08-01", "industry": "电商", "company_size": "大型",
         "renewal_type": "临期续约", "active_type": "低活跃", "ownership": "民营", "city_tier": "一线",
         "package_products": ["简历快读", "智能邀约", "超级聊聊"], "used_products": ["简历快读"],
         "use_times": 40, "max_cnt": 5, "type_cnt": 1, "use_period": 12, "max_success_day": 3,
         "renewal_days": 25, "annual_value": 180000, "coverage": 0.33, "idle_high_value": 2,
         "two_week_trend": -0.5, "value_tier": "高价值", "risk_level": "高危流失", "risk_score": 100},
        {"customer_id": "C002", "data_date": "2026-08-01", "industry": "教育", "company_size": "中型",
         "renewal_type": "远期续约", "active_type": "高活跃", "ownership": "民营", "city_tier": "新一线",
         "package_products": ["简历快读", "超级聊聊"], "used_products": ["简历快读", "超级聊聊"],
         "use_times": 120, "max_cnt": 10, "type_cnt": 2, "use_period": 30, "max_success_day": 9,
         "renewal_days": 200, "annual_value": 90000, "coverage": 1.0, "idle_high_value": 0,
         "two_week_trend": 0.2, "value_tier": "重点", "risk_level": "健康", "risk_score": 8},
        {"customer_id": "C003", "data_date": "2026-08-08", "industry": "金融", "company_size": "大型",
         "renewal_type": "临期续约", "active_type": "未活跃", "ownership": "国企", "city_tier": "一线",
         "package_products": ["智能邀约"], "used_products": [],
         "use_times": 0, "max_cnt": 0, "type_cnt": 0, "use_period": 0, "max_success_day": 0,
         "renewal_days": 10, "annual_value": 250000, "coverage": 0.0, "idle_high_value": 1,
         "two_week_trend": 0.0, "value_tier": "高价值", "risk_level": "高危流失", "risk_score": 82},
    ]
    for i in range(1, 9):
        for r in rows:
            r[f"week_{i}"] = 5
    return pd.DataFrame(rows)


def test_tool_calling_loop():
    df = make_sample_df()
    script = [
        # 第1轮：调用 describe_dataset
        {"tool_calls": [{"name": "describe_dataset", "arguments": {}}]},
        # 第2轮：调用 run_readonly_sql（含一个错误 SQL 先测错误反馈）
        {"tool_calls": [{"name": "run_readonly_sql", "arguments": {"sql": "SELECT industry FROM no_such_table"}}]},
        # 第3轮：修正后的 SQL
        {"tool_calls": [{"name": "run_readonly_sql", "arguments": {"sql": "SELECT industry, COUNT(*) AS customers FROM customer_usage_summary GROUP BY 1 ORDER BY customers DESC"}}]},
        # 第4轮：get_risk_summary
        {"tool_calls": [{"name": "get_risk_summary", "arguments": {}}]},
        # 第5轮：get_customer_detail
        {"tool_calls": [{"name": "get_customer_detail", "arguments": {"customer_id": "C001"}}]},
        # 第6轮：最终回答
        {"content": "电商行业高危客户最多，共 1 家（C001，风险评分 100）。"},
    ]
    fake = make_fake_openai(script)
    original = m.OpenAI
    m.OpenAI = lambda *a, **k: fake
    try:
        result = m.run_tool_calling_agent(df, "哪个行业高危客户最多？")
    finally:
        m.OpenAI = original

    assert result["halted"] is False, "应正常结束而非达到轮次上限"
    assert "电商行业高危客户最多" in result["answer"], f"最终回答异常: {result['answer']}"
    tools_used = [t["tool"] for t in result["trace"]]
    assert tools_used == ["describe_dataset", "run_readonly_sql", "run_readonly_sql", "get_risk_summary", "get_customer_detail"], f"工具轨迹异常: {tools_used}"
    assert result["iterations"] == 6, f"迭代次数异常: {result['iterations']}"
    # 验证错误 SQL 反馈进入了轨迹
    assert result["trace"][1]["result"].get("error"), "错误 SQL 应返回 error 信息供模型修正"
    # 验证 last_query 是最后一次成功的 SQL
    assert "industry" in result["last_query"]["sql"]
    assert result["last_query"]["rows"], "last_query 应有结果行"
    print("✓ test_tool_calling_loop 通过：5 次工具调用 + 最终回答，错误 SQL 已回传模型")


def test_tools_individually():
    df = make_sample_df()
    overview = m.execute_tool("describe_dataset", {}, df)
    assert overview["rows"] == 3 and overview["snapshot_date"] == "2026-08-08"
    risk = m.execute_tool("get_risk_summary", {}, df)
    assert risk["high_or_medium_risk"] == 2 and risk["top_risk_customers"][0]["customer_id"] == "C001"
    detail = m.execute_tool("get_customer_detail", {"customer_id": "C001"}, df)
    assert detail["customer_id"] == "C001" and isinstance(detail["used_products"], list)
    missing = m.execute_tool("get_customer_detail", {"customer_id": "NOPE"}, df)
    assert "error" in missing
    bad_sql = m.execute_tool("run_readonly_sql", {"sql": "DELETE FROM customer_usage_summary"}, df)
    assert "error" in bad_sql, "写操作必须被拒绝"
    print("✓ test_tools_individually 通过：4 个工具 + 只读安全校验")


def test_db_roundtrip():
    session_id = "test_session_roundtrip"
    raw = make_sample_df()
    mapping = {f: None for f in m.FIELDS}
    normalized = m.normalise(raw, mapping)
    dates = m.snapshot_dates(normalized)
    m.save_upload(session_id, "test.csv", len(raw), mapping, dates, raw, normalized)

    meta = m.get_upload_meta(session_id)
    assert meta is not None and meta["rows"] == 3

    loaded = m.load_customer_usage(session_id)
    assert len(loaded) == 3, f"customer_usage 行数异常: {len(loaded)}"
    assert loaded["risk_level"].tolist() == normalized["risk_level"].tolist(), "风险等级往返不一致"
    assert pd.api.types.is_numeric_dtype(loaded["risk_score"]), "risk_score 应为数值"
    assert isinstance(loaded["used_products"].iloc[0], list), "列表字段应还原为 list"
    assert pd.api.types.is_datetime64_any_dtype(loaded["data_date"]), "data_date 应为时间类型"
    assert round(float(loaded["coverage"].iloc[0]), 3) == round(float(normalized["coverage"].iloc[0]), 3)

    raw_loaded = m.get_raw_df(session_id)
    assert len(raw_loaded) == 3 and raw_loaded["customer_id"].iloc[0] == "C001"

    # 分析快照往返
    m.save_analysis_snapshot(session_id, "2026-08-08", normalized)
    snap_df, snap_date = m.load_analysis_snapshot(session_id)
    assert snap_date == "2026-08-08" and len(snap_df) == 3
    assert pd.api.types.is_numeric_dtype(snap_df["risk_score"])

    # resolve_normalized：相同 mapping 走 DB；不同 mapping 触发重算
    same = m.resolve_normalized(session_id, mapping)
    assert len(same) == 3
    other_mapping = dict(mapping)
    other_mapping["industry"] = None
    diff = m.resolve_normalized(session_id, other_mapping)
    assert len(diff) == 3

    assert m.count_uploads() >= 1
    print("✓ test_db_roundtrip 通过：元数据/原始/规范化/快照四表往返一致")


if __name__ == "__main__":
    m.init_db()
    test_tools_individually()
    test_tool_calling_loop()
    test_db_roundtrip()
    print("\n全部离线验证通过 ✓")
