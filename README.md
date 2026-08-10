# Excel-to-Report B2B Entitlement Agent

This is the deployable full-stack version of the project:

1. The frontend uploads a prepared Excel or CSV extract.
2. The FastAPI backend reads it with Pandas and lets the user confirm field mapping.
3. The backend calculates batch-level entitlement health, renewal risk, and SOP output.
4. The SQL Agent uses the uploaded, normalized table as its actual data source. With `OPENAI_API_KEY` configured, it generates read-only DuckDB SQL from natural-language questions; without a key it only exposes limited demo fallback queries.

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
