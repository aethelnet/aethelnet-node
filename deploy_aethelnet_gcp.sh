#!/bin/bash
# 🕸️ AETHELNET SWARM GCP DEPLOYMENT
# Pushes the Aethelnet Node to a GCP Instance.

if [ -z "$1" ]; then
    echo "Usage: ./deploy_aethelnet_gcp.sh <GCP_IP_ADDRESS>"
    echo "Example: ./deploy_aethelnet_gcp.sh 34.123.45.67"
    exit 1
fi

REMOTE_IP="$1"
REMOTE_USER="nhrlyn" # Change this if your GCP user is different
REMOTE_DIR="~/aethelnet-cloud-node"

echo "=================================================="
echo "    🕸️ DEPLOYING AETHELNET NODE TO GCP ($REMOTE_IP)"
echo "=================================================="

# 1. Sync Codebase
echo "[1/3] 📡 Syncing Codebase..."
gcloud compute scp --recurse \
    --zone=europe-west4-a \
    ./* aethelnet-cloud-node:$REMOTE_DIR/

if [ $? -eq 0 ]; then
    echo "✅ Code sync successful."
else
    echo "❌ Code sync failed."
    exit 1
fi

# 2. Create Remote Setup & Launcher
echo "[2/3] 🛠️  Generating Remote Setup & Launcher..."
gcloud compute ssh aethelnet-cloud-node --zone=europe-west4-a --command="cat > $REMOTE_DIR/run_cloud_node.sh << 'EOL'
#!/bin/bash
echo '🕸️ Booting Aethelnet Cloud Node...'

# Ensure Python and pip are installed
sudo apt-get update && sudo apt-get install -y python3-pip python3-venv

# Setup Virtual Environment if not exists
if [ ! -d \".venv\" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

# Install requirements
pip install -r requirements.txt
pip install websockets uvicorn fastapi

# Start the node in the background using port 8000
echo '🚀 Starting Uvicorn on Port 8000...'
export PORT=8000
nohup uvicorn aethelnet_node.main:app --host 0.0.0.0 --port 8000 > node.log 2>&1 &
echo '✅ Node is running in the background! Check node.log for output.'
EOL"
gcloud compute ssh aethelnet-cloud-node --zone=europe-west4-a --command="chmod +x $REMOTE_DIR/run_cloud_node.sh"

echo "✅ Remote launcher created: ~/aethelnet-cloud-node/run_cloud_node.sh"

echo "=================================================="
echo "    🏁 DEPLOYMENT PACK SENT!"
echo "=================================================="
echo "Next Steps:"
echo "1. SSH into your GCP server:"
echo "   ssh $REMOTE_USER@$REMOTE_IP"
echo ""
echo "2. Boot the Cloud Node:"
echo "   cd aethelnet-cloud-node"
echo "   ./run_cloud_node.sh"
echo ""
echo "3. Watch the logs:"
echo "   tail -f node.log"
echo "=================================================="
