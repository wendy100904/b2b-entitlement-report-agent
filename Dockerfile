# ---------- Stage 1: 构建 React 前端 ----------
FROM node:22-alpine AS frontend-builder
WORKDIR /build
COPY frontend-react/package.json frontend-react/package-lock.json* ./
RUN npm install
COPY frontend-react/ ./
RUN npm run build

# ---------- Stage 2: Python 后端 ----------
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
# 从 Stage 1 拷贝 React 构建产物
COPY --from=frontend-builder /build/dist ./frontend-react/dist
COPY sample_data.csv sample_data_multiweek.csv ./

ENV PYTHONUNBUFFERED=1
ENV MAX_UPLOAD_MB=30
# 数据库文件持久化目录（挂载 volume 后重启不丢）
ENV DATABASE_URL=sqlite:////app/data/entitlement.db
RUN mkdir -p /app/data
VOLUME ["/app/data"]
EXPOSE 8000

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
