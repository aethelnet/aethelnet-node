#!/usr/bin/env python3
"""
Seed script for Nexus OSINT (Financial Forensics & Offshore Networks).
Populates canonical PEPs, Nominee Directors, Shell Companies, IBAN Accounts,
and Panama Papers / FinCEN whistleblower evidence with active contradictions.
"""

import os
import sys
import json
import logging
from typing import Dict, Any

# Ensure packages/aethelnet-node is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from aethelnet_node import database
from aethelnet_node.ontology import registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Aethelnet.SeedNexus")

APP_ID = "nexus_osint"

# Canonical Entities
PERSONS = [
    {
        "id": "person_arthur_sterling",
        "label": "Lord Arthur Sterling",
        "entity_type": "person",
        "text_content": "British Politically Exposed Person (PEP), former trade envoy, and principal beneficiary of the offshore Meridian trust structure."
    },
    {
        "id": "person_klaus_richter",
        "label": "Klaus Richter",
        "entity_type": "person",
        "text_content": "Swiss professional nominee director and fiduciary agent based in Zurich. Registered officer on 42 Caribbean and Panamanian shell entities."
    },
    {
        "id": "person_elena_vasilyeva",
        "label": "Elena Vasilyeva",
        "entity_type": "person",
        "text_content": "Cyprus-based corporate services manager and registered nominee shareholder for Mediterranean transit holding entities."
    },
    {
        "id": "person_marco_bellini",
        "label": "Marco Bellini",
        "entity_type": "person",
        "text_content": "Lugano wealth manager and designated escrow signatory for cross-border private placement transfers."
    }
]

CORPORATIONS = [
    {
        "id": "corp_meridian_holdings",
        "label": "Meridian Apex Holdings Ltd",
        "entity_type": "corporation",
        "text_content": "British Virgin Islands (BVI) IBC #198204. Registered agent Trident Trust, nominee-directed conduit for $180M in undeclared assets."
    },
    {
        "id": "corp_panama_starlight",
        "label": "Starlight Global SA",
        "entity_type": "corporation",
        "text_content": "Panama Foundation #559102. Established with bearer share certificates and offshore nominee board to hold commercial real estate portfolios."
    },
    {
        "id": "corp_cyprus_albatross",
        "label": "Albatross Trade & Consulting Ltd",
        "entity_type": "corporation",
        "text_content": "Nicosia-registered conduit firm #HE381920 used for advisory fee invoicing and inter-company loan layering."
    },
    {
        "id": "corp_dubai_sovereign",
        "label": "Sovereign Horizon DMCC",
        "entity_type": "corporation",
        "text_content": "Dubai Multi Commodities Centre (DMCC) freezone trade company acting as final settlement hub for unbacked precious metal transfers."
    }
]

BANK_ACCOUNTS = [
    {
        "id": "bank_zurich_paradeplatz",
        "label": "Paradeplatz Escrow #CH93-0070-4211",
        "entity_type": "bank_account",
        "text_content": "Zurich Private Bank correspondent account utilized for high-value structured wire disbursements."
    },
    {
        "id": "bank_dubai_emirates_nbd",
        "label": "Emirates Trade Account #AE21-0260-8819",
        "entity_type": "bank_account",
        "text_content": "Dubai corporate trade settlement account flagged by UAE FIU for rapid inward-outward velocity."
    },
    {
        "id": "bank_cyprus_laiki",
        "label": "Bank of Cyprus #CY12-0020-0192",
        "entity_type": "bank_account",
        "text_content": "Nicosia corporate clearing account through which layered consultancy retainers were routed."
    }
]

CRYPTO_WALLETS = [
    {
        "id": "wallet_tornado_router",
        "label": "Tornado Cash Router (0xd90e..f31b)",
        "entity_type": "crypto_wallet",
        "text_content": "OFAC-sanctioned smart contract privacy pool utilized for on-chain fund disassociation."
    },
    {
        "id": "wallet_hyperliquid_bridge",
        "label": "Hyperliquid Cashout (0x7a25..488d)",
        "entity_type": "crypto_wallet",
        "text_content": "Decentralized L1 bridge deposit contract linked to automated stablecoin off-ramp clusters."
    }
]

