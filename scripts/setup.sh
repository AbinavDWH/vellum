#!/bin/bash
# setup.sh — Run this once to set up the project

set -e

echo "🚀 Setting up Vellum with LocalStack..."

# 1. Start infrastructure (if docker is running)
if docker info > /dev/null 2>&1; then
    echo "📦 Starting docker containers..."
    docker compose up -d localstack postgres redis || docker-compose up -d localstack postgres redis || true
else
    echo "⚠️ Docker daemon not reachable. Running in standalone local simulation mode."
fi

# 2. Check LocalStack
echo "⏳ Checking LocalStack..."
if curl -s http://localhost:4566/_localstack/health | grep -q "running"; then
    echo "✅ LocalStack is ready"
else
    echo "ℹ️ LocalStack not running on :4566. Vellum will use local simulation mode for cloud operations."
fi

# 3. Setup Python virtual environment & backend
echo "🐍 Setting up Python backend..."
if [ ! -d ".venv" ]; then
    python3.11 -m venv .venv
fi
.venv/bin/pip install -r backend/requirements.txt

# 4. Check LM Studio
echo "🔍 Checking LM Studio..."
if curl -s http://localhost:1234/v1/models > /dev/null 2>&1; then
    echo "✅ LM Studio is running"
else
    echo "❌ LM Studio not detected. Please start it:"
    echo "   → Open LM Studio → Developer Tab → Start Server"
fi

# 5. Frontend dependencies
if [ -d "frontend" ] && [ -f "frontend/package.json" ]; then
    echo "⚛️ Installing frontend dependencies..."
    cd frontend && npm install && cd ..
fi

echo ""
echo "✅ Setup complete!"
echo "   Backend:    http://localhost:8000"
echo "   Frontend:   http://localhost:3000 (or npm run dev)"
echo "   LocalStack: http://localhost:4566"
echo "   LM Studio:  http://localhost:1234"
