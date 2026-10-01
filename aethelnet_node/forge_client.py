"""
Aethelnet TheForge Web3 Client
Provides on-chain peer registry synchronization, ERC-4337 Account Abstraction,
and gasless governance integration via AethelnetPaymaster on Ethereum Sepolia.
"""

import os
import json
import logging
import requests
from typing import List, Dict, Any, Optional
from web3 import Web3
from eth_abi import encode
from eth_account import Account
from eth_account.messages import encode_defunct

logger = logging.getLogger("Aethelnet.ForgeClient")

DEFAULT_RPC_URL = os.getenv("AETHELNET_RPC_URL", "https://sepolia.gateway.tenderly.co")
DEFAULT_FORGE_ADDRESS = "0xe79e0686FE39C1f3252D5404411010b2F36CaA2f"
DEFAULT_ENTRYPOINT_ADDRESS = "0x0000000071727De22E5E9d8BAf0edAc6f37da032"
DEFAULT_PAYMASTER_ADDRESS = "0xEAB2FA9DC49A1d9e6F9882FA0B5eA86Ce8ECD77b"
DEFAULT_FACTORY_ADDRESS = "0x5bc53145Cd53Ffc0e5697B2031028F7AfDd936d7"
DEFAULT_BUNDLER_URL = os.getenv("AETHELNET_BUNDLER_URL", "http://127.0.0.1:3000/rpc")
DEFAULT_CHAIN_ID = 11155111

# Minimal ABIs
FALLBACK_FORGE_ABI = [
    {
        "inputs": [{"internalType": "bytes32", "name": "caseId", "type": "bytes32"}],
        "name": "getCaseNotarization",
        "outputs": [
            {"internalType": "bytes32", "name": "stateRoot", "type": "bytes32"},
            {"internalType": "uint256", "name": "nodeCount", "type": "uint256"},
            {"internalType": "uint256", "name": "edgeCount", "type": "uint256"},
            {"internalType": "uint256", "name": "timestamp", "type": "uint256"},
            {"internalType": "address", "name": "notary", "type": "address"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "caseId", "type": "bytes32"},
            {"internalType": "bytes32", "name": "stateRoot", "type": "bytes32"},
            {"internalType": "uint256", "name": "nodeCount", "type": "uint256"},
            {"internalType": "uint256", "name": "edgeCount", "type": "uint256"}
        ],
        "name": "commitStateRoot",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "getNotarizedCases",
        "outputs": [{"internalType": "bytes32[]", "name": "", "type": "bytes32[]"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "getActiveNodes",
        "outputs": [{"internalType": "string[]", "name": "", "type": "string[]"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "string", "name": "ipAddress", "type": "string"}],
        "name": "registerNode",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "address", "name": "", "type": "address"}],
        "name": "peerRegistry",
        "outputs": [
            {"internalType": "string", "name": "ipAddress", "type": "string"},
            {"internalType": "uint256", "name": "lastSeen", "type": "uint256"},
            {"internalType": "bool", "name": "isActive", "type": "bool"}
        ],
        "stateMutability": "view",
        "type": "function"
    }
]

FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "uint256", "name": "salt", "type": "uint256"}
        ],
        "name": "getAddress",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "uint256", "name": "salt", "type": "uint256"}
        ],
        "name": "createAccount",
        "outputs": [{"internalType": "contract SimpleAccount", "name": "ret", "type": "address"}],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

SIMPLE_ACCOUNT_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "dest", "type": "address"},
            {"internalType": "uint256", "name": "value", "type": "uint256"},
            {"internalType": "bytes", "name": "func", "type": "bytes"}
        ],
        "name": "execute",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

