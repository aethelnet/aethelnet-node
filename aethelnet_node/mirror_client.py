#!/usr/bin/env python3
"""
Aethelnet Autonomous Mirror & Independent Verifier Client
Allows any external peer, researcher, or institution to independently mirror an
investigation case, compute the canonical Merkle state root locally, and verify
cryptographic authenticity directly against TheForge smart contract on Ethereum Sepolia.
"""

import os
import sys
import json
import hashlib
import argparse
import requests
import time
import base64
from typing import Dict, Any, List, Optional
from web3 import Web3

def compute_ipfs_cid(data: bytes) -> str:
    """
    Computes a standard IPFS CIDv1 (raw multicodec 0x55, sha256 multihash 0x12 0x20, base32).
    """
    digest = hashlib.sha256(data).digest()
    multihash = bytes([0x12, 0x20]) + digest
    cid_bytes = bytes([0x01, 0x55]) + multihash
    b32 = base64.b32encode(cid_bytes).decode("ascii").lower().rstrip("=")
    return "b" + b32

DEFAULT_NODE_URL = "https://aethelburg.network"
DEFAULT_RPC_URL = "https://sepolia.gateway.tenderly.co"
THE_FORGE_ADDRESS = "0xe79e0686FE39C1f3252D5404411010b2F36CaA2f"

FORGE_ABI = [
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
    }
]

