#!/bin/bash
# S001-Pro Deployment Script (Force Sync)
set -e

cd ~/strategies/S001-Pro

echo "🚀 [1/4] Fetching latest code from GitHub..."
git fetch origin

echo "🧹 [2/4] Hard resetting to GitHub state..."
git reset --hard origin/main

echo "🗑️ [3/4] Cleaning junk files (Keeping venv)..."
git clean -fdx -e venv

echo "📦 [4/4] Verifying Dependencies..."
source venv/bin/activate
pip install -q -r requirements.txt

echo "✅ Deployment Complete."
