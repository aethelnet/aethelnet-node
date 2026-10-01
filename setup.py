from setuptools import setup, find_packages

setup(
    name="aethelnet-node",
    version="1.0.0",
    description="Aethelnet Node: Production Evidentiary Ledger, Multigraph Reconciliation & Forensic REST Daemon",
    author="Auratic Systems Prime",
    license="AGPL-3.0",
    url="https://aethelburg.network",
    packages=find_packages(),
    install_requires=[
        "fastapi>=0.90.0",
        "uvicorn>=0.20.0",
        "httpx>=0.23.0",
        "pydantic>=1.10.0",
        "aethelnet-core>=1.0.0",
        "web3>=6.0.0",
    ],
    python_requires=">=3.10",
)
