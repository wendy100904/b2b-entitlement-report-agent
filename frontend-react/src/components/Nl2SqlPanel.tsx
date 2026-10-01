import { useState } from "react";
import { askQuestion } from "../api";
import type { QueryResponse } from "../types";

const DEFAULT_QUESTION = "未来90天内哪些行业的高危和中危客户最多？";

export default function Nl2SqlPanel({ sessionId }: { sessionId: string }) {
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [status, setStatus] = useState("");
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleAsk() {
    setBusy(true);
    try {
      setStatus("Agent 正在分析问题并调用工具...");
      const d = await askQuestion(sessionId, question);
      setResult(d);
      const calls = d.tool_calls || [];
      const steps = [...new Set(calls.map((t) => t.tool))];
      const sourceLabel =
        d.source === "openai_tool_calling"
          ? `Tool Calling Agent${calls.length ? `（调用工具 ${calls.length} 次：${steps.join(" / ")}）` : ""}`
          : d.source === "openai_sql"
            ? "SQL 生成"
            : "规则降级查询";
      setStatus("完成：" + sourceLabel);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>NL2SQL 自然语言查询</h2>
          <p className="panel-kicker">用大白话提问，Agent 自动查数据并给出结论（无 Key 时为规则降级）。</p>
        </div>
        <span className="section-tag">QUERY</span>
      </div>
      <div className="agent-box">
        <div>
          <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={3} />
          <p className="agent-status">{status}</p>
        </div>
        <button onClick={handleAsk} disabled={busy}>
          {busy ? "思考中..." : "让 Agent 回答"}
        </button>
      </div>

      {result?.answer && (
        <div className="plan">
          <b>Agent 结论</b>
          <p style={{ margin: "8px 0 0", lineHeight: 1.8 }}>{result.answer}</p>
        </div>
      )}
      {result?.sql && <pre>{result.sql}</pre>}
      {result?.rows?.length ? (
        <DataTable rows={result.rows} />
      ) : (
        result?.answer && <p className="muted">（结论已在上方给出，无需表格）</p>
      )}
    </section>
  );
}

function DataTable({ rows }: { rows: Record<string, string | number>[] }) {
  const cols = Object.keys(rows[0]);
  return (
    <table>
      <thead>
        <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
      </thead>
      <tbody>
        {rows.slice(0, 30).map((r, i) => (
          <tr key={i}>
            {cols.map((c) => <td key={c}>{String(r[c])}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
