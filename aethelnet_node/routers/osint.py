import time
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Query

from ..ingest_llm import ingest_and_commit_to_graph

logger = logging.getLogger("Aethelnet.Node.OSINT")

router = APIRouter(prefix="/api/osint", tags=["Live OSINT Feeds"])

# Seed OSINT Intelligence Stream per Workspace
DEFAULT_SIGNALS: List[Dict[str, Any]] = [
    # --- NEXUS OSINT (Financial Forensics) ---
    {
        "id": "sig_nexus_01",
        "app_id": "nexus_osint",
        "source": "SEC EDGAR / 13-F",
        "severity": "HIGH",
        "timestamp": "2026-09-25 08:30:14 UTC",
        "title": "Offshore Shell Entity Disclosure",
        "summary": "SEC Form 13-F discloses Cayman entity 'Delta_Apex_Fund' registered to custodian nominee with $140M undeclared liabilities.",
        "triple_text": "Delta_Apex_Fund | offshore_subsidiary_of | Blackstone_Capital | SEC Form 13-F Cayman Custodian Disclosure 2026",
        "is_ingested": False
    },
    {
        "id": "sig_nexus_02",
        "app_id": "nexus_osint",
        "source": "FINCEN SAR LEAK",
        "severity": "CRITICAL",
        "timestamp": "2026-09-25 08:45:00 UTC",
        "title": "Unverified SWIFT Wire Routing",
        "summary": "Suspicious Activity Report flags $42.5M wire transfer from corp_shell_88 routed through Zurich intermediary without beneficial ownership record.",
        "triple_text": "corp_shell_88 | transfer_unverified | Zurich_Intermediary | FinCEN Red Flag SAR-88912 Zurich Wire",
        "is_ingested": False
    },
    {
        "id": "sig_nexus_03",
        "app_id": "nexus_osint",
        "source": "ICIJ OFFSHORE LEAKS",
        "severity": "HIGH",
        "timestamp": "2026-09-25 09:02:11 UTC",
        "title": "Nominee Director Network Linked to Shell",
        "summary": "Leaked corporate register confirms Klaus Richter acted as sole director for 14 shell companies including holding_live_test.",
        "triple_text": "Klaus_Richter | director_of | holding_live_test | ICIJ Offshore Leaks Dossier BVI-9912",
        "is_ingested": False
    },

    # --- BIOCHEM VARIANTS (Precision Oncology) ---
    {
        "id": "sig_biochem_01",
        "app_id": "biochem_variants",
        "source": "CLINVAR SUBMISSION REPOSITORY",
        "severity": "CRITICAL",
        "timestamp": "2026-09-25 08:12:00 UTC",
        "title": "Discordant Pathogenicity Classification: TP53 p.Ile251Thr",
        "summary": "Ambry Genetics classifies TP53 p.Ile251Thr as Pathogenic (Li-Fraumeni syndrome), whereas Invitae submitted Benign / Likely Benign based on population allele frequency.",
        "triple_text": "var_TP53_I251T | drives_pathogenicity | pheno_li_fraumeni | ClinVar SCV000189211.4 (Ambry Genetics 2024)",
        "is_ingested": False
    },
    {
        "id": "sig_biochem_02",
        "app_id": "biochem_variants",
        "source": "PUBMED FUNCTIONAL ASSAY",
        "severity": "HIGH",
        "timestamp": "2026-09-25 08:35:45 UTC",
        "title": "BRCA1 BRCT Transactivation Dissonance",
        "summary": "Saturation genome editing assay (Findlay et al., Nature) reports normal transactivation for BRCA1 p.Tyr465His, disputing clinical VUS/Pathogenic call.",
        "triple_text": "var_BRCA1_Y465H | refutes_pathogenicity | pheno_hboc | Nature Saturation Genome Editing Assay (Findlay et al. PMID 30209392)",
        "is_ingested": False
    },
    {
        "id": "sig_biochem_03",
        "app_id": "biochem_variants",
        "source": "ALPHAFOLD CORE STABILITY METRICS",
        "severity": "CRITICAL",
        "timestamp": "2026-09-25 09:05:20 UTC",
        "title": "Severe Thermodynamic Core Destabilization: ΔΔG +4.2 kcal/mol",
        "summary": "FoldX and AlphaFold pLDDT analysis on AF-P04637 predicts structural collapse in DNA-binding domain core due to steric clash of bulkier isoleucine.",
        "triple_text": "var_TP53_I251T | destabilizes_core | domain_TP53_DBD | AlphaFold v2.3 Structural Relaxation & FoldX ΔΔG=4.2 kcal/mol",
        "is_ingested": False
    },

    # --- PROJECT ECHO (Colonial Restitution) ---
    {
        "id": "sig_echo_01",
        "app_id": "project_echo",
        "source": "COLONIAL ARCHIVE BERLIN",
        "severity": "CRITICAL",
        "timestamp": "2026-09-25 08:15:30 UTC",
        "title": "Military Confiscation Ledger Bamum 1902",
        "summary": "Archival dispatch confirms Hauptmann Hans Glauning entered Foumban with military force in May 1902 and seized the royal Mandu Yenu throne as war spoils.",
        "triple_text": "Hans_Glauning | raubte | Mandu_Yenu_Thron | Militärbericht Hauptmann Glauning Bamum 1902",
        "is_ingested": False
    },
    {
        "id": "sig_echo_02",
        "app_id": "project_echo",
        "source": "ROYAL PALACE FOUMBAN",
        "severity": "HIGH",
        "timestamp": "2026-09-25 08:50:12 UTC",
        "title": "Royal Restitution Petition 2026",
        "summary": "Sultan Nabil Njoya of the Bamum Kingdom submits diplomatic memorandum demanding restitution of royal ancestral regalia held in Berlin.",
        "triple_text": "Sultan_Nabil_Njoya | fordert_rueckgabe | Mandu_Yenu_Thron | Offizielles Restitutionsgesuch Foumban 2026",
        "is_ingested": False
    },

    # --- BLANK INVESTIGATION ---
    {
        "id": "sig_blank_01",
        "app_id": "blank_investigation",
        "source": "ENCRYPTED SIGNAL DROP",
        "severity": "HIGH",
        "timestamp": "2026-09-25 09:10:00 UTC",
        "title": "Anonymous Whistleblower Ledger",
        "summary": "Decrypted spreadsheet identifies undisclosed consulting agreements between Defense Contractor X and Procurement Committee Director.",
        "triple_text": "Defense_Contractor_X | paid_kickback_to | Procurement_Director | Encrypted Whistleblower Drop #441",
        "is_ingested": False
    }
]

