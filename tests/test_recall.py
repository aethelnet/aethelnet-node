import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import torch
from fastapi.testclient import TestClient

from aethelnet_node import agents, coaccess
from aethelnet_node.database import get_db_connection, init_db, save_node
from aethelnet_node.main import app
from aethelnet_node.recall import recall
from aethelnet_node.routers.mcp import HTTP_EXPOSED_TOOLS

init_db()


def _edge_weight(a, b):
    a, b = sorted((a, b))
    for x, y, w in coaccess.edges_among([a, b]):
        if (x, y) == (a, b):
            return w
    return 0.0


class TestAssociativeRecall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        path = os.path.join(cls.tmp, "agents.json")
        cls.gemini = agents.add_agent("gemini", path=path)
        cls.claude = agents.add_agent("claude", path=path)
        cls.env = patch.dict(os.environ, {"AETHELNET_AGENTS_FILE": path, "AETHELNET_AUTH_TOKEN": ""})
        cls.env.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _create(self, node_id, text, token, task=None, **extra):
        headers = {"Authorization": f"Bearer {token}"}
        if task:
            headers["X-Aethelnet-Task"] = task
        res = self.client.post("/api/lgnn/node", json={"id": node_id, "text_content": text, **extra}, headers=headers)
        self.assertEqual(res.status_code, 200, res.text)

    def test_recall_reads_the_query(self):
        self._create("Recall_Zorblax", "zorblax flux capacitor calibration procedure", self.gemini, "t-zorblax")
        self._create("Recall_Quindle", "quindle provenance ledger for the carved throne", self.gemini, "t-quindle")
        first = self.client.get("/api/lgnn/recall", params={"q": "how do I calibrate the zorblax", "k": 3}).json()
        second = self.client.get("/api/lgnn/recall", params={"q": "quindle provenance ledger", "k": 3}).json()
        self.assertEqual(first["results"][0]["node_id"], "Recall_Zorblax")
        self.assertEqual(second["results"][0]["node_id"], "Recall_Quindle")

    def test_used_together_surfaces_nodes_without_shared_words(self):
        self._create("Recall_Wobble", "wobbleflange tolerance specification", self.claude, "issue-42")
        self._create("Recall_Pumper", "pumpernickel xylograph nebula", self.claude, "issue-42")
        self.assertEqual(_edge_weight("Recall_Wobble", "Recall_Pumper"), 1.0)

        res = recall("wobbleflange tolerance", k=3)
        by_id = {r["node_id"]: r for r in res["results"]}
        self.assertEqual(res["results"][0]["node_id"], "Recall_Wobble")
        self.assertIn("Recall_Pumper", by_id, "the co-used node should be recalled through association")
        self.assertTrue(by_id["Recall_Pumper"]["via_association"])

    def test_weight_counts_distinct_tasks(self):
        self._create("Recall_C1", "first co node", self.claude, "t-one")
        self._create("Recall_C2", "second co node", self.claude, "t-one")
        self._create("Recall_C1", "first co node, edited", self.claude, "t-one")
        self.assertEqual(_edge_weight("Recall_C1", "Recall_C2"), 1.0, "same task must not inflate the weight")
        self._create("Recall_C1", "first co node again", self.gemini, "t-two")
        self._create("Recall_C2", "second co node again", self.gemini, "t-two")
        self.assertEqual(_edge_weight("Recall_C1", "Recall_C2"), 2.0)

    def test_feedback_needs_a_token_and_links_nodes(self):
        self._create("Recall_F1", "feedback node one", self.gemini, "t-f1")
        self._create("Recall_F2", "feedback node two", self.gemini, "t-f2")
        body = {"node_ids": ["Recall_F1", "Recall_F2"], "task_id": "fb-1"}
        self.assertEqual(self.client.post("/api/lgnn/recall/feedback", json=body).status_code, 401)
        res = self.client.post("/api/lgnn/recall/feedback", json=body,
                               headers={"Authorization": f"Bearer {self.claude}"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["new_links"], 1)
        self.assertEqual(_edge_weight("Recall_F1", "Recall_F2"), 1.0)

    def test_daemon_writes_are_not_learned(self):
        save_node("Recall_Sys1", torch.zeros(768), 0.0, 0.5, 0.0, False, False, text_content="system one")
        save_node("Recall_Sys2", torch.zeros(768), 0.0, 0.5, 0.0, False, False, text_content="system two")
        self.assertEqual(_edge_weight("Recall_Sys1", "Recall_Sys2"), 0.0)
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM agent_touch_log WHERE node_id IN ('Recall_Sys1', 'Recall_Sys2')")
        self.assertEqual(cur.fetchone()["n"], 0)
        conn.close()

    def test_quarantined_nodes_are_not_recalled(self):
        self._create("Recall_Glimmer", "glimmerquartz quarantined rumour", self.gemini, "t-g", is_quarantined=True)
        ids = [r["node_id"] for r in recall("glimmerquartz rumour", k=5)["results"]]
        self.assertNotIn("Recall_Glimmer", ids)

    def test_dossier_lists_claims_with_author(self):
        self._create("Recall_Snorkel", "snorkelwhit carved mask", self.claude, "t-s")
        self._create("Recall_Hall", "exhibition hall nine", self.claude, "t-s")
        res = self.client.post("/api/ontology/multigraph/edge", headers={"Authorization": f"Bearer {self.claude}"}, json={
            "edge_id": "recall_claim_1", "app_id": "recall_test", "source": "Recall_Snorkel", "target": "Recall_Hall",
            "relation_type": "verwahrt_in", "evidence_quote": "Inventory 1911, hall nine", "source_doc_id": "inv_1911"})
        self.assertEqual(res.status_code, 200)
        top = recall("snorkelwhit mask", k=3)["results"][0]
        self.assertEqual(top["node_id"], "Recall_Snorkel")
        claim = top["claims"][0]
        self.assertEqual((claim["relation"], claim["target"], claim["by"]), ("verwahrt_in", "Recall_Hall", "claude"))


class TestMcpRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        path = os.path.join(cls.tmp, "agents.json")
        cls.token = agents.add_agent("mcp-agent", path=path)
        cls.env = patch.dict(os.environ, {"AETHELNET_AGENTS_FILE": path, "AETHELNET_AUTH_TOKEN": ""})
        cls.env.start()
        cls.client = TestClient(app)
        cls.auth = {"Authorization": f"Bearer {cls.token}"}
        res = cls.client.post("/api/lgnn/node", headers=cls.auth,
                              json={"id": "Recall_Mcp_Target", "text_content": "frobnicator reset sequence for the mixer"})
        assert res.status_code == 200, res.text

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _call(self, name, arguments, headers=None):
        return self.client.post("/api/lgnn/mcp/tools/call", json={"name": name, "arguments": arguments},
                                headers=self.auth if headers is None else headers)

    def test_tool_list_only_exposes_safe_tools(self):
        names = {t["name"] for t in self.client.get("/api/lgnn/mcp/tools").json()["tools"]}
        self.assertEqual(names, HTTP_EXPOSED_TOOLS)
        self.assertNotIn("lgnn_execute_cmd", names)

    def test_tool_calls_need_a_token(self):
        self.assertEqual(self._call("lgnn_topological_recovery", {"context": "x"}, headers={}).status_code, 401)

    def test_recovery_answers_the_question(self):
        body = self._call("lgnn_topological_recovery", {"context": "how to reset the frobnicator", "k": 3}).json()
        self.assertFalse(body.get("isError"))
        self.assertIn("Recall_Mcp_Target", body["content"][0]["text"])
        self.assertEqual(body["structuredContent"]["results"][0]["node_id"], "Recall_Mcp_Target")

    def test_unsafe_tools_are_refused(self):
        body = self._call("lgnn_execute_cmd", {"command": "ls"}).json()
        self.assertTrue(body["isError"])

    def test_mark_useful(self):
        body = self._call("lgnn_mark_useful", {"node_ids": ["Recall_Mcp_Target", "Recall_Zorblax"]}).json()
        self.assertIn("Noted 2 concepts", body["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
