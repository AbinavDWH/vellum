#!/bin/bash
# setup.sh — Run this once to set up the project

set -e

echo "🚀 Setting up Vellum..."

# 1. Start auxiliary infrastructure (if docker is running)
if docker info > /dev/null 2>&1; then
    echo "📦 Starting docker containers..."
    docker compose up -d postgres redis || docker-compose up -d postgres redis || true
fi

# 2. Setup Python virtual environment & backend
echo "🐍 Setting up Python backend..."
if [ ! -d ".venv" ]; then
    python3.11 -m venv .venv
fi
.venv/bin/pip install -r backend/requirements.txt

# 3. Check LM Studio
echo "🔍 Checking LM Studio..."
if curl -s http://localhost:1234/v1/models > /dev/null 2>&1; then
    echo "✅ LM Studio is running"
else
    echo "❌ LM Studio not detected. Please start it:"
    echo "   → Open LM Studio → Developer Tab → Start Server"
fi

# 4. Frontend dependencies
if [ -d "frontend" ] && [ -f "frontend/package.json" ]; then
    echo "⚛️ Installing frontend dependencies..."
    cd frontend && npm install && cd ..
fi

echo ""
echo "✅ Setup complete!"
echo "   Backend:    http://localhost:8000"
echo "   Frontend:   http://localhost:3000 (or npm run dev)"
echo "   LM Studio:  http://localhost:1234"
