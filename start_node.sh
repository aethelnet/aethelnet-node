#!/bin/bash
# Aethelnet Node Bootstrapper

PORT=${1:-8001}
echo "🚀 Booting Aethelburg Ecosystem Node on Port $PORT..."

# 1. Kill any existing processes hanging on the port
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null ; then
    echo "⚠️  Port $PORT is currently blocked. Clearing stray processes..."
    lsof -ti :$PORT | xargs kill -9
    sleep 1
    echo "✅ Port $PORT cleared."
fi

# 2. Start the Uvicorn Server
echo "🌐 Starting Uvicorn Server..."
export PYTHONPATH="../aethelnet-core:$PYTHONPATH"

# Load local secrets (git-ignored) if present, e.g. AETHELNET_AUTH_TOKEN=...
if [ -f .env ]; then
    set -a; . ./.env; set +a
fi

# Generate a throwaway token for this session if none is configured
if [ -z "$AETHELNET_AUTH_TOKEN" ]; then
    AETHELNET_AUTH_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    echo "🔑 No AETHELNET_AUTH_TOKEN set. Generated one for this session (put it in .env to keep it):"
    echo "   $AETHELNET_AUTH_TOKEN"
fi
export AETHELNET_AUTH_TOKEN

# Bind to localhost by default. Use HOST=0.0.0.0 ./start_node.sh to expose the node on the network.
HOST=${HOST:-127.0.0.1}
export PORT=$PORT
export AETHELNET_NODE_URL="http://127.0.0.1:$PORT/api/lgnn/universal_ingest"
uvicorn aethelnet_node.main:app --host "$HOST" --port $PORT --reload
