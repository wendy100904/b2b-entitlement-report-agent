# Excel-to-Report B2B Entitlement Agent

Full-stack deployable version with a **tool-calling SQL Agent** and **SQLite persistence**:

1. The frontend uploads a prepared Excel or CSV extract.
2. The FastAPI backend reads it with Pandas and lets the user confirm field mapping.
3. The backend calculates batch-level entitlement health, renewal risk, and SOP output.
4. Uploaded data is **persisted to SQLite** (swappable to PostgreSQL via `DATABASE_URL`), so sessions survive restarts.
5. With `OPENAI_API_KEY` configured, the SQL Agent runs in **tool-calling mode**: it autonomously decides which tools to call (`describe_dataset` / `run_readonly_sql` / `get_customer_detail` / `get_risk_summary`), iterates until it can answer, and returns a natural-language conclusion. Without a key it degrades to rule-based demo queries.

## Documentation & Prototype

- **Product Requirements Document (PRD)**: [PRD.pdf](docs/PRD.pdf) — background, goals/non-goals, requirement cards F1–F5, fallback & degradation, data model, and boundaries (v1.0 · 2026-08-01).
- **Hi-fi Prototype (Figma-style canvas)**: [overview](docs/prototype/overview.png) — 5 screens covering the full loop: upload → field mapping → customer-pool diagnosis → weekly report → SQL Agent.
  - [01 · Upload](docs/prototype/01-upload.png) · [02 · Field mapping](docs/prototype/02-mapping.png) · [03 · Analysis](docs/prototype/03-analysis.png) · [04 · Weekly report](docs/prototype/04-weekly-report.png) · [05 · SQL Agent](docs/prototype/05-sql-agent.png)
- **Live Demo**: https://b2b-entitlement-report-agent.onrender.com

## Tech Stack

- **Backend**: Python · FastAPI · Uvicorn · Pydantic · SQLAlchemy (SQLite; swappable to PostgreSQL via `DATABASE_URL`) · Pandas · NumPy · DuckDB · Plotly · OpenAI API
- **Frontend**: React 18 + TypeScript + Vite (served by FastAPI; native HTML/JS fallback retained)
- **Engineering**: GitHub Actions CI (pytest) · Docker / docker-compose · Render auto-deploy

## 快速开始（跨平台，推荐）

```bash
# 1. 安装依赖（建议先建虚拟环境）
pip install -r requirements.txt

# 2. （可选）配置 OpenAI 密钥以启用 Tool Calling Agent；不配也能用规则降级
export OPENAI_API_KEY="你的密钥"      # Windows PowerShell: $env:OPENAI_API_KEY="你的密钥"

# 3. 启动服务
python -m uvicorn backend.main:app --reload --port 8000
```

打开 `http://127.0.0.1:8000`，用仓库自带的 `sample_data_multiweek.csv` 上传即可体验完整流程（字段自动识别 → 风险诊断 → 图表周报 → Tool Calling 问答）。API 文档见 `http://127.0.0.1:8000/docs`。

## Run

```powershell
cd <project-folder>
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:OPENAI_API_KEY = "your key"
..\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000`. API documentation is available at `http://127.0.0.1:8000/docs`.

## Deploy for shared use

```powershell
docker compose up --build
```

The frontend is served by FastAPI and calls versioned REST endpoints under `/api/v1`, so it can be placed behind a company domain or reverse proxy without changing the browser workflow. `docker-compose.yml` mounts a volume for the SQLite file, so uploaded sessions persist across container restarts.

For a same-network demo, run `./run_lan.ps1` and share the printed LAN address. For a public demo URL, use the included `render.yaml` and follow `DEPLOY.md`.

## Data & database

- Uploads are stored in a **SQLite database** (`entitlement.db` at the project root by default), not in process memory.
- Tables: `uploads` (session metadata), `upload_raw` (original rows), `customer_usage` (normalized customer-week snapshots), `analysis_snapshot` (last analyzed pool used by the Agent).
- Set `DATABASE_URL` to switch to PostgreSQL or another SQLAlchemy-supported database.
- `GET /api/v1/sessions` lists persisted sessions; an existing `session_id` keeps working after a restart.

## Agent (tool-calling mode)

The Agent exposes four tools and loops autonomously (default max 6 iterations, override with `MAX_AGENT_ITERATIONS`):

| Tool | Purpose |
|---|---|
| `describe_dataset` | Dataset overview: schema, snapshot dates, dimension values |
| `run_readonly_sql` | Read-only SELECT/WITH query (DuckDB) on the current pool |
| `get_customer_detail` | Full entitlement snapshot of one customer |
| `get_risk_summary` | Risk distribution, expiring counts, top-risk customers |

The final response always includes a natural-language `answer` plus the tool-call trace. If the LLM API is unavailable, the endpoint falls back to rule-based demo SQL so the flow never breaks.

## Suggested Excel fields

Use the column mapping screen rather than forcing a fixed export format. The strongest report needs:

- customer code/name and data date (one customer snapshot per reporting week)
- industry, company size, ownership, city tier, renewal type, and active type
- purchased products and used products (comma-separated is fine)
- total uses, product-type count, usage period, max consecutive active days
- days to renewal and annual contract value

Optional weekly usage columns can be added in a later iteration for full trend analysis.

When a file includes `数据日期`, `统计日期`, or `快照日期`, the app preserves each customer-week snapshot. The analysis-period selector defaults to the latest snapshot and lets users reopen any uploaded historical week.
