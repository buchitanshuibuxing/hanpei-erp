# 多阶段构建：服务器零编译，镜像内已含前端 dist
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --registry https://registry.npmmirror.com --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ARG PIP_INDEX=https://pypi.org/simple
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SERVE_FRONTEND=1
WORKDIR /app
COPY backend/requirements.txt backend/constraints.txt /app/backend/
RUN pip install --no-cache-dir -i "$PIP_INDEX" -r /app/backend/requirements.txt -c /app/backend/constraints.txt
COPY backend/ /app/backend/
COPY --from=frontend /build/dist /app/frontend/dist
WORKDIR /app/backend
EXPOSE 8008
CMD ["sh", "-c", "python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8008 --workers 1"]
