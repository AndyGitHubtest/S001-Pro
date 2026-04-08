#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
# 生产模式：后台运行 + 日志文件
nohup uvicorn app.main:app --host 0.0.0.0 --port ${BACKEND_PORT:-8000} --workers 2 > ../logs/backend.log 2>&1 &
echo $! > ../logs/backend.pid
echo "Backend started on port ${BACKEND_PORT:-8000}"
