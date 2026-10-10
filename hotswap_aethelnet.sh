#!/bin/bash

# Configuration
# Deploy targets are configured locally, not in the repo, e.g. in .env:
#   AETHELNET_DEPLOY_HOSTS="ubuntu@node-a.example.org ubuntu@node-b.example.org"
if [ -f .env ]; then
    set -a; . ./.env; set +a
fi
if [ -z "$AETHELNET_DEPLOY_HOSTS" ]; then
    echo "❌ Set AETHELNET_DEPLOY_HOSTS (space-separated user@host list), e.g. in .env"
    exit 1
fi
REMOTE_DIR="${AETHELNET_REMOTE_DIR:-~/aethelnet-node}"

echo "[1/3] Preparing Aethelnet Node Updates..."
if [ ! -f "./aethelnet_node/main.py" ]; then
    echo "❌ Local main.py not found!"
    exit 1
fi

echo "[2/3] Uploading fresh Socket & P2P Logic..."
for SERVER in $AETHELNET_DEPLOY_HOSTS; do
    scp ./aethelnet_node/main.py $SERVER:$REMOTE_DIR/aethelnet_node/main.py
    if [ $? -eq 0 ]; then
        echo "✅ Upload to $SERVER successful."
        echo "Restarting service on $SERVER..."
        ssh $SERVER "sudo systemctl restart aethelnet || pm2 restart aethelnet_node"
    else
        echo "❌ Failed to upload to $SERVER"
    fi
done

echo "[3/3] 🚀 Global Swarm Resonance engaged. All configured servers are now syncing their thought-vectors!"
