# 企业权益周报分析 Agent（B2B Entitlement Report Agent）

> 一份可直接复制到简历 / Notion / 个人网站的作品集文档。
> 〔〕中的内容是需要你自己替换的占位符。

---

## 一句话简介

一个面向 B2B 客户成功团队的全栈数据分析工具——上传客户权益使用的 Excel/CSV，自动完成字段识别、续约风险分层诊断，并支持用自然语言查数据、一键导出图表化周报。

- **我的角色**：全栈独立开发（前端 + 后端 + 数据分析 + AI 集成）
- **技术栈**：Python · FastAPI · Pandas · DuckDB · Plotly · OpenAI API · 原生 HTML/JS
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
- **自然语言查询 Agent**：接入 OpenAI 将业务问题转成只读 DuckDB SQL 并在上传数据上执行；未配置密钥时自动降级为规则化查询，兼顾能力与稳定。
- **可视化周报**：用 Plotly 生成图表化的可交付 HTML 周报，并实现浏览器端一键导出 PDF（A4 分页、图表防截断、颜色保真，无需额外后端依赖）。
- **接口与部署**：用 FastAPI 设计 12+ 版本化 REST 接口（`/api/v1`）并保留旧版兼容；通过 `StaticFiles` 同源托管前后端。

---

## 技术难点与解决方案（面试重点）

- **前后端端口错位导致接口调用失败**：预览环境将静态页面代理在一个端口、API 在另一个端口，前端 `location.origin` 指向错误。通过让 FastAPI 用 `StaticFiles` 同源托管前端、统一端口，彻底消除跨端口问题。
- **AI 能力的可用性兜底**：自然语言转 SQL 依赖外部 API，缺密钥或调用失败会中断体验。设计规则化降级方案，无 Key 时仍能提供有限查询，保证核心流程不中断。
- **数据持久化边界**：当前上传数据存进程内存、重启即失效。在文档中明确标注这是 demo 边界，并规划了「对象存储 + 数据库 + 任务队列」的生产演进路径。

---

## 技术栈说明（各自职责）

| 技术 | 职责 |
|---|---|
| FastAPI | Web 框架 / REST 接口层，同源托管前端 |
| Pandas | 数据清洗、聚合、风险指标计算（分析核心） |
| DuckDB | 内嵌式只读 SQL 引擎，在内存数据上执行查询 |
| OpenAI API | 自然语言转 SQL / 生成分析方案 |
| Plotly | 图表可视化，生成周报图表 |
| Uvicorn | ASGI 服务器，启动并对外提供服务 |
| openpyxl / python-multipart | Excel 解析 / 文件上传接收 |
| 原生 HTML/CSS/JS | 前端界面与交互，含导出 PDF |

---

## 简历条目版本（可直接粘贴）

**企业权益周报分析 Agent｜全栈独立开发** — Python · FastAPI · Pandas · DuckDB · Plotly · OpenAI

- 独立开发面向 B2B 客户成功团队的权益分析工具，覆盖「上传 → 字段映射 → 风险诊断 → 图表周报 → SQL 问答」完整链路。
- 构建续约风险分层模型，结合覆盖率、到期天数、使用趋势多维打分并自动分群输出运营 SOP。
- 接入 OpenAI 实现自然语言转只读 DuckDB SQL 查询，无密钥时降级规则查询；用 Plotly 生成图表化周报并支持一键导出 PDF。
- 设计 12+ 版本化 REST 接口与前后端同源部署。

---

## 英文版（供国际岗位使用）

**B2B Entitlement Analytics Agent — Full-Stack Developer**
Python · FastAPI · Pandas · DuckDB · Plotly · OpenAI API

- Built an end-to-end analytics tool for B2B customer-success teams: Excel/CSV upload with fuzzy column mapping, customer-level aggregation, and multi-week snapshots.
- Designed a renewal-risk scoring model (churn / at-risk / upsell) segmented by industry, company size, and activity, with auto-generated action SOPs.
- Implemented a natural-language SQL agent using OpenAI to produce read-only DuckDB queries, with a rule-based fallback when no API key is configured.
- Generated chart-rich reports with Plotly and added client-side one-click PDF export (A4 pagination, chart-aware page breaks).

---

## 呈现建议

1. 一定要放**可点开的在线链接**，让面试官直接体验。
2. 配 **2–3 张截图**或一段 **30 秒录屏**，视觉最直观。
3. 诚实标注**个人 / 学习项目**，不要包装成「服务了 XX 客户」，避免被追问穿帮。
4. 如果有真实运行数据（处理行数、字段识别准确率、周报生成耗时），补一个数字会更有说服力。
