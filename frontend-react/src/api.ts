// API 层：所有后端请求都收敛在这里，组件不直接碰 fetch
import type {
  AnalysisPayload,
  AnalysisResult,
  PlanResponse,
  QueryResponse,
  UploadResponse,
  WeeklyPayload,
  WeeklyResponse,
} from "./types";

const API_BASE =
  location.protocol === "file:" ? "http://127.0.0.1:8000" : location.origin;
const API = `${API_BASE}/api/v1`;

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new Error(
      `无法连接 API（${API_BASE}）。请在项目目录运行 uvicorn 后访问 http://127.0.0.1:8000。`
    );
  }
  let json: unknown;
  try {
    json = await response.json();
  } catch {
    throw new Error(`接口返回异常（HTTP ${response.status}）`);
  }
  if (!response.ok) {
    const detail =
      typeof json === "object" && json !== null && "detail" in json
        ? String((json as { detail: unknown }).detail)
        : "请求失败";
    throw new Error(detail);
  }
  return json as T;
}

export async function uploadFile(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  return request<UploadResponse>(`${API}/uploads`, { method: "POST", body: form });
}

export async function buildAnalysisPlan(
  sessionId: string,
  mapping: Record<string, string | null>,
  goal: string
): Promise<PlanResponse> {
  return request<PlanResponse>(`${API}/agent/analysis-plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, mapping, goal }),
  });
}

export async function runAnalysis(payload: AnalysisPayload): Promise<AnalysisResult> {
  return request<AnalysisResult>(`${API}/analysis/customer-pool`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function makeWeeklyReport(payload: WeeklyPayload): Promise<WeeklyResponse> {
  return request<WeeklyResponse>(`${API}/reports/weekly`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function askQuestion(
  sessionId: string,
  question: string
): Promise<QueryResponse> {
  return request<QueryResponse>(`${API}/agent/sql-queries`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, question }),
  });
}

export const SAMPLE_DATA_URL = `${API}/sample-data`;
