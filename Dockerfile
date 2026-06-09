FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

# Install system dependencies (required for some math/C-extensions)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ libopenblas-dev && \
    rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
# Ensure we also include our new p2p dependency msgpack
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir msgpack httpx uvicorn

# Copy application code
COPY aethelnet_node/ aethelnet_node/
COPY setup.py .

# Install the node package
RUN pip install -e .

# Expose the port (Cloud Run sets this to 8080 by default)
EXPOSE $PORT

# Run the Uvicorn server
CMD ["sh", "-c", "uvicorn aethelnet_node.main:app --host 0.0.0.0 --port $PORT"]