DOCUMENTS = [
    {
        "id": "doc_panama_papers_deed",
        "label": "Panama Papers Deed of Trust (BVI-4091)",
        "entity_type": "document",
        "text_content": "Verbatim leaked trust deed establishing Lord Arthur Sterling as sole economic beneficiary of Meridian Apex Holdings."
    },
    {
        "id": "doc_fincen_sar_9921",
        "label": "FinCEN SAR Red Flag Filing 2024-9921",
        "entity_type": "document",
        "text_content": "Suspicious Activity Report detailing $42.5M SWIFT transfer originating from Paradeplatz Escrow without beneficial ownership disclosure."
    },
    {
        "id": "doc_notarized_affidavit",
        "label": "Geneva Notarized Affidavit of Denial",
        "entity_type": "document",
        "text_content": "Formal sworn denial submitted to regulatory authorities asserting zero ownership, control, or economic interest in Caribbean shell entities."
    }
]

# Canonical Multigraph Edges (Claims with Contradictions)
EDGES = [
    # --- CONTRADICTION 1: Control vs Denial (Lord Sterling -> Meridian Apex) ---
    {
        "edge_id": "edge_nexus_001",
        "source": "person_arthur_sterling",
        "target": "corp_meridian_holdings",
        "relation_type": "controls",
        "weight": 0.95,
        "timestamp": "2024-11-12",
        "evidence_quote": "FinCEN SAR 2024-9921 Section 3: Beneficial ownership registry leaks and bank signatory card show Lord Arthur Sterling exercised sole signing authority over Meridian Apex Holdings.",
        "source_doc_id": "doc_fincen_sar_9921"
    },
    {
        "edge_id": "edge_nexus_002",
        "source": "person_arthur_sterling",
        "target": "corp_meridian_holdings",
        "relation_type": "denies_relation",
        "weight": 0.60,
        "timestamp": "2024-12-05",
        "evidence_quote": "Sworn Notarized Affidavit (Geneva, 2024): 'I have never held, controlled, or directed Meridian Apex Holdings Ltd or any related Caribbean corporate entity at any time.'",
        "source_doc_id": "doc_notarized_affidavit"
    },

    # --- CONTRADICTION 2: Ownership vs Denial (Lord Sterling -> Starlight Global) ---
    {
        "edge_id": "edge_nexus_003",
        "source": "person_arthur_sterling",
        "target": "corp_panama_starlight",
        "relation_type": "owns",
        "weight": 0.92,
        "timestamp": "2021-04-18",
        "evidence_quote": "Panama Papers Deed of Trust BVI-4091: Nominee certificate registers 100% bearer interest held in trust for the explicit benefit of Arthur Sterling.",
        "source_doc_id": "doc_panama_papers_deed"
    },
    {
        "edge_id": "edge_nexus_004",
        "source": "person_arthur_sterling",
        "target": "corp_panama_starlight",
        "relation_type": "denies_relation",
        "weight": 0.55,
        "timestamp": "2024-12-05",
        "evidence_quote": "Public Legal Response: 'The purported trust deeds in the Panama Papers leak are fabricated or relate to an unrelated commercial third party.'",
        "source_doc_id": "doc_notarized_affidavit"
    },

    # --- CONTRADICTION 3: Control vs Denial (Klaus Richter -> Meridian Apex) ---
    {
        "edge_id": "edge_nexus_005",
        "source": "person_klaus_richter",
        "target": "corp_meridian_holdings",
        "relation_type": "controls",
        "weight": 0.70,
        "timestamp": "2024-03-15",
        "evidence_quote": "BVI Commercial Registry Extract: Klaus Richter registered as sole active Managing Director with full statutory powers.",
        "source_doc_id": "doc_fincen_sar_9921"
    },
    {
        "edge_id": "edge_nexus_006",
        "source": "person_klaus_richter",
        "target": "corp_meridian_holdings",
        "relation_type": "denies_relation",
        "weight": 0.70,
        "timestamp": "2024-10-22",
        "evidence_quote": "Swiss Federal Police Interview: 'My signature was used without authorization by corporate intermediaries; I never managed Meridian Apex.'",
        "source_doc_id": "doc_notarized_affidavit"
    },

    # --- Layering & Transaction Flows ---
    {
        "edge_id": "edge_nexus_007",
        "source": "corp_meridian_holdings",
        "target": "bank_zurich_paradeplatz",
        "relation_type": "transferred_funds",
        "weight": 0.88,
        "timestamp": "2024-08-14",
        "evidence_quote": "Wire Confirmation Ref #ZH-40912: $28,400,000 transfer from BVI corporate treasury to Zurich correspondent account.",
        "source_doc_id": "doc_fincen_sar_9921"
    },
    {
        "edge_id": "edge_nexus_008",
        "source": "bank_zurich_paradeplatz",
        "target": "corp_cyprus_albatross",
        "relation_type": "transferred_funds",
        "weight": 0.85,
        "timestamp": "2024-08-16",
        "evidence_quote": "Consultancy invoice #ALB-88: $14,200,000 disbursement for unverified maritime consulting services.",
        "source_doc_id": "doc_fincen_sar_9921"
    },
    {
        "edge_id": "edge_nexus_009",
        "source": "corp_cyprus_albatross",
        "target": "bank_cyprus_laiki",
        "relation_type": "transferred_funds",
        "weight": 0.90,
        "timestamp": "2024-08-17",
        "evidence_quote": "Domestic clearing ledger shows immediate inward receipt of $14.2M from Zurich Paradeplatz account.",
        "source_doc_id": "doc_fincen_sar_9921"
    },
    {
        "edge_id": "edge_nexus_010",
        "source": "bank_cyprus_laiki",
        "target": "corp_dubai_sovereign",
        "relation_type": "laundered_through",
        "weight": 0.82,
        "timestamp": "2024-08-20",
        "evidence_quote": "Cross-border bullion settlement: funds routed through DMCC freezone trading entity with fragmented invoicing.",
        "source_doc_id": "doc_fincen_sar_9921"
    },
    {
        "edge_id": "edge_nexus_011",
        "source": "corp_dubai_sovereign",
        "target": "bank_dubai_emirates_nbd",
        "relation_type": "transferred_funds",
        "weight": 0.91,
        "timestamp": "2024-08-22",
        "evidence_quote": "Corporate deposit slip at Emirates NBD Dubai: $12.8M cash collateral placement.",
        "source_doc_id": "doc_fincen_sar_9921"
    },
    {
        "edge_id": "edge_nexus_012",
        "source": "bank_dubai_emirates_nbd",
        "target": "wallet_tornado_router",
        "relation_type": "laundered_through",
        "weight": 0.87,
        "timestamp": "2024-09-02",
        "evidence_quote": "On-chain deposit trace: OTC desk purchased 4,200 ETH and routed directly into Tornado Cash privacy pools.",
        "source_doc_id": "doc_fincen_sar_9921"
    },
    {
        "edge_id": "edge_nexus_013",
        "source": "wallet_tornado_router",
        "target": "wallet_hyperliquid_bridge",
        "relation_type": "transferred_funds",
        "weight": 0.84,
        "timestamp": "2024-09-05",
        "evidence_quote": "Chainalysis heuristics: timing and gas price correlation matches withdrawals into Hyperliquid L1 bridge address.",
        "source_doc_id": "doc_fincen_sar_9921"
    },

    # --- Corporate Secretarial & Nominee Links ---
    {
        "edge_id": "edge_nexus_014",
        "source": "person_elena_vasilyeva",
        "target": "corp_cyprus_albatross",
        "relation_type": "controls",
        "weight": 0.89,
        "timestamp": "2022-01-10",
        "evidence_quote": "Cyprus Registrar of Companies: Elena Vasilyeva registered as sole legal representative and 100% nominal shareholder.",
        "source_doc_id": "doc_panama_papers_deed"
    },
    {
        "edge_id": "edge_nexus_015",
        "source": "person_marco_bellini",
        "target": "bank_zurich_paradeplatz",
        "relation_type": "controls",
        "weight": 0.93,
        "timestamp": "2023-06-01",
        "evidence_quote": "Bank power of attorney: Marco Bellini holds discretionary management mandate over Paradeplatz Escrow account.",
        "source_doc_id": "doc_fincen_sar_9921"
    },
    {
        "edge_id": "edge_nexus_016",
        "source": "corp_panama_starlight",
        "target": "corp_meridian_holdings",
        "relation_type": "transferred_funds",
        "weight": 0.78,
        "timestamp": "2024-05-11",
        "evidence_quote": "Inter-company debt forgiveness agreement: Starlight Global capitalized Meridian Apex with $8.5M loan credit.",
        "source_doc_id": "doc_panama_papers_deed"
    }
]

