# API Contract

Base path: `/api/v1`. Interactive OpenAPI documentation is available at `/docs`.

## `GET /health`

Returns service status and storage mode.

## `POST /uploads`

Uploads one Excel (`.xlsx`, `.xls`) or CSV extract. The response provides `session_id`, inferred column mapping, preview rows, and column names.

## `POST /analysis/customer-pool`

Accepts `session_id`, confirmed mapping, industry, renewal window, and value tier. Returns batch KPIs, risk distribution, industry rollup, SOP, and a prioritized customer-pool export.

## `POST /reports/weekly`

Accepts the same filters plus a report title and week label. Returns a self-contained HTML weekly report with visualizations.

## `POST /agent/sql-queries`

Accepts `session_id` and a natural-language question. With an OpenAI key configured, the Agent creates and executes a read-only DuckDB SQL query against the uploaded, normalized dataset.

## Current no-database boundary

Uploads are stored in process memory, so one deployment instance can serve many active browser users while it is running, but a restart clears sessions and multi-instance deployments do not share uploaded files. Production persistence should replace `SESSIONS` with object storage plus a database or cache, and add authentication and tenant isolation.
