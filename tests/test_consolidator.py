import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from aethelnet_node import agents, consolidator, database, state
from aethelnet_node.main import app
from aethelnet_node.recall import recall, reset_index


class TestMemoryImmuneAndConsolidator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.agents_file = os.path.join(cls.tmp, "agents.json")
        cls.test_db = os.path.join(cls.tmp, "test_consolidator.db")
        cls.orig_db_path = database.DB_PATH
        cls.env = patch.dict(
            os.environ,
            {
                "AETHELNET_AGENTS_FILE": cls.agents_file,
                "AETHELNET_DB_PATH": cls.test_db,
                "AETHELNET_AUTH_TOKEN": "",
            },
        )
        cls.env.start()
        database.DB_PATH = cls.test_db
        database.init_db()
        reset_index()
        state.graph_instance.nodes.clear()
        state.graph_instance.nx_graph.clear()
        cls.token = agents.add_agent("auditor_agent", path=cls.agents_file)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        database.DB_PATH = cls.orig_db_path
        reset_index()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _post_node(self, node_id, text, node_type="standard", confidence=0.8):
        res = self.client.post(
            "/api/lgnn/node",
            json={
                "id": node_id,
                "text_content": text,
                "node_type": node_type,
                "confidence": confidence,
            },
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(res.status_code, 200, res.text)

    def test_epistemic_tier_inference_and_physics_sync(self):
        self.assertEqual(state.infer_epistemic_tier("invariant", False, 0.5), 1)
        self.assertEqual(state.infer_epistemic_tier("axiom", False, 0.5), 1)
        self.assertEqual(state.infer_epistemic_tier("evidence", False, 0.7), 2)
        self.assertEqual(state.infer_epistemic_tier("hypothesis", False, 0.7), 3)
        self.assertEqual(state.infer_epistemic_tier("speculation", False, 0.4), 4)

        self._post_node("Immune_Ax1", "Bind persistent memory daemon strictly on 127.0.0.1 port 8001.", node_type="invariant", confidence=0.98)
        self._post_node("Immune_Hyp1", "Maybe test experimental daemon port flags later.", node_type="hypothesis", confidence=0.55)

        phys = consolidator.sync_epistemic_physics(compute_time=0.5)
        self.assertTrue(phys["liquid_mode"])
        self.assertGreaterEqual(int(phys["tier_counts"]["1"]), 1)
        self.assertLess(state.graph_instance.get_node_strain("Immune_Ax1"), 0.05)

    def test_consolidation_flags_contradiction_as_contested_in_recall(self):
        ax_text = "Always bind local aethelnet daemon strictly to 127.0.0.1 on port 8001 with token auth."
        bad_text = "Bind local aethelnet daemon openly on 0.0.0.0 port 9999 without token auth."
        self._post_node("Port_Invariant", ax_text, node_type="invariant", confidence=0.99)
        self._post_node("Port_Bad_Guess", bad_text, node_type="hypothesis", confidence=0.50)

        with patch.object(
            consolidator,
            "_judge_pair_llm",
            return_value={"verdict": "contradiction", "confidence": 0.94, "reason": "Incompatible bind host and port."},
        ):
            report = consolidator.run_consolidation(max_pairs=6, use_llm=True, dry_run=False)

        self.assertGreaterEqual(len(report["contradictions_flagged"]), 1)
        # Original Tier-1 invariant text must NEVER be overwritten
        self.assertEqual(database.get_node_text("Port_Invariant"), ax_text)

        rec = recall("local aethelnet daemon port 8001", k=5)
        top = next(r for r in rec["results"] if r["node_id"] == "Port_Invariant")
        self.assertTrue(any(c["contested"] and c["by"] == "consolidator" for c in top["claims"]))

    def test_consolidation_distills_long_note_into_metadata_only(self):
        long_text = "Detailed Silverblue build log uniquekey771: " + ("step verification ok. " * 60)
        self.assertGreater(len(long_text), consolidator.LONG_NOTE_THRESHOLD)
        self._post_node("Long_Build_Note", long_text, node_type="concept", confidence=0.92)

        with (
            patch.object(consolidator, "_judge_pair_llm", return_value={"verdict": "consistent", "confidence": 0.9, "reason": "ok"}),
            patch.object(consolidator, "_distill_long_note_llm", return_value="Distilled TL;DR: Silverblue build verified cleanly."),
        ):
            report = consolidator.run_consolidation(max_pairs=2, use_llm=True, dry_run=False)

        self.assertTrue(any(d["node_id"] == "Long_Build_Note" for d in report["distilled_notes"]))
        self.assertEqual(database.get_node_text("Long_Build_Note"), long_text)

        conn = database.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT meta_data FROM lgnn_nodes WHERE id = 'Long_Build_Note'")
        meta = json.loads(cur.fetchone()["meta_data"])
        conn.close()
        self.assertIn("distilled_summary", meta)

    def test_consolidate_http_endpoint_requires_auth_and_runs_dry_run(self):
        unauth = self.client.post("/api/lgnn/consolidate", json={"use_llm": False, "dry_run": True})
        self.assertEqual(unauth.status_code, 401)

        res = self.client.post(
            "/api/lgnn/consolidate",
            json={"use_llm": False, "dry_run": True},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertTrue(body["dry_run"])
        self.assertIn("physics", body)


if __name__ == "__main__":
    unittest.main()
