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
export AETHELNET_AUTH_TOKEN="aethel_dev_token"
export PORT=$PORT
export AETHELNET_NODE_URL="http://127.0.0.1:$PORT/api/lgnn/universal_ingest"
uvicorn aethelnet_node.main:app --host 0.0.0.0 --port $PORT --reload
