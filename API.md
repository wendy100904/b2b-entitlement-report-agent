# API Contract

Base path: `/api/v1`. Interactive OpenAPI documentation is available at `/docs`.

## `GET /health`

Returns service status, storage mode (`sqlite` / `database`), database location, persisted session count, and agent mode.

## `GET /sessions`

Lists persisted upload sessions (`session_id`, filename, rows, created_at, snapshot count). Sessions survive service restarts.

## `POST /uploads`

Uploads one Excel (`.xlsx`, `.xls`) or CSV extract. The response provides `session_id`, inferred column mapping, preview rows, and column names. Uploaded data is normalized and persisted to SQLite.

## `POST /analysis/customer-pool`

Accepts `session_id`, confirmed mapping, industry, renewal window, and value tier. Returns batch KPIs, risk distribution, industry rollup, SOP, and a prioritized customer-pool export. The analyzed pool is stored in `analysis_snapshot` for the Agent.

## `POST /reports/weekly`

Accepts the same filters plus a report title and week label. Returns a self-contained HTML weekly report with visualizations.

## `POST /agent/sql-queries`

Accepts `session_id` and a natural-language question. With an OpenAI key configured, the Agent runs in **tool-calling mode** (tools: `describe_dataset`, `run_readonly_sql`, `get_customer_detail`, `get_risk_summary`), iterates up to `MAX_AGENT_ITERATIONS` rounds, and returns:

- `answer`: final natural-language conclusion
- `sql` / `columns` / `rows`: the last read-only query executed (if any)
- `tool_calls`: the tool-call trace
- `source`: `openai_tool_calling` / `openai_sql` / `demo_fallback`

Without a key, the endpoint degrades to rule-based demo queries.

## Storage

Uploads are persisted to SQLite by default (`entitlement.db` in the project root). Set `DATABASE_URL` to switch to PostgreSQL or another SQLAlchemy-supported database. Tables: `uploads`, `upload_raw`, `customer_usage`, `analysis_snapshot`.