# In-memory signal store
LIVE_SIGNALS: List[Dict[str, Any]] = list(DEFAULT_SIGNALS)

class PublishSignalRequest(BaseModel):
    app_id: str
    source: str
    severity: str = "HIGH"
    title: str
    summary: str
    triple_text: str

@router.get("/signals")
def get_osint_signals(
    app_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100)
):
    """
    Returns real-time OSINT intelligence signals for an investigative case.
    """
    signals = LIVE_SIGNALS
    if app_id:
        signals = [s for s in signals if s.get("app_id") == app_id]
    
    # Return most recent first
    return {
        "status": "success",
        "count": len(signals[:limit]),
        "signals": signals[:limit]
    }

@router.post("/publish")
def publish_signal(req: PublishSignalRequest):
    """
    Publishes an intelligence signal into the live stream from automated spiders or feeds.
    """
    new_sig = {
        "id": f"sig_{int(time.time())}_{len(LIVE_SIGNALS)}",
        "app_id": req.app_id,
        "source": req.source,
        "severity": req.severity.upper(),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "title": req.title,
        "summary": req.summary,
        "triple_text": req.triple_text,
        "is_ingested": False
    }
    LIVE_SIGNALS.insert(0, new_sig)
    logger.info(f"[OSINT] New signal published: {new_sig['id']} ({new_sig['title']})")
    return {"status": "published", "signal": new_sig}

