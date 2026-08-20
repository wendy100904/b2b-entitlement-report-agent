# Shared Access and Deployment

`127.0.0.1` is only reachable from the computer that starts the service. Use one of the options below for shared access.

## Option 1: Same office network

Run this command on the host computer:

```powershell
cd <project-folder>\fullstack_agent
.\run_lan.ps1
```

The script prints an address such as `http://192.168.1.20:8000`. Colleagues on the same network can open that address after Windows Firewall allows inbound TCP port 8000.

This is suitable only for demos or a trusted internal network. The upload session is kept in memory and is cleared when the service restarts.

## Option 2: Public demo URL with Render （推荐）

本项目根目录已含 `Dockerfile` 与 `render.yaml`，可直接在 Render 用 Blueprint 一键部署：

1. 把**整个项目根目录**推到一个 Git 仓库（GitHub/GitLab 均可）。
2. 登录 [Render](https://render.com) → New → **Blueprint** → 选择该仓库。Render 会读取根目录的 `render.yaml`，自动创建一个 Docker Web Service，健康检查用 `/api/v1/health`。
3. （可选）在 Render 面板的 Environment 里填 `OPENAI_API_KEY`（`render.yaml` 已设为 `sync:false`，不会进代码库）。不填也能部署，NL2SQL 会降级为规则查询。
4. 等构建完成，Render 会给出一个 `https://xxx.onrender.com` 的公开地址——页面和 `/api` 同源，上传/分析/周报/PDF/样例下载全部可用。

> 端口说明：Render 会注入 `PORT` 环境变量，`Dockerfile` 里的 `uvicorn ... --port ${PORT:-8000}` 会自动使用它，无需手动改端口。

### 快速自查（部署后）
- 打开 `https://xxx.onrender.com/api/v1/health` 应返回 `{"status":"ok",...}`
- 打开首页 → 点「⬇ 下载样例数据」应能下载 `sample_data_multiweek.csv`
- 用样例上传 → 生成报告/周报 → 导出 PDF，确认全链路正常

## Production boundary

The current prototype has no login, tenant isolation, database, or durable file storage. Do not upload real company/customer data to a public URL until it is deployed inside a company network or extended with SSO, authorization, object storage, a database/cache, and audit logging.