def seed_nexus_osint():
    logger.info("[*] Seeding Nexus OSINT (Financial Forensics) into Aethelnet multigraph...")

    all_entities = PERSONS + CORPORATIONS + BANK_ACCOUNTS + CRYPTO_WALLETS + DOCUMENTS

    # 1. Clear existing nexus_osint entries for a deterministic, clean slate
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM lgnn_multigraph_edges WHERE app_id = ?", (APP_ID,))
    cursor.execute("DELETE FROM lgnn_nodes WHERE app_id = ?", (APP_ID,))
    conn.commit()
    conn.close()

    conn = database.get_db_connection()
    cursor = conn.cursor()
    dummy_emb = bytes(128 * 4)

    # 2. Insert Nodes
    for ent in all_entities:
        cursor.execute("""
        INSERT INTO lgnn_nodes (
            id, embedding, text_content, mean_activation, confidence, plateau_factor,
            is_grounded, help_chain, is_archived, source_tag, is_quarantined, node_type,
            meta_data, app_id, entity_type, label, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            text_content = excluded.text_content,
            label = excluded.label,
            entity_type = excluded.entity_type,
            app_id = excluded.app_id
        """, (
            ent["id"], dummy_emb, ent["text_content"], 0.85, 0.95, 1.0,
            1, 0, 0, "nexus_curated", 0, "standard",
            json.dumps({"app_id": APP_ID, "label": ent["label"], "entity_type": ent["entity_type"]}),
            APP_ID, ent["entity_type"], ent["label"]
        ))
    conn.commit()
    conn.close()
    logger.info(f"[+] Inserted {len(all_entities)} canonical forensic entities into 'nexus_osint'.")

    # 3. Insert Multigraph Edges
    for e in EDGES:
        database.save_multigraph_edge(
            edge_id=e["edge_id"],
            app_id=APP_ID,
            source=e["source"],
            target=e["target"],
            relation_type=e["relation_type"],
            weight=e["weight"],
            timestamp=e.get("timestamp", ""),
            evidence_quote=e.get("evidence_quote", ""),
            source_doc_id=e.get("source_doc_id", "")
        )
    logger.info(f"[+] Inserted {len(EDGES)} multigraph edges into 'nexus_osint'.")

    # 4. Synchronize Conflicts
    conflicts = database.sync_conflicts_for_app(APP_ID)
    logger.info(f"[!] DETECTED {len(conflicts)} ACTIVE CONTRADICTIONS IN 'nexus_osint'!")
    for c in conflicts:
        logger.info(f"   -> [{c.get('severity', 'INFO').upper()}] {c.get('rule_name')}: {c.get('source')} vs {c.get('target')} ({c.get('verdict_code')})")

    # 5. Compute Deterministic State Root
    summary = database.compute_case_state_root(APP_ID)
    logger.info(f"[✓] Nexus OSINT State Root: {summary.get('state_root')}")
    logger.info("[✓] Seeding completed successfully.")

if __name__ == "__main__":
    seed_nexus_osint()
