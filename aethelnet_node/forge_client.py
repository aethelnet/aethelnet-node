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

DEFAULT_RPC_URL = "https://ethereum-sepolia.publicnode.com"
DEFAULT_FORGE_ADDRESS = "0x58A520120BEfCBB1dA7A9546c1f1F98C9e6ef1A5"
DEFAULT_ENTRYPOINT_ADDRESS = "0x0000000071727De22E5E9d8BAf0edAc6f37da032"
DEFAULT_PAYMASTER_ADDRESS = "0x9A48A9613e93D2496C794CC51086Ca1F4b2A298f"
DEFAULT_FACTORY_ADDRESS = "0x5bc53145Cd53Ffc0e5697B2031028F7AfDd936d7"
DEFAULT_BUNDLER_URL = "http://localhost:3000/rpc"
DEFAULT_CHAIN_ID = 11155111

# Minimal ABIs
FALLBACK_FORGE_ABI = [
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
    import stun
    import ipaddress
    wan_ip = None
    try:
        nat_type, external_ip, external_port = stun.get_ip_info(stun_host='stun.l.google.com', stun_port=19302)
        if external_ip:
            wan_ip = external_ip
            logger.info(f"[ForgeClient] STUN Resolution Successful: {wan_ip}")
    except Exception as e:
        logger.warning(f"[ForgeClient] UDP STUN failed: {e}. Falling back to HTTPS.")

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

    def _resolve_contract_address(self, explicit_addr: Optional[str]) -> str:
        if explicit_addr:
            return explicit_addr
        
        env_addr = os.getenv("AETHELNET_FORGE_ADDRESS")
        if env_addr:
            return env_addr
            
        manifest_path = "/home/ubuntu/aethelnet-contracts/deployed_addresses.json"
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r") as f:
                    manifest = json.load(f)
                    if "TheForge" in manifest:
                        return manifest["TheForge"]
            except Exception as e:
                logger.debug(f"[ForgeClient] Could not read deployed_addresses.json: {e}")
                
        return DEFAULT_FORGE_ADDRESS

    def _resolve_abi(self) -> list:
        artifact_path = "/home/ubuntu/aethelnet-contracts/artifacts/contracts/TheForge.sol/TheForge.json"
        if os.path.exists(artifact_path):
            try:
                with open(artifact_path, "r") as f:
                    data = json.load(f)
                    return data.get("abi", FALLBACK_FORGE_ABI)
            except Exception as e:
                logger.warning(f"[ForgeClient] Failed reading TheForge artifact: {e}")
        return FALLBACK_FORGE_ABI

    def is_connected(self) -> bool:
        try:
            return self.w3.is_connected()
        except Exception:
            return False

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
            if "rate limited" in error_msg:
                logger.warning(f"[ForgeClient] Node heartbeat throttled by Paymaster cooldown (30 min): {error_msg}")
                return {
                    "success": False,
                    "rate_limited": True,
                    "message": error_msg,
                    "ip_address": ip_address
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
