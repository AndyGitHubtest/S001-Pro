#!/bin/bash
cd "/Users/andy/S001-Pro/monitor/frontend"
# 使用 npx serve 提供静态文件
npx serve -s dist -l 3000 > ../logs/frontend.log 2>&1 &
echo $! > ../logs/frontend.pid
echo "Frontend started on port 3000"
