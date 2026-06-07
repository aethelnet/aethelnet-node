from setuptools import setup, find_packages

setup(
    name="aethelnet-node",
    version="1.0.0",
    description="Decentralized P2P Gossip Node for Aethelnet",
    author="Aethelnet",
    packages=find_packages(),
    install_requires=[
        "fastapi>=0.90.0",
        "uvicorn>=0.20.0",
        "httpx>=0.23.0",
        "pydantic>=1.10.0",
    ],
    python_requires=">=3.9",
)
