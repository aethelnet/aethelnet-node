import unittest
import json
import os
import tempfile

from aethelnet_node import database
from aethelnet_node.ingest_llm import (
    compute_claim_hash,
    detect_action_events,
    ingest_and_commit_to_graph
)
from aethelnet_node.ontology import registry

class TestIdempotentIngest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Use a temporary database for test isolation
        cls.orig_db_path = database.DB_PATH
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.temp_db_path = os.path.join(cls.temp_dir.name, "test_ingest.db")
        database.DB_PATH = cls.temp_db_path
        database.init_db()

    @classmethod
    def tearDownClass(cls):
        database.DB_PATH = cls.orig_db_path
        cls.temp_dir.cleanup()

    def setUp(self):
        self.app_id = "project_echo"
        database.clear_case_multigraph(self.app_id)

    def test_deterministic_claim_hash(self):
        hash1 = compute_claim_hash(self.app_id, "doc_A", "statue_tibati", "hans_glauning", "raubte")
        hash2 = compute_claim_hash(self.app_id, "doc_A", "Statue_Tibati", "Hans_Glauning", "Raubte")
        self.assertEqual(hash1, hash2)
        self.assertTrue(hash1.startswith("claim_"))
        self.assertEqual(len(hash1), 22)  # "claim_" (6) + 16 hex chars

        # Different doc_id produces different claim hash
        hash3 = compute_claim_hash(self.app_id, "doc_B", "statue_tibati", "hans_glauning", "raubte")
        self.assertNotEqual(hash1, hash3)

    def test_detect_action_events(self):
        # 1. New contradiction detected (Deadlock triggered)
        initial = []
        new_c = [{
            "conflict_id": "test_c1",
            "rule_id": "raub_vs_schenkung",
            "source": "statue_tibati",
            "target": "hans_glauning",
            "relation_a": "raubte",
            "relation_b": "schenkte",
            "weight_a": 0.55,
            "weight_b": 0.55,
            "weight_delta": 0.0,
            "verdict": "DEADLOCK_UNCERTAIN"
        }]
        events = detect_action_events(initial, new_c, self.app_id)
        self.assertTrue(any(e["event_type"] == "DEADLOCK_TRIGGERED" for e in events))
        self.assertTrue(any(e["action_required"] == "AUDIT_PRIMARY_ARCHIVE" for e in events))

        # 2. Contradiction resolved decisive
        resolved_c = [{
            "conflict_id": "test_c1",
            "rule_id": "raub_vs_schenkung",
            "source": "statue_tibati",
            "target": "hans_glauning",
            "relation_a": "raubte",
            "relation_b": "schenkte",
            "weight_a": 0.95,
            "weight_b": 0.20,
            "weight_delta": 0.75,
            "verdict": "A_CONFIRMED"
        }]
        events_res = detect_action_events(new_c, resolved_c, self.app_id)
        self.assertTrue(any(e["event_type"] == "DEADLOCK_RESOLVED_DECISIVE" for e in events_res))
        self.assertTrue(any(e["action_required"] == "ARCHIVE_CASE_VERDICT" for e in events_res))

    def test_idempotent_ingest_pipeline(self):
        # Structured payload to test fast-path
        doc1_payload = json.dumps({
            "nodes": [
                {"id": "statue_tibati", "label": "Statue von Tibati", "entity_type": "artifact"},
                {"id": "hans_glauning", "label": "Hauptmann Hans Glauning", "entity_type": "actor"}
            ],
            "edges": [
                {
                    "source": "hans_glauning",
                    "target": "statue_tibati",
                    "relation_type": "raubte",
                    "evidence_quote": "Glauning erbeutete die Ahnenfigur nach Erstürmung der Lamidat-Festung 1901."
                }
            ]
        })

        # Ingestion 1
        res1 = ingest_and_commit_to_graph(
            text=doc1_payload,
            app_id=self.app_id,
            source_doc_id="BArch_R1001_3244"
        )
        self.assertEqual(res1["status"], "success")
        self.assertEqual(res1["edges_ingested"], 1)
        self.assertEqual(res1["edges_updated"], 0)

        # Ingestion 2 with revised quote under SAME source_doc_id
        doc1_revised = json.dumps({
            "nodes": [
                {"id": "statue_tibati", "label": "Statue von Tibati", "entity_type": "artifact"},
                {"id": "hans_glauning", "label": "Hauptmann Hans Glauning", "entity_type": "actor"}
            ],
            "edges": [
                {
                    "source": "hans_glauning",
                    "target": "statue_tibati",
                    "relation_type": "raubte",
                    "evidence_quote": "BArch R1001/3244, Blatt 14: Glauning erbeutete die Ahnenfigur nach Erstürmung."
                }
            ]
        })
        res2 = ingest_and_commit_to_graph(
            text=doc1_revised,
            app_id=self.app_id,
            source_doc_id="BArch_R1001_3244"
        )
        self.assertEqual(res2["status"], "success")
        self.assertEqual(res2["edges_ingested"], 0, "No duplicate edge should be created!")
        self.assertEqual(res2["edges_updated"], 1, "Existing edge should be updated in place!")

        # Verify edge evidence was updated in database
        edges = database.get_multigraph_edges(app_id=self.app_id)
        self.assertEqual(len(edges), 1)
        self.assertIn("Blatt 14", edges[0]["evidence_quote"])

        # Ingestion 3: Conflicting claim from museum inventory under a different source_doc_id
        doc2_conflict = json.dumps({
            "nodes": [
                {"id": "statue_tibati", "label": "Statue von Tibati", "entity_type": "artifact"},
                {"id": "hans_glauning", "label": "Hauptmann Hans Glauning", "entity_type": "actor"}
            ],
            "edges": [
                {
                    "source": "hans_glauning",
                    "target": "statue_tibati",
                    "relation_type": "schenkte",
                    "evidence_quote": "Museumsinventar 1902: Schenkung von Hauptmann Glauning an das Museum."
                }
            ]
        })
        res3 = ingest_and_commit_to_graph(
            text=doc2_conflict,
            app_id=self.app_id,
            source_doc_id="Museum_Inv_1902"
        )
        self.assertEqual(res3["status"], "success")
        self.assertEqual(res3["edges_ingested"], 1)
        self.assertGreaterEqual(res3["active_conflicts"], 1, "Conflict rule raub_vs_schenkung must be triggered!")
        self.assertGreater(len(res3["action_events"]), 0, "Action event must be emitted!")

        # Ingestion 4: Deterministic State Root calculation
        state_info = database.compute_case_state_root(self.app_id)
        self.assertTrue(state_info["state_root"].startswith("0x"))
        self.assertEqual(len(state_info["state_root"]), 66)  # "0x" + 64 hex chars
        self.assertGreaterEqual(state_info["node_count"], 2)
        self.assertEqual(state_info["edge_count"], 2)

        # Re-computing state root without changing graph yields identical root
        state_info_again = database.compute_case_state_root(self.app_id)
        self.assertEqual(state_info["state_root"], state_info_again["state_root"], "State root must be deterministic!")

if __name__ == "__main__":
    unittest.main()