def compute_local_state_root(case_id: str, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Computes the canonical deterministic SHA-256 Merkle root from raw nodes and edges.
    Runs identically on any machine without requiring GPU or heavyweight dependencies.
    """
    node_hashes = []
    for n in nodes:
        nid = n.get("id", "")
        ntxt = n.get("text_content") or ""
        nh = hashlib.sha256(f"node:{nid}:{ntxt}".encode("utf-8")).hexdigest()
        node_hashes.append(nh)
    node_hashes.sort()

    edge_hashes = []
    for e in edges:
        eid = e.get("edge_id")
        src = e.get("source")
        tgt = e.get("target")
        rel = e.get("relation_type")
        w = e.get("weight")
        eh = hashlib.sha256(f"edge:{eid}:{src}:{tgt}:{rel}:{w}".encode("utf-8")).hexdigest()
        edge_hashes.append(eh)
    edge_hashes.sort()

    combined_payload = f"{case_id}::" + ":".join(node_hashes) + "||" + ":".join(edge_hashes)
    computed_root = "0x" + hashlib.sha256(combined_payload.encode("utf-8")).hexdigest()

    return {
        "case_id": case_id,
        "computed_state_root": computed_root,
        "node_count": len(nodes),
        "edge_count": len(edges)
    }

def fetch_on_chain_notarization(case_id: str, rpc_url: str, contract_address: str) -> Dict[str, Any]:
    """
    Queries Ethereum Sepolia directly via Web3 RPC to fetch the notarized state root.
    """
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise ConnectionError(f"Cannot connect to Ethereum RPC at {rpc_url}")

    contract = w3.eth.contract(address=Web3.to_checksum_address(contract_address), abi=FORGE_ABI)
    case_bytes32 = Web3.keccak(text=case_id)
    raw = contract.functions.getCaseNotarization(case_bytes32).call()

    state_root = "0x" + raw[0].hex()
    is_notarized = (raw[3] > 0 and state_root != "0x" + "00"*32)

    return {
        "is_notarized": is_notarized,
        "state_root": state_root,
        "node_count": raw[1],
        "edge_count": raw[2],
        "timestamp": raw[3],
        "notary": raw[4]
    }

def audit_bundle_file(bundle_path: str, verify: bool = True, rpc_url: str = DEFAULT_RPC_URL):
    print("=" * 70)
    print(f"  AETHELNET OFFLINE EVIDENCE BUNDLE AUDITOR")
    print(f"  Target File: {bundle_path}")
    print("=" * 70)

    if not os.path.exists(bundle_path):
        print(f"[FAIL] Bundle file not found: {bundle_path}")
        sys.exit(1)

    with open(bundle_path, "r", encoding="utf-8") as f:
        bundle = json.load(f)

    manifest = bundle.get("manifest", {})
    payload = bundle.get("payload", bundle)
    case_id = manifest.get("case_id") or payload.get("case_id", "unknown_case")
    nodes = payload.get("nodes", [])
    edges = payload.get("edges", [])

    print(f"[1/3] Loaded bundle: {len(nodes)} nodes, {len(edges)} edges for case '{case_id}'.")
    
    # 2. Local State Root Calculation
    local_calc = compute_local_state_root(case_id, nodes, edges)
    local_root = local_calc["computed_state_root"]
    print(f"[2/3] Locally Reconstructed State Root: {local_root}")

    # Compute IPFS CID
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    cid = compute_ipfs_cid(serialized)
    print(f"      Locally Reconstructed IPFS CID: {cid}")

    if verify:
        print("[3/3] Cross-referencing Ethereum Sepolia (TheForge)...")
        try:
            on_chain = fetch_on_chain_notarization(case_id, rpc_url, THE_FORGE_ADDRESS)
            chain_root = on_chain["state_root"]
            print(f"      On-Chain Notarized Root:        {chain_root}")
            print(f"      On-Chain Timestamp:             {on_chain['timestamp']}")
            print(f"      On-Chain Notary Signer:         {on_chain['notary']}")

            root_match = (local_root.lower() == chain_root.lower())
            count_match = (len(nodes) == on_chain["node_count"] and len(edges) == on_chain["edge_count"])

            if root_match and count_match:
                print("\n[>>> AUDIT RESULT: PASSED <<<]")
                print("100% BIT-EXACT CRYPTOGRAPHIC VERIFICATION CONFIRMED BY ETHEREUM.")
            else:
                print("\n[>>> AUDIT RESULT: MISMATCH / TAMPERING DETECTED <<<]")
                if not root_match:
                    print(f"Divergence: File Root ({local_root}) != Chain Root ({chain_root})")
                if not count_match:
                    print(f"Count mismatch: File ({len(nodes)}/{len(edges)}) vs Chain ({on_chain['node_count']}/{on_chain['edge_count']})")
        except Exception as e:
            print(f"      [WARN] Could not query Ethereum RPC: {e}")

    print("=" * 70)

def mirror_case(node_url: str, case_id: str, output_dir: str, verify: bool = True, rpc_url: str = DEFAULT_RPC_URL):
    os.makedirs(output_dir, exist_ok=True)
    base = node_url.rstrip("/")
    
    print("=" * 70)
    print(f"  AETHELNET INDEPENDENT CASE MIRROR & AUDIT ENGINE")
    print(f"  Source Node: {base} | Target Case: '{case_id}'")
    print("=" * 70)

    # 1. Fetch Multigraph from Remote Node (try export_bundle first, fallback to multigraph)
    print(f"[1/4] Fetching canonical evidentiary bundle for '{case_id}'...")
    res = requests.get(f"{base}/api/ontology/multigraph/{case_id}/export_bundle", timeout=30)
    bundle_data = None
    if res.status_code == 200:
        bundle_data = res.json()
        payload = bundle_data.get("payload", {})
        nodes = payload.get("nodes", [])
        edges = payload.get("edges", [])
        conflicts = payload.get("conflicts", [])
    else:
        res = requests.get(f"{base}/api/ontology/multigraph/{case_id}", timeout=30)
        if res.status_code != 200:
            print(f"[FAIL] HTTP {res.status_code}: {res.text}")
            sys.exit(1)
        data = res.json()
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        conflicts = data.get("conflicts", [])

    print(f"      Retrieved: {len(nodes)} nodes, {len(edges)} edges, {len(conflicts)} active conflicts.")

    # 2. Compute Deterministic Merkle State Root Locally
    print("[2/4] Computing canonical SHA-256 Merkle root locally...")
    local_calc = compute_local_state_root(case_id, nodes, edges)
    local_root = local_calc["computed_state_root"]
    print(f"      Locally Computed State Root: {local_root}")

    # 3. Verify Against On-Chain Smart Contract
    verified = False
    if verify:
        print("[3/4] Verifying against TheForge smart contract on Ethereum Sepolia...")
        try:
            on_chain = fetch_on_chain_notarization(case_id, rpc_url, THE_FORGE_ADDRESS)
            chain_root = on_chain["state_root"]
            print(f"      On-Chain Notarized Root:     {chain_root}")
            print(f"      On-Chain Timestamp:          {on_chain['timestamp']}")
            print(f"      On-Chain Notary Signer:      {on_chain['notary']}")

            root_match = (local_root.lower() == chain_root.lower())
            count_match = (local_calc["node_count"] == on_chain["node_count"] and local_calc["edge_count"] == on_chain["edge_count"])

            if root_match and count_match:
                verified = True
                print("\n[>>> AUDIT RESULT: PASSED <<<]")
                print("100% BIT-EXACT CRYPTOGRAPHIC VERIFICATION CONFIRMED BY ETHEREUM.")
                print("No entity has tampered with or retroactively altered the evidence graph.")
            else:
                print("\n[>>> AUDIT RESULT: MISMATCH / DISSONANCE <<<]")
                if not root_match:
                    print(f"Root divergence: Local ({local_root}) != On-Chain ({chain_root})")
                if not count_match:
                    print(f"Element count mismatch: Nodes {local_calc['node_count']} vs {on_chain['node_count']}, Edges {local_calc['edge_count']} vs {on_chain['edge_count']}")
        except Exception as e:
            print(f"      [WARN] Could not query Ethereum RPC: {e}")

    # 4. Save Persistent Mirror Snapshot
    print(f"[4/4] Saving persistent offline mirror snapshot...")
    snapshot_filename = f"mirror_{case_id}_{local_root[:18]}.json"
    snapshot_path = os.path.join(output_dir, snapshot_filename)
    
    mirror_bundle = {
        "case_id": case_id,
        "source_node": base,
        "mirrored_at": int(time.time()),
        "state_root": local_root,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "is_on_chain_verified": verified,
        "contract": THE_FORGE_ADDRESS,
        "nodes": nodes,
        "edges": edges,
        "conflicts": conflicts
    }

    # Compute IPFS CID for mirror bundle
    serialized = json.dumps(mirror_bundle, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    cid = compute_ipfs_cid(serialized)
    mirror_bundle["ipfs_cid_v1"] = cid
    print(f"      Canonical IPFS CIDv1:        {cid}")

    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(mirror_bundle, f, indent=2, ensure_ascii=False)

    print(f"      Mirror successfully saved to: {snapshot_path}")
    print("=" * 70)
    print(f"Independent mirror ready. Even if {base} is offline,")
    print(f"this local snapshot serves as an undeniable cryptographic witness.")
    print("=" * 70)

def main():
    parser = argparse.ArgumentParser(description="Aethelnet Independent Case Mirror & Verifier")
    parser.add_argument("--node", default=DEFAULT_NODE_URL, help="Source Aethelnet Node base URL")
    parser.add_argument("--case", default="project_echo", help="Case / investigation app_id to mirror")
    parser.add_argument("--bundle", default=None, help="Audit an existing local .json evidence bundle offline")
    parser.add_argument("--out", default=os.path.expanduser("~/.aethelnet/mirrors"), help="Output directory for mirrors")
    parser.add_argument("--no-verify", action="store_true", help="Skip on-chain Ethereum verification")
    parser.add_argument("--rpc", default=DEFAULT_RPC_URL, help="Ethereum RPC URL")
    
    args = parser.parse_args()
    if args.bundle:
        audit_bundle_file(
            bundle_path=args.bundle,
            verify=not args.no_verify,
            rpc_url=args.rpc
        )
    else:
        mirror_case(
            node_url=args.node,
            case_id=args.case,
            output_dir=args.out,
            verify=not args.no_verify,
            rpc_url=args.rpc
        )

if __name__ == "__main__":
    main()
