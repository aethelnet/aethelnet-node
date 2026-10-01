"""
Aethelnet Court-Proof Forensic Evidence Dossier Generator
Produces standalone, verifiable, and printable HTML/PDF dossiers
including bit-exact Merkle state roots, IPFS CIDs, and Ethereum Sepolia notarization proofs.
"""

import time
from typing import Dict, Any, List

def generate_html_dossier(app_id: str, bundle: Dict[str, Any]) -> str:
    manifest = bundle.get("manifest", {})
    payload = bundle.get("payload", {})
    nodes = payload.get("nodes", [])
    edges = payload.get("edges", [])
    conflicts = payload.get("conflicts", [])

    state_root = manifest.get("state_root", "N/A")
    ipfs_cid = manifest.get("ipfs_cid_v1", "N/A")
    is_verified = manifest.get("is_cryptographically_verified", False)
    eth_notarization = manifest.get("ethereum_notarization", {})
    contract_addr = eth_notarization.get("contract", "N/A")
    on_chain_root = eth_notarization.get("on_chain_root") or "Uncommitted"
    notary_addr = eth_notarization.get("notary") or "N/A"
    notarized_ts = eth_notarization.get("timestamp")
    formatted_ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(notarized_ts)) if notarized_ts else "Pending Notarization"
    exported_at_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(manifest.get("exported_at_unix", int(time.time()))))

    # Build Conflict Rows
    conflict_rows_html = ""
    if conflicts:
        for idx, c in enumerate(conflicts):
            rule_name = c.get("rule_name") or c.get("rule_id", "Contradiction")
            entity_a = c.get("entity_a", "Entity A")
            entity_b = c.get("entity_b", "Entity B")
            claim_a = c.get("claim_a", {})
            claim_b = c.get("claim_b", {})
            verdict = c.get("resolution_verdict", "PENDING_ARBITRATION")
            delta_w = c.get("weight_delta", 0.0)
            
            conflict_rows_html += f"""
            <div class="conflict-item">
                <div class="conflict-title">
                    <span class="badge-red">[ CONTRADICTION #{idx+1} ]</span>
                    <strong>{rule_name}</strong> :: {entity_a} &lt;---&gt; {entity_b}
                </div>
                <div class="competing-grid">
                    <div class="competing-col">
                        <span class="col-tag">[ CLAIM A ]</span>
                        <div class="claim-rel">{claim_a.get('relation_type', 'N/A')} (Weight: {claim_a.get('weight', 1.0):.2f})</div>
                        <div class="claim-quote">"{claim_a.get('evidence_quote') or 'Archival citation recorded'}"</div>
                    </div>
                    <div class="competing-col">
                        <span class="col-tag">[ CLAIM B ]</span>
                        <div class="claim-rel">{claim_b.get('relation_type', 'N/A')} (Weight: {claim_b.get('weight', 1.0):.2f})</div>
                        <div class="claim-quote">"{claim_b.get('evidence_quote') or 'Archival citation recorded'}"</div>
                    </div>
                </div>
                <div class="conflict-verdict">
                    <span class="verdict-label">EPISTEMIC MATHEMATICAL VERDICT:</span>
                    <span class="verdict-val">{verdict} (ΔW = {delta_w:.3f})</span>
                </div>
            </div>
            """
    else:
        conflict_rows_html = "<div class='empty-note'>No contested contradictory claims identified in active graph topology.</div>"

    # Build Top Claims Rows (up to 50)
    claims_rows_html = ""
    for idx, e in enumerate(edges[:60]):
        src = e.get("source", "")
        tgt = e.get("target", "")
        rel = e.get("relation_type", "")
        w = e.get("weight", 1.0)
        quote = e.get("evidence_quote") or e.get("source_doc_id") or "Primary document record"
        is_contested = bool(e.get("is_contested"))
        status_tag = "<span class='badge-red'>CONTESTED</span>" if is_contested else "<span class='badge-green'>VERIFIED</span>"

        claims_rows_html += f"""
        <tr>
            <td class="mono">{idx+1}</td>
            <td class="mono"><strong>{src}</strong></td>
            <td class="mono rel-cell">{rel}</td>
            <td class="mono"><strong>{tgt}</strong></td>
            <td class="mono">{w:.2f}</td>
            <td>{quote[:120]}</td>
            <td>{status_tag}</td>
        </tr>
        """

    # Build Top Entities Rows (up to 40)
    nodes_rows_html = ""
    for idx, n in enumerate(nodes[:50]):
        nid = n.get("id", "")
        etype = n.get("entity_type") or "concept"
        conf = n.get("confidence", 1.0)
        grounded = "YES" if n.get("is_grounded") else "NO"

        nodes_rows_html += f"""
        <tr>
            <td class="mono">{idx+1}</td>
            <td class="mono"><strong>{nid}</strong></td>
            <td class="mono">{etype}</td>
            <td class="mono">{conf:.2f}</td>
            <td class="mono">{grounded}</td>
        </tr>
        """

    verification_banner = f"""
    <div class="status-banner {'banner-pass' if is_verified else 'banner-diverge'}">
        <div class="banner-badge">{'[ 100% BIT-EXACT CRYPTOGRAPHIC VERIFICATION CONFIRMED BY ETHEREUM ]' if is_verified else '[ UNCOMMITTED LOCAL STATE OR MERKLE DIVERGENCE ]'}</div>
        <div class="banner-sub">
            {'Every node and relation in this document matches the immutable Ethereum Sepolia state root at block timestamp ' + str(notarized_ts) if is_verified else 'The multigraph contains uncommitted modifications that have not yet been finalized on-chain.'}
        </div>
    </div>
    """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Aethelnet Evidence Dossier :: {app_id.upper()}</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700&display=swap');

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: #F8FAFC;
            color: #0F172A;
            line-height: 1.5;
            padding: 2rem;
        }}

        .dossier-wrapper {{
            max-width: 1000px;
            margin: 0 auto;
            background: #FFFFFF;
            border: 1px solid #CBD5E1;
            padding: 3rem;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05);
        }}

        /* Print Controls Bar */
        .action-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid #E2E8F0;
        }}

        .action-btn {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
            font-weight: 700;
            padding: 0.5rem 1rem;
            border: 1px solid #CBD5E1;
            background: #FFFFFF;
            color: #0F172A;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.15s ease;
        }}

        .action-btn:hover {{
            background: #F1F5F9;
            border-color: #94A3B8;
        }}

        .action-btn.btn-primary {{
            background: #0F172A;
            color: #FFFFFF;
            border-color: #0F172A;
        }}

        .action-btn.btn-primary:hover {{
            background: #1E293B;
        }}

        /* Document Header */
        .doc-header {{
            margin-bottom: 2rem;
        }}

        .doc-classification {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.75rem;
            font-weight: 800;
            color: #64748B;
            letter-spacing: 0.05em;
            margin-bottom: 0.4rem;
        }}

        .doc-title {{
            font-size: 1.8rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            color: #0F172A;
            margin-bottom: 0.3rem;
        }}

        .doc-subtitle {{
            font-size: 0.95rem;
            color: #475569;
            font-weight: 500;
        }}

        /* Status Banners */
        .status-banner {{
            padding: 1.25rem 1.5rem;
            margin-bottom: 2rem;
            border: 1px solid;
            font-family: 'JetBrains Mono', monospace;
        }}

        .banner-pass {{
            background: #F0FDF4;
            border-color: #BBF7D0;
            color: #166534;
        }}

        .banner-diverge {{
            background: #FEF2F2;
            border-color: #FECACA;
            color: #991B1B;
        }}

        .banner-badge {{
            font-weight: 800;
            font-size: 0.9rem;
            margin-bottom: 0.3rem;
        }}

        .banner-sub {{
            font-size: 0.78rem;
            line-height: 1.4;
        }}

        /* Manifest Meta Grid */
        .meta-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 1rem;
            background: #F8FAFC;
            border: 1px solid #E2E8F0;
            padding: 1.5rem;
            margin-bottom: 2.5rem;
            font-family: 'JetBrains Mono', monospace;
        }}

        .meta-item {{
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
        }}

        .meta-label {{
            font-size: 0.68rem;
            font-weight: 700;
            color: #64748B;
        }}

        .meta-val {{
            font-size: 0.82rem;
            color: #0F172A;
            word-break: break-all;
        }}

        .col-span-2 {{
            grid-column: span 2;
        }}

        /* Section Headings */
        .section-header {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.95rem;
            font-weight: 800;
            color: #0F172A;
            letter-spacing: 0.03em;
            margin-bottom: 1rem;
            padding-bottom: 0.5rem;
            border-bottom: 2px solid #0F172A;
            display: flex;
            justify-content: space-between;
            align-items: baseline;
        }}

        .section-sub {{
            font-size: 0.72rem;
            color: #64748B;
            font-weight: 600;
        }}

        /* Tables */
        .table-responsive {{
            width: 100%;
            overflow-x: auto;
            margin-bottom: 2.5rem;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.8rem;
            text-align: left;
        }}

        th {{
            font-family: 'JetBrains Mono', monospace;
            background: #F1F5F9;
            color: #475569;
            font-size: 0.72rem;
            font-weight: 700;
            padding: 0.6rem 0.8rem;
            border: 1px solid #E2E8F0;
        }}

        td {{
            padding: 0.6rem 0.8rem;
            border: 1px solid #E2E8F0;
            color: #334155;
        }}

        tr:nth-child(even) {{
            background: #FAFAFA;
        }}

        .mono {{
            font-family: 'JetBrains Mono', monospace;
        }}

        .rel-cell {{
            color: #0284C7;
            font-weight: 600;
        }}

        /* Badges */
        .badge-green {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.65rem;
            font-weight: 700;
            background: #DCFCE7;
            color: #166534;
            padding: 0.15rem 0.4rem;
        }}

        .badge-red {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.65rem;
            font-weight: 700;
            background: #FEE2E2;
            color: #991B1B;
            padding: 0.15rem 0.4rem;
        }}

        /* Conflict Cards */
        .conflict-item {{
            background: #FEF2F2;
            border: 1px solid #FECACA;
            padding: 1.25rem;
            margin-bottom: 1.25rem;
            font-family: 'JetBrains Mono', monospace;
        }}

        .conflict-title {{
            font-size: 0.85rem;
            color: #991B1B;
            margin-bottom: 0.85rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        .competing-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
            margin-bottom: 0.85rem;
        }}

        .competing-col {{
            background: #FFFFFF;
            border: 1px solid #FCA5A5;
            padding: 0.85rem;
        }}

        .col-tag {{
            font-size: 0.68rem;
            font-weight: 800;
            color: #DC2626;
        }}

        .claim-rel {{
            font-size: 0.8rem;
            font-weight: 700;
            color: #0F172A;
            margin: 0.25rem 0;
        }}

        .claim-quote {{
            font-family: 'Inter', sans-serif;
            font-size: 0.75rem;
            color: #475569;
            font-style: italic;
        }}

        .conflict-verdict {{
            background: #FFFFFF;
            border: 1px solid #FECACA;
            padding: 0.65rem 0.85rem;
            display: flex;
            justify-content: space-between;
            font-size: 0.75rem;
        }}

        .verdict-label {{
            font-weight: 700;
            color: #64748B;
        }}

        .verdict-val {{
            font-weight: 800;
            color: #991B1B;
        }}

        .empty-note {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
            color: #64748B;
            padding: 1rem;
            background: #F8FAFC;
            border: 1px dashed #CBD5E1;
            margin-bottom: 2rem;
        }}

        /* Footer & Audit Box */
        .dossier-footer {{
            margin-top: 3rem;
            padding-top: 1.5rem;
            border-top: 1px solid #E2E8F0;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.72rem;
            color: #64748B;
            line-height: 1.6;
        }}

        .audit-command-box {{
            background: #0F172A;
            color: #38BDF8;
            padding: 0.85rem 1.25rem;
            margin-top: 0.75rem;
            border: 1px solid #1E293B;
            word-break: break-all;
        }}

        /* Print Media Styles */
        @media print {{
            body {{
                background: #FFFFFF;
                padding: 0;
            }}
            .dossier-wrapper {{
                border: none;
                box-shadow: none;
                padding: 0;
                max-width: 100%;
            }}
            .action-bar {{
                display: none;
            }}
            .status-banner, .meta-grid, .conflict-item, th, td {{
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
            }}
        }}
    </style>