@router.post("/ingest_signal/{signal_id}")
def ingest_signal_api(signal_id: str):
    """
    One-click instant evidentiary ingestion:
    Extracts the structured triple from an OSINT signal and commits it to the case multigraph
    in <30ms using the Fast Heuristic Engine.
    """
    target_sig = next((s for s in LIVE_SIGNALS if s.get("id") == signal_id), None)
    if not target_sig:
        raise HTTPException(status_code=404, detail=f"Signal '{signal_id}' not found.")

    app_id = target_sig.get("app_id", "nexus_osint")
    triple_text = target_sig.get("triple_text", "")
    if not triple_text:
        raise HTTPException(status_code=400, detail="Signal contains no structured triple.")

    result = ingest_and_commit_to_graph(
        text=triple_text,
        app_id=app_id,
        source_doc_id=target_sig["id"],
        auto_dedup=False,
        mode="heuristic"
    )

    target_sig["is_ingested"] = True
    logger.info(f"[OSINT] Signal '{signal_id}' ingested into '{app_id}'. Ingested nodes: {result.get('nodes_ingested')}")
    
    return {
        "status": "success",
        "signal_id": signal_id,
        "ingest_result": result,
        "new_node_ids": result.get("new_node_ids", [])
    }


class DispatchScoutRequest(BaseModel):
    app_id: str = "solana_whales"
    mission_prompt: str
    connector: str = "solana_onchain"
    limit: int = 5
    auto_commit: bool = False
    custom_url: Optional[str] = None


@router.get("/connectors")
def list_connectors_api():
    """Returns available modular scout connectors."""
    return {
        "status": "success",
        "connectors": [
            {
                "id": "solana_onchain",
                "name": "Solana On-Chain Whale & MEV Scout",
                "description": "High-throughput on-chain SOL transfers, CEX deposit routing, Jito MEV block-0 sniping, and pool drains.",
                "supported_apps": ["solana_whales", "nexus_osint"]
            },
            {
                "id": "clinvar_pubchem",
                "name": "ClinVar & PubMed Genomic Variant Scout",
                "description": "Cross-references ClinVar ACMG variant interpretations, PubMed functional assays, and AlphaFold stability predictions.",
                "supported_apps": ["biochem_variants", "nexus_osint"]
            },
            {
                "id": "archival_leak",
                "name": "Archival Records & Whistleblower Leaks",
                "description": "Primary colonial records (BArch R1001), corporate registry leaks, and SEC/FinCEN filings.",
                "supported_apps": ["project_echo", "nexus_osint"]
            },
            {
                "id": "arxiv_academic",
                "name": "arXiv Academic & Research Preprint Scout",
                "description": "Searches arXiv API for preprint abstracts, methodologies, and institutional authors.",
                "supported_apps": ["general", "nexus_osint"]
            },
            {
                "id": "custom_feed",
                "name": "Custom Webhook / WebSocket / JSON Stream",
                "description": "Connects to any external REST API or WebSocket feed to ingest streaming signals.",
                "supported_apps": ["*"]
            }
        ]
    }


@router.post("/dispatch_scout")
def dispatch_scout_api(req: DispatchScoutRequest):
    """
    Launches an autonomous OSINT scout mission across the specified connector.
    Discovered signals are broadcast to the live ticker and optionally auto-committed to the multigraph.
    """
    try:
        from ..scout_dispatcher import dispatch_scout_mission
    except ImportError:
        from aethelnet_node.scout_dispatcher import dispatch_scout_mission

    result = dispatch_scout_mission(
        app_id=req.app_id,
        mission_prompt=req.mission_prompt,
        connector=req.connector,
        limit=req.limit,
        auto_commit=req.auto_commit,
        custom_url=req.custom_url
    )
    return result

