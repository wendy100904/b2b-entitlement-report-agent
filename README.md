# Excel-to-Report B2B Entitlement Agent

This is the deployable full-stack version of the project:

1. The frontend uploads a prepared Excel or CSV extract.
2. The FastAPI backend reads it with Pandas and lets the user confirm field mapping.
3. The backend calculates batch-level entitlement health, renewal risk, and SOP output.
4. The SQL Agent uses the uploaded, normalized table as its actual data source. With `OPENAI_API_KEY` configured, it generates read-only DuckDB SQL from natural-language questions; without a key it only exposes limited demo fallback queries.

## 快速开始（跨平台，推荐）

```bash
# 1. 安装依赖（建议先建虚拟环境）
pip install -r requirements.txt

# 2. （可选）配置 OpenAI 密钥以启用自然语言查询；不配也能用规则降级
export OPENAI_API_KEY="你的密钥"      # Windows PowerShell: $env:OPENAI_API_KEY="你的密钥"

# 3. 启动服务
python -m uvicorn backend.main:app --reload --port 8000
```

打开 `http://127.0.0.1:8000`，用仓库自带的 `sample_data.csv` 上传即可体验完整流程（字段自动识别 → 风险诊断 → 图表周报 → SQL 问答）。API 文档见 `http://127.0.0.1:8000/docs`。

## Run

```powershell
cd <project-folder>\fullstack_agent
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:OPENAI_API_KEY = "your key"
..\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000`. API documentation is available at `http://127.0.0.1:8000/docs`.

## Deploy for shared use

```powershell
docker compose up --build
```

The frontend is served by FastAPI and calls versioned REST endpoints under `/api/v1`, so it can be placed behind a company domain or reverse proxy without changing the browser workflow.

For a same-network demo, run `./run_lan.ps1` and share the printed LAN address. For a public demo URL, use the included `render.yaml` and follow `DEPLOY.md`.

## No-database boundary

This version deliberately excludes a database. Uploaded files are held in process memory, so they are available to concurrent users of one service instance but are cleared after restart. Before production rollout, add SSO/API authentication, tenant isolation, object storage, a metadata database, and an async task queue for large reports.

## Suggested Excel fields

Use the column mapping screen rather than forcing a fixed export format. The strongest report needs:

- customer code/name and data date (one customer snapshot per reporting week)
- industry, company size, ownership, city tier, renewal type, and active type
- purchased products and used products (comma-separated is fine)
- total uses, product-type count, usage period, max consecutive active days
- days to renewal and annual contract value

Optional weekly usage columns can be added in a later iteration for full trend analysis.

When a file includes `数据日期`, `统计日期`, or `快照日期`, the app preserves each customer-week snapshot. The analysis-period selector defaults to the latest snapshot and lets users reopen any uploaded historical week.
