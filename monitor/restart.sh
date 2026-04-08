#!/bin/bash
cd "$(dirname "$0")"
./stop_all.sh
echo ""
sleep 2
./start_all.sh
