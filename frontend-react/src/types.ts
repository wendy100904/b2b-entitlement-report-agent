// 与后端 /api/v1 接口对应的 TypeScript 类型定义

export interface Dimension {
  field: string;
  label: string;
  values: string[];
  source: string;
}

export interface UploadResponse {
  session_id: string;
  upload_id: string;
  columns: string[];
  mapping: Record<string, string | null>;
  rows: number;
  snapshots: string[];
  snapshot_count: number;
  dimensions: Dimension[];
  auto_ready: boolean;
  storage: string;
  expires: string;
}

export interface PlanResponse {
  source: string; // openai_planner | rule_planner
  mode: string;
  primary_dimension: string;
  focus_dimensions: string[];
  renewal_max: number;
  filters: Record<string, string>;
  metrics: string[];
  ranking_rule: string;
  report_sections: string[];
  actions: string[];
  available_dimensions: Dimension[];
}

export interface Summary {
  customers: number;
  high_risk: number;
  upsell: number;
  avg_coverage: number;
}

export interface Delta {
  customers?: number;
  high_risk?: number;
  upsell?: number;
  avg_coverage?: number;
}

export interface Comparison {
  deltas: Delta;
}

export interface Breakdown {
  label: string;
  rows: Record<string, string | number>[];
}

export interface AnalysisResult {
  snapshot_date: string;
  available_snapshots: string[];
  summary: Summary;
  comparison: Comparison | null;
  risk: Record<string, number>;
  industry: Record<string, string | number>[];
  breakdowns: Breakdown[];
  focus_dimensions: string[];
  report: string;
  download_rows: Record<string, string | number>[];
}

export interface ToolCall {
  tool: string;
  args?: unknown;
  result?: unknown;
  error?: string;
}

export interface QueryResponse {
  source: string; // openai_tool_calling | openai_sql | demo_fallback
  answer: string;
  sql: string;
  columns: string[];
  rows: Record<string, string | number>[];
  summary: string;
  tool_calls: ToolCall[];
  iterations: number;
  halted: boolean;
  snapshot_date: string;
}

export interface WeeklyResponse {
  title: string;
  week_label: string;
  html: string;
  rows: number;
  snapshot_date: string;
}

export interface AnalysisPayload {
  session_id: string;
  mapping: Record<string, string | null>;
  snapshot_date: string;
  industry: string;
  renewal_max: number;
  value_tier: string;
  filters: Record<string, string>;
  focus_dimensions: string[];
}

export interface WeeklyPayload extends AnalysisPayload {
  report_title: string;
  week_label: string;
  analysis_plan: PlanResponse | null;
}
