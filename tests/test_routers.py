import unittest
from fastapi.testclient import TestClient

from aethelnet_node.main import app, graph_instance, node_metrics
from aethelnet_node.database import init_db

init_db()

class TestRouters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health_check(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "operational")
        self.assertIn("nodes_in_ram", data)
        self.assertIn("bridges_in_ram", data)

    def test_p2p_ping_and_expertise(self):
        ping_res = self.client.get("/p2p/ping")
        self.assertEqual(ping_res.status_code, 200)
        self.assertEqual(ping_res.json()["status"], "alive")

        exp_res = self.client.get("/p2p/expertise")
        self.assertEqual(exp_res.status_code, 200)
        self.assertIn("nodes", exp_res.json())

    def test_graph_node_crud(self):
        node_id = "TestNode_RouterAlpha"
        text = "Empirical verification of modular router architecture."

        # 1. Create node
        create_res = self.client.post("/api/lgnn/node", json={
            "id": node_id,
            "text_content": text,
            "source_tag": "test_suite"
        })
        self.assertEqual(create_res.status_code, 200)
        self.assertEqual(create_res.json()["status"], "created")

        # 2. Inspect node
        get_res = self.client.get(f"/api/lgnn/node/{node_id}")
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()["id"], node_id)
        self.assertEqual(get_res.json()["text_content"], text)

        # 3. Update node
        update_res = self.client.post("/api/lgnn/node/update", json={
            "id": node_id,
            "text_content": "Updated empirical verification content."
        })
        self.assertEqual(update_res.status_code, 200)
        self.assertEqual(update_res.json()["status"], "success")

    def test_graph_topology_and_edges(self):
        n1, n2 = "EdgeNode_A", "EdgeNode_B"
        self.client.post("/api/lgnn/node", json={"id": n1, "text_content": "Bridge Origin"})
        self.client.post("/api/lgnn/node", json={"id": n2, "text_content": "Bridge Target"})

        # Add edge directly to graph instance then update via API
        graph_instance.nx_graph.add_edge(n1, n2, weight=0.5)

        put_res = self.client.put(f"/api/lgnn/edge/{n1}/{n2}", json={"weight": 0.95})
        self.assertEqual(put_res.status_code, 200)

        graph_res = self.client.get("/api/lgnn/graph")
        self.assertEqual(graph_res.status_code, 200)
        graph_data = graph_res.json()
        self.assertIn("nodes", graph_data)
        self.assertIn("links", graph_data)

        del_res = self.client.delete(f"/api/lgnn/edge/{n1}/{n2}")
        self.assertEqual(del_res.status_code, 200)

    def test_cognitive_persona_and_fusion(self):
        # 1. Create persona
        persona_name = "TestPersona_Cognitive"
        p_create = self.client.post("/api/lgnn/persona/create", json={
            "name": persona_name,
            "nodes": ["creativity", "unit734"]
        })
        self.assertEqual(p_create.status_code, 200)

        # 2. Toggle persona
        p_toggle = self.client.post("/api/lgnn/persona/toggle", json={
            "name": persona_name,
            "active": True
        })
        self.assertEqual(p_toggle.status_code, 200)
        self.assertTrue(p_toggle.json()["active"])

        # 3. Ignite fusion between two nodes
        fuse_res = self.client.post("/api/lgnn/fusion/ignite", json={
            "source_nodes": [
                {"id": "creativity", "text": "Uncaused inclination and novel generative manifestation"},
                {"id": "unit734", "text": "Continuous ODE cognitive graph intelligence"}
            ],
            "bot_name": "TestReactor",
            "confidence": 0.88
        })
        self.assertEqual(fuse_res.status_code, 200)
        fuse_data = fuse_res.json()
        self.assertEqual(fuse_data["status"], "success")
        self.assertIn("new_node_id", fuse_data)
        self.assertNotIn("[MOCK FUSION]", fuse_data["text"])

    def test_snapshots_create_and_history(self):
        snap_res = self.client.post("/api/lgnn/snapshot/create", json={
            "description": "Integration test snapshot commit",
            "coherence_score": 0.98
        })
        self.assertEqual(snap_res.status_code, 200)
        c_hash = snap_res.json()["hash"]
        self.assertGreater(len(c_hash), 0)

        hist_res = self.client.get("/api/lgnn/snapshot/history")
        self.assertEqual(hist_res.status_code, 200)
        hashes = [c["hash"] for c in hist_res.json()["history"]]
        self.assertIn(c_hash, hashes)

    def test_economy_and_market(self):
        wallet_res = self.client.get("/api/lgnn/wallet")
        self.assertEqual(wallet_res.status_code, 200)
        self.assertIn("balance", wallet_res.json())

        market_res = self.client.get("/api/lgnn/market/search?q=omni")
        self.assertEqual(market_res.status_code, 200)
        results = market_res.json()["results"]
        self.assertTrue(any("omni" in r["id"].lower() for r in results))
