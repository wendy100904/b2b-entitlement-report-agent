import { useState } from "react";
import WorkflowStepper from "./components/WorkflowStepper";
import UploadPanel from "./components/UploadPanel";
import MappingPanel from "./components/MappingPanel";
import AnalysisPanel from "./components/AnalysisPanel";
import WeeklyReportPanel from "./components/WeeklyReportPanel";
import Nl2SqlPanel from "./components/Nl2SqlPanel";
import type { Dimension, PlanResponse } from "./types";

// 顶层组件：持有会话级全局状态，通过 props 下发到各面板
export default function App() {
  const [sessionId, setSessionId] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [dimensions, setDimensions] = useState<Dimension[]>([]);
  const [snapshots, setSnapshots] = useState<string[]>([]);
  const [step, setStep] = useState(1);
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [weeklyHtml, setWeeklyHtml] = useState("");

  const [showMapping, setShowMapping] = useState(false);
  const [showAnalysis, setShowAnalysis] = useState(false);
  const [showAgent, setShowAgent] = useState(false);
  const [showWeekly, setShowWeekly] = useState(false);

  function handleUploaded(d: {
    sessionId: string;
    columns: string[];
    mapping: Record<string, string | null>;
    dimensions: Dimension[];
    snapshots: string[];
  }) {
    setSessionId(d.sessionId);
    setColumns(d.columns);
    setMapping(d.mapping);
    setDimensions(d.dimensions);
    setSnapshots(d.snapshots);
    setShowMapping(true);
    setShowAnalysis(true);
    setShowWeekly(false);
    setShowAgent(false);
    setStep(2);
  }

  function handleAnalyzed() {
    setShowAgent(true);
    setStep(3);
  }

  function handleWeeklyGenerated(html: string) {
    setWeeklyHtml(html);
    setShowWeekly(true);
    setStep(4);
  }

  return (
    <>
      <header>
        <div className="topbar">
          <div className="brand">
            <div className="eyebrow">B2B COMMERCIAL ANALYTICS</div>
            <h1>企业权益周报 Agent</h1>
            <p>批量识别权益使用、定位续费风险，自动产出可交付周报</p>
          </div>
          <div className="header-meta">
            <span className="status-chip"><i></i>API 服务正常</span>
            <span className="status-chip">数据源：SQLite + Excel / CSV</span>
            <span className="status-chip">React 18 + TypeScript</span>
          </div>
        </div>
      </header>

      <main>
        <WorkflowStepper step={step} />

        <UploadPanel disabled={!!sessionId} onUploaded={handleUploaded} />

        {showMapping && (
          <MappingPanel columns={columns} mapping={mapping} onChange={setMapping} />
        )}

        {showAnalysis && (
          <AnalysisPanel
            sessionId={sessionId}
            mapping={mapping}
            dimensions={dimensions}
            snapshots={snapshots}
            plan={plan}
            setPlan={setPlan}
            onAnalyzed={handleAnalyzed}
            onWeeklyGenerated={handleWeeklyGenerated}
          />
        )}

        {showWeekly && <WeeklyReportPanel html={weeklyHtml} />}

        {showAgent && <Nl2SqlPanel sessionId={sessionId} />}
      </main>
    </>
  );
}