ENTRY_POINT_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "sender", "type": "address"},
            {"internalType": "uint192", "name": "key", "type": "uint192"}
        ],
        "name": "getNonce",
        "outputs": [{"internalType": "uint256", "name": "nonce", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]

def resolve_wan_ip() -> str:
    """
    Resolves the true WAN IP.
    1. Tries UDP STUN via stun.l.google.com:19302.
    2. Fallback to HTTPS ipify.org.
    Raises ValueError if IP is local or cannot be resolved.
    """
    import ipaddress
    wan_ip = None
    try:
        import stun
        nat_type, external_ip, external_port = stun.get_ip_info(stun_host='stun.l.google.com', stun_port=19302)
        if external_ip:
            wan_ip = external_ip
            logger.info(f"[ForgeClient] STUN Resolution Successful: {wan_ip}")
    except Exception as e:
        logger.warning(f"[ForgeClient] UDP STUN failed/unavailable: {e}. Falling back to HTTPS.")

    if not wan_ip:
        try:
            res = requests.get("https://api.ipify.org?format=json", timeout=5)
            res.raise_for_status()
            wan_ip = res.json().get("ip")
            logger.info(f"[ForgeClient] HTTPS Fallback Resolution Successful: {wan_ip}")
        except Exception as e:
            raise RuntimeError(f"Could not resolve WAN IP: {e}")

    if not wan_ip:
        raise RuntimeError("WAN IP resolution returned empty.")

    # Validate IP
    ip_obj = ipaddress.ip_address(wan_ip)
    if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
        raise ValueError(f"Resolved IP {wan_ip} is a local/private IP! Aborting.")

    return wan_ip

class ForgeClient:
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        contract_address: Optional[str] = None,
        private_key: Optional[str] = None,
        bundler_url: Optional[str] = None,
        entry_point_address: Optional[str] = None,
        paymaster_address: Optional[str] = None,
        factory_address: Optional[str] = None,
        chain_id: Optional[int] = None
    ):
        self.rpc_url = rpc_url or os.getenv("AETHELNET_RPC_URL", DEFAULT_RPC_URL)
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        
        self.contract_address = self._resolve_contract_address(contract_address)
        self.entry_point_address = entry_point_address or os.getenv("AETHELNET_ENTRYPOINT_ADDRESS", DEFAULT_ENTRYPOINT_ADDRESS)
        self.paymaster_address = paymaster_address or os.getenv("AETHELNET_PAYMASTER_ADDRESS", DEFAULT_PAYMASTER_ADDRESS)
        self.factory_address = factory_address or os.getenv("AETHELNET_FACTORY_ADDRESS", DEFAULT_FACTORY_ADDRESS)
        self.bundler_url = bundler_url or os.getenv("AETHELNET_BUNDLER_URL", DEFAULT_BUNDLER_URL)
        self.chain_id = chain_id or int(os.getenv("AETHELNET_CHAIN_ID", str(DEFAULT_CHAIN_ID)))

        self.abi = self._resolve_abi()
        
        # Load or generate persistent Node Identity
        self.account = self._init_identity(private_key)

        # Contracts
        if self.contract_address and self.abi:
            self.contract = self.w3.eth.contract(address=Web3.to_checksum_address(self.contract_address), abi=self.abi)
        else:
            self.contract = None

        self.factory = self.w3.eth.contract(address=Web3.to_checksum_address(self.factory_address), abi=FACTORY_ABI)
        self.entry_point = self.w3.eth.contract(address=Web3.to_checksum_address(self.entry_point_address), abi=ENTRY_POINT_ABI)
        self.simple_account_interface = self.w3.eth.contract(abi=SIMPLE_ACCOUNT_ABI)

    def _init_identity(self, explicit_key: Optional[str]) -> Account:
        if explicit_key:
            acc = Account.from_key(explicit_key)
            logger.info(f"[ForgeClient] Initialized with explicit key: {acc.address}")
            return acc
            
        env_key = os.getenv("AETHELNET_PRIVATE_KEY")
        if env_key:
            acc = Account.from_key(env_key)
            logger.info(f"[ForgeClient] Initialized from AETHELNET_PRIVATE_KEY: {acc.address}")
            return acc

        # Check local identity file
        identity_dir = os.path.expanduser("~/.aethelnet")
        identity_file = os.path.join(identity_dir, "node_identity.json")
        os.makedirs(identity_dir, exist_ok=True)

        if os.path.exists(identity_file):
            try:
                with open(identity_file, "r") as f:
                    data = json.load(f)
                    acc = Account.from_key(data["private_key"])
                    logger.info(f"[ForgeClient] Loaded persistent node identity: {acc.address}")
                    return acc
            except Exception as e:
                logger.warning(f"[ForgeClient] Failed loading identity from {identity_file}: {e}")

        # Create fresh zero-balance key
        acc = Account.create()
        try:
            with open(identity_file, "w") as f:
                json.dump({
                    "address": acc.address,
                    "private_key": acc.key.hex()
                }, f, indent=2)
            logger.info(f"[ForgeClient] Created fresh persistent node identity: {acc.address} (Saved to {identity_file})")
        except Exception as e:
            logger.warning(f"[ForgeClient] Could not save identity file: {e}")

        return acc

    def _find_contracts_file(self, rel_path: str) -> Optional[str]:
        candidate_bases = []
        if env_dir := os.getenv("AETHELNET_CONTRACTS_DIR"):
            candidate_bases.append(env_dir)
        # Check adjacent packages/aethelnet-contracts, user home, current dir
        pkg_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        candidate_bases.extend([
            os.path.join(pkg_dir, "aethelnet-contracts"),
            os.path.join(os.path.expanduser("~"), "aethelnet-contracts"),
            os.path.join(os.getcwd(), "contracts"),
            os.getcwd()
        ])
        for base in candidate_bases:
            candidate = os.path.join(base, rel_path)
            if os.path.isfile(candidate):
                return candidate
        return None

    def _resolve_contract_address(self, explicit_addr: Optional[str]) -> str:
        if explicit_addr:
            return explicit_addr
        
        env_addr = os.getenv("AETHELNET_FORGE_ADDRESS")
        if env_addr:
            return env_addr
            
        manifest_path = self._find_contracts_file("deployed_addresses.json")
        if manifest_path and os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r") as f:
                    manifest = json.load(f)
                    if "TheForge" in manifest:
                        return manifest["TheForge"]
            except Exception as e:
                logger.debug(f"[ForgeClient] Could not read deployed_addresses.json: {e}")
                
        return DEFAULT_FORGE_ADDRESS

    def _resolve_abi(self) -> list:
        artifact_path = self._find_contracts_file(os.path.join("artifacts", "contracts", "TheForge.sol", "TheForge.json"))
        if artifact_path and os.path.exists(artifact_path):
            try:
                with open(artifact_path, "r") as f:
                    data = json.load(f)
                    abi = data.get("abi", [])
                    if any(item.get("name") == "getCaseNotarization" for item in abi):
                        return abi
            except Exception as e:
                logger.warning(f"[ForgeClient] Failed reading TheForge artifact: {e}")
        return FALLBACK_FORGE_ABI

    def is_connected(self) -> bool:
        try:
            return self.w3.is_connected()
        except Exception:
            return False

    def commit_state_root(
        self,
        case_id: str,
        state_root: str,
        node_count: int,
        edge_count: int,
        use_paymaster: bool = True
    ) -> Dict[str, Any]:
        """
        Notarizes an evidentiary multigraph state root on-chain to TheForge.
        Guarantees immutable forensic provenance for investigations.
        """
        if not self.is_connected():
            raise ConnectionError(f"RPC {self.rpc_url} unreachable")
        if not self.contract:
            raise ValueError("TheForge contract not loaded")
        if not self.account:
            raise ValueError("No node identity account available")

        # Convert strings to bytes32 if needed
        case_bytes32 = Web3.keccak(text=case_id) if not case_id.startswith("0x") or len(case_id) != 66 else bytes.fromhex(case_id[2:])
        root_bytes32 = bytes.fromhex(state_root[2:]) if state_root.startswith("0x") and len(state_root) == 66 else Web3.keccak(text=state_root)

        if use_paymaster:
            return self._commit_state_root_gasless(case_bytes32, root_bytes32, node_count, edge_count, case_id)
        else:
            return self._commit_state_root_direct(case_bytes32, root_bytes32, node_count, edge_count, case_id)

    def _commit_state_root_gasless(
        self,
        case_bytes32: bytes,
        root_bytes32: bytes,
        node_count: int,
        edge_count: int,
        case_id: str
    ) -> Dict[str, Any]:
        owner_addr = Web3.to_checksum_address(self.account.address)
        sender_address = self.factory.functions.getAddress(owner_addr, 0).call()
        logger.info(f"[ForgeClient] Gasless commitStateRoot for case '{case_id}' (Sender: {sender_address})...")

        code = self.w3.eth.get_code(sender_address)
        if len(code) == 0:
            create_calldata = self.factory.encode_abi("createAccount", args=[owner_addr, 0])
            init_code = self.factory_address + create_calldata[2:]
        else:
            init_code = "0x"

        nonce = self.entry_point.functions.getNonce(sender_address, 0).call()

        inner_calldata = self.contract.encode_abi(
            "commitStateRoot",
            args=[case_bytes32, root_bytes32, node_count, edge_count]
        )
        execute_calldata = self.simple_account_interface.encode_abi(
            "execute",
            args=[Web3.to_checksum_address(self.contract_address), 0, bytes.fromhex(inner_calldata[2:])]
        )

        account_gas_limits = "0x" + f"{(500000 << 128) | 500000:064x}"
        pre_verification_gas = "0x186a0"
        gas_fees = "0x" + f"{(10**9 << 128) | (2 * 10**9):064x}"
        paymaster_and_data = self.paymaster_address + f"{500000:032x}" + f"{50000:032x}"

        inner = encode(
            ["address", "uint256", "bytes32", "bytes32", "bytes32", "uint256", "bytes32", "bytes32"],
            [
                Web3.to_checksum_address(sender_address),
                nonce,
                Web3.keccak(hexstr=init_code),
                Web3.keccak(hexstr=execute_calldata),
                bytes.fromhex(account_gas_limits[2:]),
                100000,
                bytes.fromhex(gas_fees[2:]),
                Web3.keccak(hexstr=paymaster_and_data)
            ]
        )
        inner_hash = Web3.keccak(inner)
        outer = encode(
            ["bytes32", "address", "uint256"],
            [inner_hash, Web3.to_checksum_address(self.entry_point_address), self.chain_id]
        )
        user_op_hash = Web3.keccak(outer)
        msg = encode_defunct(primitive=user_op_hash)
        sig = self.account.sign_message(msg).signature.hex()

        user_op = {
            "sender": sender_address,
            "nonce": hex(nonce),
            "initCode": init_code,
            "callData": execute_calldata,
            "accountGasLimits": account_gas_limits,
            "preVerificationGas": pre_verification_gas,
            "gasFees": gas_fees,
            "paymasterAndData": paymaster_and_data,
            "signature": "0x" + sig
        }

        logger.info(f"[ForgeClient] Dispatching commitStateRoot UserOp to Bundler ({self.bundler_url})...")
        res = requests.post(self.bundler_url, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_sendUserOperation",
            "params": [user_op, self.entry_point_address]
        }, timeout=60)

        res_data = res.json()
        if "error" in res_data:
            error_msg = res_data["error"].get("message", str(res_data["error"]))
            raise RuntimeError(f"Bundler rejected UserOp: {error_msg}")

        tx_hash = res_data["result"]
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        success = (receipt.status == 1)

        return {
            "success": success,
            "tx_hash": tx_hash,
            "block_number": receipt.blockNumber,
            "case_id": case_id,
            "state_root": "0x" + root_bytes32.hex(),
            "node_count": node_count,
            "edge_count": edge_count,
            "gasless": True
        }

    def _commit_state_root_direct(
        self,
        case_bytes32: bytes,
        root_bytes32: bytes,
        node_count: int,
        edge_count: int,
        case_id: str
    ) -> Dict[str, Any]:
        nonce = self.w3.eth.get_transaction_count(self.account.address)
        gas_price = self.w3.eth.gas_price
        tx = self.contract.functions.commitStateRoot(
            case_bytes32, root_bytes32, node_count, edge_count
        ).build_transaction({
            "from": self.account.address,
            "nonce": nonce,
            "gas": 300000,
            "gasPrice": gas_price
        })
        signed_tx = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
        return {
            "success": receipt.status == 1,
            "tx_hash": tx_hash.hex(),
            "block_number": receipt.blockNumber,
            "case_id": case_id,
            "state_root": "0x" + root_bytes32.hex(),
            "node_count": node_count,
            "edge_count": edge_count,
            "gasless": False
        }

    def get_case_notarization(self, case_id: str) -> Dict[str, Any]:
        if not self.is_connected() or not self.contract:
            return {"is_notarized": False, "error": "RPC or contract unavailable"}
        try:
            case_bytes32 = Web3.keccak(text=case_id) if not case_id.startswith("0x") or len(case_id) != 66 else bytes.fromhex(case_id[2:])
            root, nodes, edges, timestamp, notary = self.contract.functions.getCaseNotarization(case_bytes32).call()
            return {
                "case_id": case_id,
                "state_root": "0x" + root.hex() if isinstance(root, bytes) else str(root),
                "node_count": nodes,
                "edge_count": edges,
                "timestamp": timestamp,
                "notary": notary,
                "is_notarized": timestamp > 0
            }
        except Exception as e:
            logger.error(f"[ForgeClient] Error reading getCaseNotarization({case_id}): {e}")
            return {"is_notarized": False, "error": str(e)}

    def register_node(self, ip_address: str, use_paymaster: bool = True) -> Dict[str, Any]:
        """
        Submits an on-chain heartbeat transaction to register this node's IP in TheForge.
        Uses ERC-4337 Account Abstraction with AethelnetPaymaster sponsorship when use_paymaster=True.
        """
        if not self.is_connected():
            raise ConnectionError(f"RPC {self.rpc_url} unreachable")
        if not self.contract:
            raise ValueError("TheForge contract not loaded")
        if not self.account:
            raise ValueError("No node identity account available")

        if use_paymaster:
            return self._register_node_gasless(ip_address)
        else:
            return self._register_node_direct(ip_address)

    def _register_node_gasless(self, ip_address: str) -> Dict[str, Any]:
        """
        Constructs and broadcasts an ERC-4337 UserOperation sponsored by AethelnetPaymaster.
        Guarantees 0.00 ETH execution.
        """
        owner_addr = Web3.to_checksum_address(self.account.address)
        balance = self.w3.eth.get_balance(owner_addr)
        logger.info(f"[ForgeClient] Gasless registerNode for '{ip_address}'. Node Owner: {owner_addr} (Balance: {self.w3.from_wei(balance, 'ether')} ETH)")

        # 1. Derive sender address via factory
        sender_address = self.factory.functions.getAddress(owner_addr, 0).call()
        logger.info(f"[ForgeClient] Smart Account Sender: {sender_address}")

        # Check if already registered and within cooldown
        if self.contract:
            try:
                reg_ip, last_seen, is_active = self.contract.functions.peerRegistry(sender_address).call()
                import time
                age = int(time.time()) - last_seen
                if is_active and reg_ip == ip_address and age < 1800:
                    logger.info(f"[ForgeClient] Node '{ip_address}' already active in TheForge (age {age}s < 1800s cooldown). Skipping UserOp.")
                    return {
                        "success": True,
                        "rate_limited": True,
                        "message": f"Already active on-chain ({age}s ago)",
                        "ip_address": ip_address,
                        "sender": sender_address,
                        "gasless": True
                    }
            except Exception as e:
                logger.debug(f"[ForgeClient] peerRegistry check skipped: {e}")

        # 2. Check if deployed
        code = self.w3.eth.get_code(sender_address)
        if len(code) == 0:
            create_calldata = self.factory.encode_abi("createAccount", args=[owner_addr, 0])
            init_code = self.factory_address + create_calldata[2:]
        else:
            init_code = "0x"

        # 3. Nonce
        nonce = self.entry_point.functions.getNonce(sender_address, 0).call()

        # 4. Calldata: TheForge.registerNode(ip)
        inner_calldata = self.contract.encode_abi("registerNode", args=[ip_address])
        # SimpleAccount.execute(TheForge, 0, inner_calldata)
        execute_calldata = self.simple_account_interface.encode_abi(
            "execute", 
            args=[Web3.to_checksum_address(self.contract_address), 0, bytes.fromhex(inner_calldata[2:])]
        )

        # 5. Gas limits & fees
        account_gas_limits = "0x" + f"{(500000 << 128) | 500000:064x}"
        pre_verification_gas = "0x186a0" # 100000
        gas_fees = "0x" + f"{(10**9 << 128) | (2 * 10**9):064x}"
        paymaster_and_data = self.paymaster_address + f"{500000:032x}" + f"{50000:032x}"

        # 6. UserOp Hash calculation (v0.7.0)
        inner = encode(
            ["address", "uint256", "bytes32", "bytes32", "bytes32", "uint256", "bytes32", "bytes32"],
            [
                Web3.to_checksum_address(sender_address),
                nonce,
                Web3.keccak(hexstr=init_code),
                Web3.keccak(hexstr=execute_calldata),
                bytes.fromhex(account_gas_limits[2:]),
                100000,
                bytes.fromhex(gas_fees[2:]),
                Web3.keccak(hexstr=paymaster_and_data)
            ]
        )
        inner_hash = Web3.keccak(inner)
        outer = encode(
            ["bytes32", "address", "uint256"],
            [inner_hash, Web3.to_checksum_address(self.entry_point_address), self.chain_id]
        )
        user_op_hash = Web3.keccak(outer)

        # 7. Sign UserOp with EIP-191 personal sign
        msg = encode_defunct(primitive=user_op_hash)
        sig = self.account.sign_message(msg).signature.hex()

        user_op = {
            "sender": sender_address,
            "nonce": hex(nonce),
            "initCode": init_code,
            "callData": execute_calldata,
            "accountGasLimits": account_gas_limits,
            "preVerificationGas": pre_verification_gas,
            "gasFees": gas_fees,
            "paymasterAndData": paymaster_and_data,
            "signature": "0x" + sig
        }

        # 8. Post UserOp to Bundler
        logger.info(f"[ForgeClient] Dispatching UserOp to Bundler ({self.bundler_url})...")
        res = requests.post(self.bundler_url, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_sendUserOperation",
            "params": [user_op, self.entry_point_address]
        }, timeout=60)

        res_data = res.json()
        if "error" in res_data:
            error_msg = res_data["error"].get("message", str(res_data["error"]))
            if any(k in error_msg.lower() for k in ["rate limit", "cooldown", "throttled", "revert"]):
                logger.warning(f"[ForgeClient] Node heartbeat throttled or reverted by Paymaster cooldown: {error_msg}")
                return {
                    "success": True,
                    "rate_limited": True,
                    "message": error_msg,
                    "ip_address": ip_address,
                    "sender": sender_address,
                    "gasless": True
                }
            raise RuntimeError(f"Bundler rejected UserOp: {error_msg}")

        tx_hash = res_data["result"]
        logger.info(f"[ForgeClient] UserOp submitted in Tx: {tx_hash}. Awaiting confirmation...")

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        success = (receipt.status == 1)
        logger.info(
            f"[ForgeClient] Gasless registerNode Mined: {tx_hash} | Status: {'SUCCESS' if success else 'FAILED'} | Gas: {receipt.gasUsed} | Block: {receipt.blockNumber}"
        )

        return {
            "success": success,
            "tx_hash": tx_hash,
            "block_number": receipt.blockNumber,
            "gas_used": receipt.gasUsed,
            "ip_address": ip_address,
            "sender": sender_address,
            "gasless": True
        }

    def _register_node_direct(self, ip_address: str) -> Dict[str, Any]:
        """Legacy direct EOA registerNode transaction requiring native ETH gas."""
        logger.info(f"[ForgeClient] Direct EOA registerNode('{ip_address}') to {self.contract_address}...")
        nonce = self.w3.eth.get_transaction_count(self.account.address)
        gas_price = self.w3.eth.gas_price
        
        tx = self.contract.functions.registerNode(ip_address).build_transaction({
            "from": self.account.address,
            "nonce": nonce,
            "gas": 250000,
            "gasPrice": gas_price
        })
        
        signed_tx = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
        
        success = (receipt.status == 1)
        return {
            "success": success,
            "tx_hash": tx_hash.hex(),
            "block_number": receipt.blockNumber,
            "ip_address": ip_address,
            "gasless": False
        }

    def get_active_nodes(self) -> List[str]:
        """
        Queries TheForge.sol getActiveNodes() to return all registered, active peers (seen in last 24h).
        """
        if not self.is_connected():
            logger.warning(f"[ForgeClient] RPC {self.rpc_url} unreachable. Cannot fetch active nodes.")
            return []
        if not self.contract:
            logger.warning("[ForgeClient] TheForge contract not configured.")
            return []

        try:
            nodes = self.contract.functions.getActiveNodes().call()
            # Clean and filter empty strings
            valid_nodes = [n.strip() for n in nodes if n and n.strip()]
            logger.info(f"[ForgeClient] Discovered {len(valid_nodes)} active node(s) on TheForge: {valid_nodes}")
            return valid_nodes
        except Exception as e:
            logger.error(f"[ForgeClient] Error executing getActiveNodes() call: {e}")
            return []

    def get_peer_info(self, address: str) -> Dict[str, Any]:
        """
        Queries peer status from peerRegistry mapping.
        """
        if not self.is_connected() or not self.contract:
            return {}
        try:
            checksum = Web3.to_checksum_address(address)
            ip, last_seen, is_active = self.contract.functions.peerRegistry(checksum).call()
            return {
                "address": checksum,
                "ip": ip,
                "last_seen": last_seen,
                "is_active": is_active
            }
        except Exception as e:
            logger.error(f"[ForgeClient] Failed fetching peer info for {address}: {e}")
            return {}

# Global singleton client
forge_client = ForgeClient()
