#!/bin/bash

SERVERS=("ubuntu@YOUR_NODE_IP_2" "ubuntu@YOUR_NODE_IP_1")

for SERVER in "${SERVERS[@]}"; do
    echo "====================================="
    echo "🚀 Syncing and setting up $SERVER"
    echo "====================================="

    # 1. Sync local codebase (without local db/venvs)
    echo "[1/4] Rsyncing codebase..."
    rsync -az --exclude '.venv' --exclude '__pycache__' --exclude 'lgnn.db' --exclude 'scratch' --exclude '*.log' ./ $SERVER:~/aethelnet-node/

    # 2. Remote setup (Clean db, rebuild venv)
    echo "[2/4] Cleaning old garbage & rebuilding environment on $SERVER..."
    ssh $SERVER << 'EOF'
        cd ~/aethelnet-node
        echo "Removing old database and virtual environment..."
        rm -f lgnn.db
        rm -rf .venv
        python3 -m venv .venv
        source .venv/bin/activate
        echo "Installing requirements..."
        pip install -U pip setuptools wheel
        pip install -r requirements.txt
        pip install -e .
EOF

    # 3. Setup systemd user service
    echo "[3/4] Registering systemd user service on $SERVER..."
    ssh $SERVER << 'EOF'
        mkdir -p ~/.config/systemd/user
        cat << 'SVC' > ~/.config/systemd/user/aethelnet-node.service
[Unit]
Description=Aethelnet P2P Node
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/ubuntu/aethelnet-node
ExecStart=/home/ubuntu/aethelnet-node/.venv/bin/uvicorn aethelnet_node.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
SVC
        systemctl --user daemon-reload
        systemctl --user enable aethelnet-node.service
        systemctl --user restart aethelnet-node.service
        sudo loginctl enable-linger ubuntu || true
EOF

    echo "✅ Setup on $SERVER complete!"
    echo ""
done

echo "🎉 All nodes have been cleaned, updated, and started safely via systemd!"
