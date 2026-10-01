"""
Aethelnet ERC-4337 v0.7 Micro-Bundler
Relays UserOperations to EntryPoint (0x0000000071727De22E5E9d8BAf0edAc6f37da032)
Sponsored by AethelnetPaymaster on Ethereum Sepolia.
"""

import os
import logging
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from web3 import Web3
from eth_account import Account

logger = logging.getLogger("Aethelnet.Bundler")

DEFAULT_RPC_URL = os.getenv("AETHELNET_RPC_URL", "https://sepolia.gateway.tenderly.co")
DEFAULT_BUNDLER_KEY = os.getenv("AETHELNET_BUNDLER_KEY", "d35bcb391904a95ef74a366654964d63ab09675ae7b82036d0f3ff28a0a69b1c")
ENTRY_POINT_ADDRESS = os.getenv("AETHELNET_ENTRYPOINT_ADDRESS", "0x0000000071727De22E5E9d8BAf0edAc6f37da032")
SEPOLIA_CHAIN_ID = 11155111

ENTRY_POINT_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "sender", "type": "address"},
                    {"internalType": "uint256", "name": "nonce", "type": "uint256"},
                    {"internalType": "bytes", "name": "initCode", "type": "bytes"},
                    {"internalType": "bytes", "name": "callData", "type": "bytes"},
                    {"internalType": "bytes32", "name": "accountGasLimits", "type": "bytes32"},
                    {"internalType": "uint256", "name": "preVerificationGas", "type": "uint256"},
                    {"internalType": "bytes32", "name": "gasFees", "type": "bytes32"},
                    {"internalType": "bytes", "name": "paymasterAndData", "type": "bytes"},
                    {"internalType": "bytes", "name": "signature", "type": "bytes"}
                ],
                "internalType": "struct PackedUserOperation[]",
                "name": "ops",
                "type": "tuple[]"
            },
            {"internalType": "address payable", "name": "beneficiary", "type": "address"}
        ],
        "name": "handleOps",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

app = FastAPI(title="Aethelnet ERC-4337 Bundler", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_web3_and_account():
    rpc = os.getenv("AETHELNET_RPC_URL", DEFAULT_RPC_URL)
    w3 = Web3(Web3.HTTPProvider(rpc))
    acc = Account.from_key(DEFAULT_BUNDLER_KEY)
    entry_point = w3.eth.contract(address=Web3.to_checksum_address(ENTRY_POINT_ADDRESS), abi=ENTRY_POINT_ABI)
    return w3, acc, entry_point

def _parse_bytes(val: Any) -> bytes:
    if isinstance(val, bytes):
        return val
    if isinstance(val, str):
        hex_str = val[2:] if val.startswith("0x") else val
        if len(hex_str) % 2 != 0:
            hex_str = "0" + hex_str
        return bytes.fromhex(hex_str)
    return b""

def _parse_int(val: Any) -> int:
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        return int(val, 16) if val.startswith("0x") else int(val)
    return 0

@app.post("/rpc")
@app.post("/")
async def handle_rpc(request: Request):
    body = await request.json()
    req_id = body.get("id", 1)
    method = body.get("method", "")
    params = body.get("params", [])

    logger.info(f"[Bundler] RPC Call: {method}")

    if method == "eth_supportedEntryPoints":
        return {"jsonrpc": "2.0", "id": req_id, "result": [ENTRY_POINT_ADDRESS]}

    elif method == "eth_chainId":
        return {"jsonrpc": "2.0", "id": req_id, "result": hex(SEPOLIA_CHAIN_ID)}

    elif method == "eth_sendUserOperation":
        try:
            if not params or len(params) < 1:
                return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Missing userOp parameter"}}

            user_op = params[0]
            logger.info(f"[Bundler] Processing UserOp for sender {user_op.get('sender')}")

            w3, acc, entry_point = get_web3_and_account()

            formatted_op = (
                Web3.to_checksum_address(user_op["sender"]),
                _parse_int(user_op["nonce"]),
                _parse_bytes(user_op.get("initCode", "0x")),
                _parse_bytes(user_op["callData"]),
                _parse_bytes(user_op["accountGasLimits"]),
                _parse_int(user_op["preVerificationGas"]),
                _parse_bytes(user_op["gasFees"]),
                _parse_bytes(user_op.get("paymasterAndData", "0x")),
                _parse_bytes(user_op["signature"])
            )

            # Build and sign transaction
            nonce = w3.eth.get_transaction_count(acc.address)
            gas_price = w3.eth.gas_price
            
            # Simulate first to prevent gas waste on reverts
            try:
                entry_point.functions.handleOps([formatted_op], acc.address).call({"from": acc.address})
            except Exception as sim_err:
                logger.warning(f"[Bundler] handleOps simulation reverted: {sim_err}")
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32500, "message": f"Simulation reverted: {sim_err}"}
                }

            tx_dict = entry_point.functions.handleOps([formatted_op], acc.address).build_transaction({
                "from": acc.address,
                "nonce": nonce,
                "gas": 2500000,
                "maxFeePerGas": int(gas_price * 2),
                "maxPriorityFeePerGas": int(w3.eth.max_priority_fee or 10**9),
                "chainId": SEPOLIA_CHAIN_ID
            })

            signed_tx = w3.eth.account.sign_transaction(tx_dict, private_key=acc.key)
            raw_bytes = getattr(signed_tx, "raw_transaction", None) or getattr(signed_tx, "rawTransaction", None)
            tx_hash = w3.eth.send_raw_transaction(raw_bytes)
            tx_hex = tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)
            if not tx_hex.startswith("0x"):
                tx_hex = "0x" + tx_hex
            logger.info(f"[Bundler] Dispatched handleOps tx: {tx_hex}. Awaiting confirmation...")

            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            status_str = "SUCCESS" if receipt.status == 1 else "FAILED"
            logger.info(f"[Bundler] Mined handleOps tx: {tx_hex} | Status: {status_str} | Block: {receipt.blockNumber}")

            if receipt.status != 1:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32603, "message": f"Execution reverted on chain (Tx: {tx_hex})"}
                }

            return {"jsonrpc": "2.0", "id": req_id, "result": tx_hex}

        except Exception as e:
            logger.error(f"[Bundler] Error submitting UserOp: {e}", exc_info=True)
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(e)}}

    else:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method '{method}' not found"}}

def main():
    import uvicorn
    port = int(os.getenv("PORT", "3000"))
    host = os.getenv("HOST", "0.0.0.0")
    logging.basicConfig(level=logging.INFO)
    logger.info(f"Starting Aethelnet ERC-4337 Micro-Bundler on {host}:{port}...")
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    main()
