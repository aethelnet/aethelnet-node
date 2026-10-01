import re
import math
import logging
from typing import Dict, Any, List, Tuple, Optional
from collections import defaultdict

from .database import get_db_connection

logger = logging.getLogger("Aethelnet.Weights")

# Source authority heuristics based on institutional/legal credibility
PRIMARY_KEYWORDS = re.compile(
    r'\b(atlas der abwesenheit|urteil\w*|gericht\w*|grundbuch\w*|handelsregister\w*|'
    r'tagebuch\w*|kriegstagebuch\w*|bundesarchiv\w*|barch\b|national archives|geheimes staatsarchiv|'
    r'staatsarchiv\w*|zentralarchiv\w*|smb-za|dkb\b|patent\w*|europepmc|pubmed|doi\.org|'
    r'peer-review|strafexpedition\w*|amtliche akte\w*|militärexpedition\w*|'
    r'militär\w*-register)\b',
    re.IGNORECASE
)

OFFICIAL_KEYWORDS = re.compile(
    r'\b(inventarbuch\w*|inventar\w*|katalog\w*|museum\w*|übersee-museum|linden-museum|'
    r'vertrag\w*|schenkung\w*|schenkungsurkunde\w*|notar\w*|sec filing|10-k|annual report|bilanz\w*|'
    r'finanzamt\w*|registergericht\w*|schutztruppe\w*|akquisition\w*|provenienznotiz\w*)\b',
    re.IGNORECASE
)

SECONDARY_KEYWORDS = re.compile(
    r'\b(zeitung\w*|presse\w*|reuters|bloomberg|spiegel|monographie\w*|biografie\w*|'
    r'buch|artikel|investigativ\w*|bericht\w*|recherche\w*|zeitzeuge\w*)\b',
    re.IGNORECASE
)

UNVERIFIED_KEYWORDS = re.compile(
    r'\b(dementi\w*|stellungnahme\w*|pressemitteilung\w*|anonym\w*|gerücht\w*|interview\w*|'
    r'behauptung\w*|social media|tweet\w*|blog\w*|post\w*)\b',
    re.IGNORECASE
)

def evaluate_source_authority(source_doc: str) -> Tuple[float, str]:
    """
    Evaluates the institutional and epistemic authority of a source reference string.
    Returns (authority_score, tier_label).
    """
    if not source_doc or not str(source_doc).strip():
        return 0.45, "UNSPECIFIED_SOURCE"

    text = str(source_doc).lower()

    if PRIMARY_KEYWORDS.search(text):
        return 0.95, "LEVEL_1_PRIMARY_ARCHIVE"
    elif OFFICIAL_KEYWORDS.search(text):
        return 0.75, "LEVEL_2_OFFICIAL_CATALOG"
    elif SECONDARY_KEYWORDS.search(text):
        return 0.50, "LEVEL_3_SECONDARY_PRESS"
    elif UNVERIFIED_KEYWORDS.search(text):
        return 0.30, "LEVEL_4_UNVERIFIED_STATEMENT"

    # Default moderate score for named but unclassified sources
    return 0.55, "LEVEL_3_NAMED_RECORD"

def evaluate_quote_strength(evidence_quote: str) -> Tuple[float, str]:
    """
    Evaluates evidence strength based on verbatim quote presence and length.
    """
    if not evidence_quote or not str(evidence_quote).strip():
        return 0.60, "NO_DIRECT_QUOTE"

    q = str(evidence_quote).strip()
    length = len(q)

    if length >= 50:
        return 1.0, "SUBSTANTIVE_VERBATIM_QUOTE"
    elif length >= 20:
        return 0.85, "CONCISE_VERBATIM_QUOTE"
    else:
        return 0.70, "FRAGMENT_QUOTE"

def compute_edge_weight(
    source_doc: str,
    evidence_quote: str,
    corroboration_count: int = 1
) -> Tuple[float, Dict[str, Any]]:
    """
    Computes a composite epistemic edge weight in [0.10, 1.00] based on:
    1. Source authority (0.30 - 0.95)
    2. Quote strength (0.60 - 1.00)
    3. Multi-source corroboration multiplier (1.0 + 0.1 * log2(count))
    """
    auth_score, auth_tier = evaluate_source_authority(source_doc)
    quote_score, quote_tier = evaluate_quote_strength(evidence_quote)

    corrob_mult = 1.0
    if corroboration_count > 1:
        corrob_mult = 1.0 + 0.12 * math.log2(corroboration_count)

    raw_weight = auth_score * quote_score * corrob_mult
    final_weight = max(0.10, min(1.00, round(raw_weight, 3)))

    details = {
        "source_authority": auth_score,
        "source_tier": auth_tier,
        "quote_strength": quote_score,
        "quote_tier": quote_tier,
        "corroboration_count": corroboration_count,
        "corroboration_multiplier": round(corrob_mult, 3),
        "final_weight": final_weight
    }
    return final_weight, details

def recalculate_case_weights(app_id: str) -> Dict[str, Any]:
    """
    Recalculates and updates epistemic weights for all edges within an application case.
    Accounts for cross-source corroboration and document authorities.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT edge_id, source, target, relation_type, source_doc_id, evidence_quote
        FROM lgnn_multigraph_edges
        WHERE app_id = ?
    """, (app_id,))
    rows = cursor.fetchall()

    if not rows:
        conn.close()
        return {
            "app_id": app_id,
            "status": "empty",
            "edges_updated": 0,
            "metrics": {}
        }

    # Count claim corroboration: how many times does (source, target, relation) appear across distinct sources?
    claim_sources: Dict[Tuple[str, str, str], set] = defaultdict(set)
    for r in rows:
        triple = (str(r["source"]), str(r["target"]), str(r["relation_type"]).lower())
        doc_id = str(r["source_doc_id"] or "").strip()
        claim_sources[triple].add(doc_id if doc_id else r["edge_id"])

    # Compute weights and batch update
    updates: List[Tuple[float, str]] = []
    weights_list: List[float] = []
    tier_counts: Dict[str, int] = defaultdict(int)

    for r in rows:
        triple = (str(r["source"]), str(r["target"]), str(r["relation_type"]).lower())
        corrob_count = len(claim_sources[triple])

        w, details = compute_edge_weight(
            source_doc=r["source_doc_id"] or "",
            evidence_quote=r["evidence_quote"] or "",
            corroboration_count=corrob_count
        )
        updates.append((w, r["edge_id"]))
        weights_list.append(w)
        tier_counts[details["source_tier"]] += 1

    cursor.executemany("""
        UPDATE lgnn_multigraph_edges
        SET weight = ?
        WHERE edge_id = ?
    """, updates)

    conn.commit()
    conn.close()

    avg_w = round(sum(weights_list) / len(weights_list), 3) if weights_list else 0.0
    min_w = min(weights_list) if weights_list else 0.0
    max_w = max(weights_list) if weights_list else 0.0

    return {
        "app_id": app_id,
        "status": "success",
        "edges_updated": len(updates),
        "metrics": {
            "average_weight": avg_w,
            "min_weight": min_w,
            "max_weight": max_w,
            "high_confidence_edges": sum(1 for w in weights_list if w >= 0.70),
            "tier_distribution": dict(tier_counts)
        }
    }