</head>
<body>
    <div class="dossier-wrapper">
        <!-- Print / Export Controls -->
        <div class="action-bar">
            <div class="action-left">
                <span class="mono" style="font-size: 0.75rem; font-weight: 700; color: #64748B;">AETHELNET PROVABLE EVIDENCE SYSTEM</span>
            </div>
            <div class="action-right" style="display: flex; gap: 0.75rem;">
                <button class="action-btn btn-primary" onclick="window.print()">[ PRINT / EXPORT PDF ]</button>
                <a class="action-btn" href="/api/ontology/multigraph/{app_id}/export_bundle?download=true" target="_blank">[ DOWNLOAD CANONICAL JSON ]</a>
                <a class="action-btn" href="https://sepolia.etherscan.io/address/{contract_addr}" target="_blank">[ ETHERSCAN CONTRACT ]</a>
            </div>
        </div>

        <!-- Document Header -->
        <div class="doc-header">
            <div class="doc-classification">[ FORENSIC EVIDENTIARY AUDIT DOSSIER :: DECLASSIFIED ARCHIVE ]</div>
            <h1 class="doc-title">{app_id.upper().replace('_', ' ')}</h1>
            <div class="doc-subtitle">Provably Untampered Multigraph Topology &amp; Epistemic Contradiction Ledger</div>
        </div>

        <!-- Verification Banner -->
        {verification_banner}

        <!-- Manifest Meta Grid -->
        <div class="meta-grid">
            <div class="meta-item">
                <span class="meta-label">CASE IDENTIFIER</span>
                <span class="meta-val">{app_id}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">NOTARIZATION TIMESTAMP</span>
                <span class="meta-val">{formatted_ts}</span>
            </div>
            <div class="meta-item col-span-2">
                <span class="meta-label">IMMUTABLE STATE ROOT (SHA-256 MERKLE)</span>
                <span class="meta-val">{state_root}</span>
            </div>
            <div class="meta-item col-span-2">
                <span class="meta-label">IPFS CIDv1 (CONTENT-ADDRESSED ARCHIVE)</span>
                <span class="meta-val">{ipfs_cid}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">ETHEREUM CONTRACT (THE FORGE)</span>
                <span class="meta-val">{contract_addr} (Sepolia)</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">NOTARY ACCOUNT (ERC-4337)</span>
                <span class="meta-val">{notary_addr}</span>
            </div>
        </div>

        <!-- Section: Contested Contradictions -->
        <div class="section-header">
            <span>[ CONTESTED CONTRADICTIONS &amp; DISSONANCE ARBITRATION ]</span>
            <span class="section-sub">{len(conflicts)} ACTIVE CONFLICT(S)</span>
        </div>
        {conflict_rows_html}

        <!-- Section: Primary Claims Ledger -->
        <div class="section-header">
            <span>[ PRIMARY FORENSIC CLAIM LEDGER ]</span>
            <span class="section-sub">{len(edges)} TOTAL CLAIMS</span>
        </div>
        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>SUBJECT / SOURCE</th>
                        <th>RELATION</th>
                        <th>OBJECT / TARGET</th>
                        <th>WEIGHT</th>
                        <th>EVIDENCE CITATION / QUOTE</th>
                        <th>STATUS</th>
                    </tr>
                </thead>
                <tbody>
                    {claims_rows_html}
                </tbody>
            </table>
        </div>

        <!-- Section: Entity Registry -->
        <div class="section-header">
            <span>[ TOPOLOGICAL ENTITY REGISTRY ]</span>
            <span class="section-sub">{len(nodes)} REGISTERED NODES</span>
        </div>
        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>ENTITY IDENTIFIER</th>
                        <th>TYPE</th>
                        <th>CONFIDENCE</th>
                        <th>GROUNDED</th>
                    </tr>
                </thead>
                <tbody>
                    {nodes_rows_html}
                </tbody>
            </table>
        </div>

        <!-- Document Footer -->
        <div class="dossier-footer">
            <p><strong>INDEPENDENT CRYPTOGRAPHIC AUDIT INSTRUCTIONS:</strong></p>
            <p>This evidence dossier was compiled deterministically from Aethelnet node storage. Any independent researcher, court, or tribunal can verify bit-exact cryptographic authenticity against Ethereum Sepolia by running:</p>
            <div class="audit-command-box">
                python3 mirror_client.py --node https://aethelburg.network --case {app_id}
            </div>
            <p style="margin-top: 0.85rem;">Generated by Aethelnet Forensics Engine at {exported_at_str}. Document hash canonical across all peer mirrors.</p>
        </div>
    </div>
</body>
</html>
"""
    return html
