import { useState } from "react";
import { buildAnalysisPlan, runAnalysis, makeWeeklyReport } from "../api";
import type {
  AnalysisPayload,
  AnalysisResult,
  Dimension,
  PlanResponse,
} from "../types";

interface Props {
  sessionId: string;
  mapping: Record<string, string | null>;
  dimensions: Dimension[];
  snapshots: string[];
  plan: PlanResponse | null;
  setPlan: (p: PlanResponse) => void;
  onAnalyzed: () => void;
  onWeeklyGenerated: (html: string) => void;
}

const DEFAULT_GOAL =
  "识别未来 90 天内需要优先跟进的续费风险客户，并按行业、企业规模和活跃类型制定策略。";

function planDetailItems(plan: PlanResponse) {
  const label = (field: string) =>
    (plan.available_dimensions.find((d) => d.field === field) || {}).label || field;
  return [
    ["主分群", label(plan.primary_dimension)],
    ["对照分群", plan.focus_dimensions.map(label).join("、")],
    ["核心指标", plan.metrics.join("、")],
    ["排序方式", plan.ranking_rule],
    ["报告结构", plan.report_sections.join(" → ")],
    ["运营动作", plan.actions.join("；")],
  ];
}

export default function AnalysisPanel(props: Props) {
  const { sessionId, mapping, dimensions, snapshots, plan, setPlan, onAnalyzed, onWeeklyGenerated } = props;

  const [goal, setGoal] = useState(DEFAULT_GOAL);
  const [planStatus, setPlanStatus] = useState(
    "上传数据后，Agent 会根据字段完整度和经营问题生成分析方案。"
  );
  const [dynFilters, setDynFilters] = useState<Record<string, string>>({});
  const [snapshotDate, setSnapshotDate] = useState("最新一周");
  const [industry, setIndustry] = useState("全部");
  const [windowDays, setWindowDays] = useState(90);
  const [tier, setTier] = useState("全部");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [reportTitle, setReportTitle] = useState("企业权益产品周报");
  const [weekLabel, setWeekLabel] = useState("第 N 周");

  function payload(extra?: Partial<AnalysisPayload>): AnalysisPayload {
    return {
      session_id: sessionId,
      mapping,
      snapshot_date: snapshotDate,
      industry,
      renewal_max: windowDays,
      value_tier: tier,
      filters: dynFilters,
      focus_dimensions: (dimensions || []).map((d) => d.field),
      ...extra,
    };
  }

  async function handleBuildPlan() {
    if (!sessionId) return;
    setBusy(true);
    try {
      setPlanStatus("Agent 正在读取客户池画像并生成分析方案...");
      const d = await buildAnalysisPlan(sessionId, mapping, goal);
      setPlan(d);
      setWindowDays(d.renewal_max);
      const filters = d.filters || {};
      if (filters.industry) setIndustry(filters.industry);
      setDynFilters((prev) => ({ ...prev, ...filters }));
      const label = (field: string) =>
        (d.available_dimensions.find((x) => x.field === field) || {}).label || field;
      setPlanStatus(
        `${d.source === "openai_planner" ? "AI 策划" : "规则策划"}完成：${d.mode}。主分群为 ${label(d.primary_dimension)}，已自动回填适用的筛选范围。点击“按当前方案生成报告”查看诊断结果。`
      );
    } catch (e) {
      setPlanStatus(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleAnalyze() {
    setBusy(true);
    try {
      const d = await runAnalysis(payload());
      setResult(d);
      onAnalyzed();
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleMakeWeekly() {
    setBusy(true);
    try {
      const d = await makeWeeklyReport({
        ...payload(),
        report_title: reportTitle,
        week_label: weekLabel,
        analysis_plan: plan,
      });
      onWeeklyGenerated(d.html);
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function downloadCsv() {
    const rows = result?.download_rows || [];
    if (!rows.length) return;
    const cols = Object.keys(rows[0]);
    const csv = [
      cols.join(","),
      ...rows.map((r) => cols.map((c) => `"${String(r[c] ?? "").replaceAll('"', '""')}"`).join(",")),
    ].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["\ufeff" + csv], { type: "text/csv" }));
    a.download = "entitlement_risk_pool.csv";
    a.click();
  }

  const extraDims = (dimensions || []).filter((d) => d.field !== "industry");
  const industryDim = (dimensions || []).find((d) => d.field === "industry");
  const deltas = result?.comparison?.deltas;

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>运行批量客户池诊断</h2>
          <p className="panel-kicker">输入本次经营问题，Agent 会基于数据画像规划分析范围、分群口径、指标和周报结构。</p>
        </div>
        <span className="section-tag">ANALYSIS</span>
      </div>

      <div className="mode-planner">
        <textarea value={goal} onChange={(e) => setGoal(e.target.value)} rows={2} />
        <button onClick={handleBuildPlan} disabled={busy}>生成分析方案</button>
        <p className="plan-status">{planStatus}</p>
        {plan && (
          <div className="plan-detail">
            {planDetailItems(plan).map(([title, value]) => (
              <div className="plan-item" key={title}>
                <b>{title}</b>{value}
              </div>
            ))}
          </div>
        )}
      </div>

      {extraDims.length > 0 && (
        <div className="dimension-filters">
          {extraDims.map((d) => (
            <label key={d.field}>
              {d.label}
              <span className="source-note">{d.source}</span>
              <select
                value={dynFilters[d.field] ?? "全部"}
                onChange={(e) => setDynFilters({ ...dynFilters, [d.field]: e.target.value })}
              >
                <option value="全部">全部</option>
                {d.values.map((v) => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            </label>
          ))}
        </div>
      )}

      <div className="filters">
        <div>
          <label>分析周期
            <select value={snapshotDate} onChange={(e) => setSnapshotDate(e.target.value)}>
              <option value="最新一周">最新一周</option>
              {snapshots.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
        </div>
        <div>
          <label>行业
            <select value={industry} onChange={(e) => setIndustry(e.target.value)}>
              <option>全部</option>
              {(industryDim?.values || []).map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          </label>
        </div>
        <div>
          <label>到期窗口
            <select value={windowDays} onChange={(e) => setWindowDays(Number(e.target.value))}>
              {[30, 60, 90, 180].map((w) => (
                <option key={w} value={w}>{w} 天</option>
              ))}
            </select>
          </label>
        </div>
        <div>
          <label>客户价值
            <select value={tier} onChange={(e) => setTier(e.target.value)}>
              {["全部", "高价值", "重点", "普通"].map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </label>
        </div>
        <button onClick={handleAnalyze} disabled={busy}>按当前方案生成报告</button>
      </div>

      {result && (
        <div className="subsection">
          <h3>批量诊断报告</h3>
          <div className="grid">
            <Metric label="客户池规模" value={result.summary.customers} delta={deltas?.customers} />
            <Metric label="高 / 中危客户" value={result.summary.high_risk} delta={deltas?.high_risk} higherWorse />
            <Metric label="续费 / 增购机会" value={result.summary.upsell} delta={deltas?.upsell} />
            <Metric label="平均权益覆盖率" value={(result.summary.avg_coverage * 100).toFixed(1) + "%"} delta={deltas?.avg_coverage} pct />
          </div>

          <div className="subsection">
            <h3>风险分布</h3>
            {Object.entries(result.risk).map(([k, v]) => (
              <p key={k}><b>{k}</b>：{v}</p>
            ))}
          </div>

          {result.breakdowns?.map((b, i) => (
            <div className="subsection" key={b.label}>
              <h3>{i === 0 ? `${b.label}分群汇总` : b.label}</h3>
              <DataTable rows={b.rows} />
            </div>
          ))}

          <div className="subsection">
            <h3>自动 SOP</h3>
            <pre>{result.report}</pre>
            <div className="report-actions">
              <button className="button-ghost" onClick={downloadCsv}>下载客户池 CSV</button>
              <input value={reportTitle} onChange={(e) => setReportTitle(e.target.value)} />
              <input value={weekLabel} onChange={(e) => setWeekLabel(e.target.value)} />
              <button onClick={handleMakeWeekly} disabled={busy}>生成带图表周报</button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function Metric({
  label, value, delta, pct, higherWorse,
}: {
  label: string;
  value: string | number;
  delta?: number;
  pct?: boolean;
  higherWorse?: boolean;
}) {
  let deltaNode: React.ReactNode = null;
  if (delta === undefined || delta === null || Number.isNaN(delta)) {
    deltaNode = <span className="delta flat">持平<small>较上周</small></span>;
  } else {
    const val = pct ? delta * 100 : delta;
    const arrow = val > 0 ? "▲" : val < 0 ? "▼" : "＝";
    const text = pct ? (val > 0 ? "+" : "") + val.toFixed(1) + "pt" : (val > 0 ? "+" : "") + val;
    const good = val === 0 ? null : higherWorse ? val < 0 : val > 0;
    deltaNode = (
      <span className={`delta ${val === 0 ? "flat" : good ? "down" : "up"}`}>
        {arrow} {text}<small>较上周</small>
      </span>
    );
  }
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {deltaNode}
    </div>
  );
}

function DataTable({ rows }: { rows: Record<string, string | number>[] }) {
  if (!rows || !rows.length) return <p className="muted">没有数据</p>;
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
