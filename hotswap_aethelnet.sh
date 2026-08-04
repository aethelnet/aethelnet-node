#!/bin/bash

# Configuration
SERVER_92="ubuntu@92.5.45.124"
SERVER_141="ubuntu@YOUR_NODE_IP_1"
REMOTE_DIR="~/aethelnet-node"

echo "[1/4] Preparing Aethelnet Node Updates..."
if [ ! -f "./aethelnet_node/main.py" ]; then
    echo "❌ Local main.py not found!"
    exit 1
fi

echo "[2/4] Uploading fresh Socket & P2P Logic to .92 Server..."
scp ./aethelnet_node/main.py $SERVER_92:$REMOTE_DIR/aethelnet_node/main.py
if [ $? -eq 0 ]; then
    echo "✅ Upload to .92 successful."
    echo "Restarting service on .92..."
    ssh $SERVER_92 "sudo systemctl restart aethelnet || pm2 restart aethelnet_node"
else
    echo "❌ Failed to upload to .92"
fi

echo "[3/4] Uploading fresh Socket & P2P Logic to .141 Server..."
scp ./aethelnet_node/main.py $SERVER_141:$REMOTE_DIR/aethelnet_node/main.py
if [ $? -eq 0 ]; then
    echo "✅ Upload to .141 successful."
    echo "Restarting service on .141..."
    ssh $SERVER_141 "sudo systemctl restart aethelnet || pm2 restart aethelnet_node"
else
    echo "❌ Failed to upload to .141"
fi

echo "[4/4] 🚀 Global Swarm Resonance engaged. Servers .92 and .141 are now syncing their thought-vectors to GCP!"
