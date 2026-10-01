import os
import json
import logging
from typing import Dict, List, Optional, Any
from .schema import AppOntology, EntityType, RelationType, ConflictRule

logger = logging.getLogger("Aethelnet.Ontology")

class OntologyRegistry:
    """
    Central registry for dynamic workspace ontologies in Aethelnet.
    Manages schemas for Project Echo, Nexus OSINT, Aura Audio, and user-defined domains.
    """
    def __init__(self, schemas_dir: Optional[str] = None):
        if schemas_dir is None:
            schemas_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemas")
        self.schemas_dir = schemas_dir
        self._schemas: Dict[str, AppOntology] = {}
        self.reload()

    def reload(self):
        """Scans the schemas directory and loads all valid AppOntology JSON files."""
        self._schemas.clear()
        if not os.path.exists(self.schemas_dir):
            os.makedirs(self.schemas_dir, exist_ok=True)
            return

        for filename in sorted(os.listdir(self.schemas_dir)):
            if filename.endswith(".json"):
                filepath = os.path.join(self.schemas_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    ontology = AppOntology.model_validate(data)
                    self._schemas[ontology.app_id] = ontology
                    logger.info(f"Loaded workspace ontology '{ontology.app_id}' v{ontology.version} ({len(ontology.entities)} entities, {len(ontology.relations)} relations)")
                except Exception as e:
                    logger.error(f"Failed to load ontology from {filepath}: {e}")

    def get_schema(self, app_id: str) -> Optional[AppOntology]:
        """Returns the AppOntology for a given app_id, or None if not found."""
        return self._schemas.get(app_id)

    def list_schemas(self) -> List[Dict[str, Any]]:
        """Returns a summary list of all registered workspace ontologies."""
        return [
            {
                "app_id": ont.app_id,
                "name": ont.name,
                "version": ont.version,
                "domain": ont.domain,
                "description": ont.description,
                "icon": ont.icon,
                "default_view": ont.default_view,
                "entity_count": len(ont.entities),
                "relation_count": len(ont.relations),
                "conflict_rule_count": len(ont.conflict_rules),
            }
            for ont in self._schemas.values()
        ]

    def register_schema(self, ontology: AppOntology) -> bool:
        """Registers a runtime schema and persists it to disk."""
        self._schemas[ontology.app_id] = ontology
        filepath = os.path.join(self.schemas_dir, f"{ontology.app_id}.json")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(ontology.model_dump_json(indent=2))
            return True
        except Exception as e:
            logger.error(f"Failed to persist ontology {ontology.app_id}: {e}")
            return False

    def delete_schema(self, app_id: str) -> bool:
        """Deletes a runtime schema from memory and disk."""
        if app_id in self._schemas:
            del self._schemas[app_id]
        filepath = os.path.join(self.schemas_dir, f"{app_id}.json")
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                return True
            except Exception as e:
                logger.error(f"Failed to delete ontology schema file {filepath}: {e}")
                return False
        return True

    def detect_conflicts(self, app_id: str, edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Analyzes a list of edges against the conflict rules of the target ontology.
        Returns a list of detected conflicts (dissonance pairs).
        Each edge dict must have 'source', 'target', and 'relation_type'.
        """
        schema = self.get_schema(app_id)
        if not schema or not schema.conflict_rules:
            return []

        # Group edges by symmetric node pair to catch both directional variations
        pair_map: Dict[tuple, List[Dict[str, Any]]] = {}
        for edge in edges:
            src = edge.get("source")
            tgt = edge.get("target")
            if not src or not tgt:
                continue
            pair = tuple(sorted([src, tgt]))
            pair_map.setdefault(pair, []).append(edge)

        conflicts = []
        for rule in schema.conflict_rules:
            conflicting_set = set(rule.conflicting_relations)
            for pair, pair_edges in pair_map.items():
                found_relations = {e.get("relation_type") for e in pair_edges if e.get("relation_type")}
                intersection = found_relations.intersection(conflicting_set)
                # If two or more conflicting relations exist between the entities
                if len(intersection) >= 2:
                    conflicting_edge_objs = [e for e in pair_edges if e.get("relation_type") in intersection]

                    # Epistemic Weight Resolution: compare evidence weights of competing claims
                    conflicting_edge_objs.sort(key=lambda e: float(e.get("weight") or 0.5), reverse=True)
                    dom_edge = conflicting_edge_objs[0]
                    sub_edge = conflicting_edge_objs[1]
                    w_dom = float(dom_edge.get("weight") or 0.5)
                    w_sub = float(sub_edge.get("weight") or 0.5)
                    weight_delta = round(w_dom - w_sub, 3)

                    if weight_delta >= 0.15:
                        verdict_code = "DECISIVE"
                        verdict = f"'{dom_edge.get('relation_type', '').upper()}' (Weight {w_dom:.2f}) decisively outweighs '{sub_edge.get('relation_type', '').upper()}' (Weight {w_sub:.2f}) by +{weight_delta:.2f}."
                    elif weight_delta > 0.04:
                        verdict_code = "MODERATE"
                        verdict = f"'{dom_edge.get('relation_type', '').upper()}' (Weight {w_dom:.2f}) moderately leads over '{sub_edge.get('relation_type', '').upper()}' (Weight {w_sub:.2f}) by +{weight_delta:.2f}."
                    else:
                        verdict_code = "DEADLOCK"
                        verdict = f"Deadlock: Competing claims have nearly identical weights ({w_dom:.2f} vs {w_sub:.2f}). Additional primary source required."

                    conflicts.append({
                        "rule_id": rule.rule_id,
                        "rule_name": rule.name,
                        "severity": rule.severity,
                        "description": rule.description,
                        "source": pair[0],
                        "target": pair[1],
                        "conflicting_relations": list(intersection),
                        "dominant_relation": dom_edge.get("relation_type"),
                        "subordinate_relation": sub_edge.get("relation_type"),
                        "weight_delta": weight_delta,
                        "verdict_code": verdict_code,
                        "verdict": verdict,
                        "edges": conflicting_edge_objs
                    })

        return conflicts

# Global singleton
registry = OntologyRegistry()
