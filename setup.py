from setuptools import setup, find_packages

setup(
    name="aethelnet-node",
    version="1.0.0",
    description="Aethelnet Node: Production Evidentiary Ledger, Multigraph Reconciliation & Forensic REST Daemon",
    author="Auratic Systems Prime",
    license="AGPL-3.0",
    url="https://aethelburg.network",
    packages=find_packages(exclude=["tests", "tests.*", "research_scout"]),
    # Keep in sync with requirements.txt
    install_requires=[
        "fastapi>=0.90.0",
        "uvicorn>=0.20.0",
        "httpx>=0.23.0",
        "pydantic>=1.10.0",
        "python-multipart>=0.0.6",
        "requests>=2.28.0",
        "msgpack>=1.0.0",
        "python-dotenv>=1.0.0",
        "torch>=2.0.0",
        "torchdiffeq>=0.2.3",
        "networkx>=3.0",
        "numpy>=1.22.0",
        "scipy>=1.8.0",
        "pyyaml>=6.0",
        "beautifulsoup4>=4.11.0",
        "sentence-transformers>=2.0.0",
        "web3>=6.0.0",
        # aethelnet-core is not on PyPI yet, so install it straight from GitHub
        "aethelnet-core @ git+https://github.com/aethelnet/aethelnet-core.git",
    ],
    extras_require={
        "postgres": ["psycopg2-binary>=2.9"],
        "dev": ["pytest>=7.0"],
    },
    python_requires=">=3.10",
)
