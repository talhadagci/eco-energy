#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "📦 Bağımlılıklar kuruluyor..."
pip install -r requirements.txt -q

echo "🚀 Sunucu başlatılıyor → http://localhost:8000"
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
