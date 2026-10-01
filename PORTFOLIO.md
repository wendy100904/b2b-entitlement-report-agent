# 企业权益周报分析 Agent（B2B Entitlement Report Agent）

> 一份可直接复制到简历 / Notion / 个人网站的作品集文档。
> 〔〕中的内容是需要你自己替换的占位符。

---

## 一句话简介

一个面向 B2B 客户成功团队的全栈数据分析工具——上传客户权益使用的 Excel/CSV，自动完成字段识别、续约风险分层诊断，并支持用自然语言查数据、一键导出图表化周报。

- **我的角色**：全栈独立开发（前端 + 后端 + 数据分析 + AI 集成）
- **技术栈**：Python · FastAPI · Pandas · DuckDB · Plotly · OpenAI Tool Calling · SQLAlchemy + SQLite · React 18 + TypeScript
- **项目类型**：个人 / 学习项目
- **在线体验**：〔发布后的稳定链接〕
- **项目截图**：〔放 2–3 张：上传界面 / 诊断报告 KPI / 图表化周报〕

---

## 项目背景与解决的问题

B2B 客户成功团队每周需要人工翻阅大量客户权益使用数据，判断哪些客户可能流失、哪些有增购机会。这个过程效率低、容易漏判临期高风险客户，且分析口径不统一。

本项目把「上传数据 → 字段映射 → 批量风险诊断 → 生成可交付周报 → 自然语言查询」五个环节串成一条自动化链路，实现「上传即出报告」，并让非技术的业务同事也能用大白话直接查数据。

---

## 我做了什么（核心工作）

- **数据处理与风险模型**：用 Pandas 完成 Excel/CSV 的字段模糊匹配、缺失值处理、客户级聚合与多周快照管理；构建续约风险分层模型（高危流失 / 中危预警 / 续费增购等），结合权益覆盖率、到期天数、使用趋势多维打分，并按行业、企业规模、活跃类型自动分群输出运营 SOP。
- **Tool Calling 查询 Agent**：基于 OpenAI Function Calling 实现多轮工具调用循环——Agent 自主决定调用「数据集概况 / 只读 SQL / 客户详情 / 风险总览」四个工具，SQL 报错时可自我修正重试，最终以自然语言输出结论；无密钥时自动降级为规则查询，保证核心流程不中断。
- **数据库持久化**：用 SQLAlchemy + SQLite 替代进程内存存储（`uploads` / `upload_raw` / `customer_usage` / `analysis_snapshot` 四张表），上传会话重启不丢、可跨实例复用；`DATABASE_URL` 一行切换 PostgreSQL。
- **可视化周报**：用 Plotly 生成图表化的可交付 HTML 周报，并实现浏览器端一键导出 PDF（A4 分页、图表防截断、颜色保真，无需额外后端依赖）。
- **接口与部署**：用 FastAPI 设计 12+ 版本化 REST 接口（`/api/v1`）并保留旧版兼容；通过 `StaticFiles` 同源托管前后端。

---

## 技术难点与解决方案（面试重点）

- **前后端端口错位导致接口调用失败**：预览环境将静态页面代理在一个端口、API 在另一个端口，前端 `location.origin` 指向错误。通过让 FastAPI 用 `StaticFiles` 同源托管前端、统一端口，彻底消除跨端口问题。
- **单次 NL2SQL 无法应对复杂问题**：早期版本一次提示词生成 SQL，模型看不到数据概况、SQL 报错即失败。重构为 Function Calling 多轮工具调用：先 `describe_dataset` 了解 schema，再按需执行只读 SQL / 查客户详情 / 取风险总览，工具返回 error 时携带错误信息回传模型修正重试，最终输出自然语言结论，并保留「工具调用 → 传统 NL2SQL → 规则查询」三级降级。
- **数据持久化边界**：早期上传数据存进程内存、重启即失效。用 SQLAlchemy + SQLite 建立四表存储（元数据 / 原始行 / 规范化快照 / 分析快照），重启后会话仍可继续查询；`DATABASE_URL` 可切换 PostgreSQL，为多实例部署预留了路径。

---

## 技术栈说明（各自职责）

| 技术 | 职责 |
|---|---|
| FastAPI | Web 框架 / REST 接口层，同源托管前端 |
| Pandas | 数据清洗、聚合、风险指标计算（分析核心） |
| DuckDB | 内嵌式只读 SQL 引擎，执行 Agent 生成的查询 |
| OpenAI API | Tool Calling 多轮工具调用 / 自然语言转 SQL / 生成分析方案 |
| SQLAlchemy + SQLite | 数据持久化（可切换 PostgreSQL），上传会话跨重启保留 |
| Plotly | 图表可视化，生成周报图表 |
| Uvicorn | ASGI 服务器，启动并对外提供服务 |
| openpyxl / python-multipart | Excel 解析 / 文件上传接收 |
| React 18 + TypeScript | 前端（Vite 构建），组件化实现上传/映射/分析/周报/NL2SQL |

---

## 简历条目版本（可直接粘贴）

**企业权益周报分析 Agent｜全栈独立开发** — Python · FastAPI · Pandas · DuckDB · Plotly · OpenAI Tool Calling · SQLAlchemy/SQLite

- 独立开发面向 B2B 客户成功团队的权益分析工具，覆盖「上传 → 字段映射 → 风险诊断 → 图表周报 → 自然语言问答」完整链路。
- 构建续约风险分层模型，结合覆盖率、到期天数、使用趋势多维打分并自动分群输出运营 SOP。
- 基于 OpenAI Function Calling 实现多轮工具调用 Agent（数据集概况 / 只读 SQL / 客户详情 / 风险总览四个工具），SQL 出错可自我修正重试，输出自然语言结论，无密钥时三级降级不中断。
- 用 SQLAlchemy + SQLite 实现数据持久化，上传会话跨重启保留，`DATABASE_URL` 可切换 PostgreSQL；用 Plotly 生成图表化周报并支持一键导出 PDF。
- 设计 12+ 版本化 REST 接口与前后端同源部署；前端使用 React 18 + TypeScript（Vite 构建）组件化实现。

---

## 英文版（供国际岗位使用）

**B2B Entitlement Analytics Agent — Full-Stack Developer**
Python · FastAPI · Pandas · DuckDB · Plotly · OpenAI Tool Calling · SQLAlchemy/SQLite

- Built an end-to-end analytics tool for B2B customer-success teams: Excel/CSV upload with fuzzy column mapping, customer-level aggregation, and multi-week snapshots.
- Designed a renewal-risk scoring model (churn / at-risk / upsell) segmented by industry, company size, and activity, with auto-generated action SOPs.
- Implemented a tool-calling agent with OpenAI Function Calling (dataset overview / read-only SQL / customer detail / risk summary), iterating autonomously and self-correcting SQL errors, with a three-level fallback when no API key is configured.
- Persisted uploads with SQLAlchemy + SQLite (swappable to PostgreSQL via DATABASE_URL) so sessions survive restarts; generated chart-rich reports with Plotly and added client-side one-click PDF export (A4 pagination, chart-aware page breaks).

---

## 呈现建议

1. 一定要放**可点开的在线链接**，让面试官直接体验。
2. 配 **2–3 张截图**或一段 **30 秒录屏**，视觉最直观。
3. 诚实标注**个人 / 学习项目**，不要包装成「服务了 XX 客户」，避免被追问穿帮。
4. 如果有真实运行数据（处理行数、字段识别准确率、周报生成耗时），补一个数字会更有说服力。
