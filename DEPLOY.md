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

## Option 2: Public demo URL with Render

1. Push the `fullstack_agent` folder to a private Git repository.
2. In Render, create a Blueprint from that repository. The included `render.yaml` creates a Docker web service and uses `/api/v1/health` as its health check.
3. Add `OPENAI_API_KEY` in the Render dashboard only when SQL and planning need an LLM. Do not commit this key to Git.
4. After deployment, share the generated HTTPS URL or bind a custom domain.

## Production boundary

The current prototype has no login, tenant isolation, database, or durable file storage. Do not upload real company/customer data to a public URL until it is deployed inside a company network or extended with SSO, authorization, object storage, a database/cache, and audit logging.
