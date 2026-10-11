#!/bin/bash
# Deploys the node to every server in AETHELNET_DEPLOY_HOSTS and restarts it.
#
# The whole aethelnet_node package is shipped, not just main.py: main.py imports
# security.py, routers/, ... so a partial copy crashes the service on restart.
# Runtime state that lives on the server (ledger, databases) is never overwritten.
#
# Configuration (environment or .env):
#   AETHELNET_DEPLOY_HOSTS="ubuntu@node-a.example.org ubuntu@node-b.example.org"   (required)
#   AETHELNET_REMOTE_DIR=~/aethelnet-node          node checkout on the server
#   AETHELNET_REMOTE_PORT=8001                     port the service listens on (health check)
#   AETHELNET_REMOTE_PIP=/opt/aethelnet-node/.venv/bin/pip    if set, installs requirements.txt
#   AETHELNET_REMOTE_CORE_DIR=~/aethelnet-core     if set, also ships ../aethelnet-core/aethelnet

if [ -f .env ]; then
    set -a; . ./.env; set +a
fi
if [ -z "$AETHELNET_DEPLOY_HOSTS" ]; then
    echo "❌ Set AETHELNET_DEPLOY_HOSTS (space-separated user@host list), e.g. in .env"
    exit 1
fi
REMOTE_DIR="${AETHELNET_REMOTE_DIR:-~/aethelnet-node}"
REMOTE_PORT="${AETHELNET_REMOTE_PORT:-8001}"
TAR_EXCLUDES=(--exclude=__pycache__ --exclude='*.pyc' --exclude=ledger.json --exclude='*.db' --exclude='.visited_*.json')

echo "[1/4] Checking the local package..."
if [ ! -f "./aethelnet_node/main.py" ]; then
    echo "❌ Run this from the aethelnet-node repository root."
    exit 1
fi
if ! python3 -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8'), str(p)) for p in pathlib.Path('aethelnet_node').rglob('*.py')]"; then
    echo "❌ Syntax error in aethelnet_node, nothing was deployed."
    exit 1
fi

FAILED=0
for SERVER in $AETHELNET_DEPLOY_HOSTS; do
    echo "[2/4] Uploading aethelnet_node/ and requirements.txt to $SERVER:$REMOTE_DIR ..."
    if ! tar czf - "${TAR_EXCLUDES[@]}" aethelnet_node requirements.txt | \
            ssh "$SERVER" "mkdir -p $REMOTE_DIR && tar xzf - -C $REMOTE_DIR"; then
        echo "❌ Upload to $SERVER failed, skipping restart."
        FAILED=1
        continue
    fi
    if [ -n "$AETHELNET_REMOTE_CORE_DIR" ] && [ -d ../aethelnet-core/aethelnet ]; then
        echo "      ...and aethelnet-core to $SERVER:$AETHELNET_REMOTE_CORE_DIR"
        tar czf - "${TAR_EXCLUDES[@]}" -C ../aethelnet-core aethelnet | \
            ssh "$SERVER" "mkdir -p $AETHELNET_REMOTE_CORE_DIR && tar xzf - -C $AETHELNET_REMOTE_CORE_DIR" || FAILED=1
    fi
    if [ -n "$AETHELNET_REMOTE_PIP" ]; then
        ssh "$SERVER" "$AETHELNET_REMOTE_PIP install -q -r $REMOTE_DIR/requirements.txt" || FAILED=1
    fi

    echo "[3/4] Restarting the service on $SERVER..."
    ssh "$SERVER" "sudo systemctl restart aethelnet || pm2 restart aethelnet_node"

    echo "[4/4] Health check on $SERVER (port $REMOTE_PORT)..."
    if ssh "$SERVER" "for i in 1 2 3 4 5 6 7 8 9 10; do curl -fsS http://127.0.0.1:$REMOTE_PORT/ >/dev/null && exit 0; sleep 3; done; exit 1"; then
        echo "✅ $SERVER is up."
    else
        echo "❌ $SERVER did not come back. Logs: ssh $SERVER 'journalctl -u aethelnet -n 50'"
        FAILED=1
    fi
done

if [ "$FAILED" -ne 0 ]; then
    echo "⚠️  Deployment finished with errors."
    exit 1
fi
echo "🚀 Global Swarm Resonance engaged. All configured servers are running the new code."
echo "   Reminder: nodes reachable from the internet need AETHELNET_AUTH_TOKEN in their .env."
