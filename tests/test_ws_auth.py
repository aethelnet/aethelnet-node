import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from aethelnet_node.database import init_db
from aethelnet_node.main import app, graph_instance

init_db()

TOKEN = "ws-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _recv_until(ws, types, limit=10):
    """The telemetry socket interleaves replies with telemetry frames; read until one of `types`."""
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("type") in types:
            return msg
    raise AssertionError(f"none of {types} received")


class TestTelemetrySocketAuth(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"AETHELNET_AUTH_TOKEN": TOKEN, "AETHELNET_PEER_TOKEN": ""})
        self.env.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.env.stop()

    def _make_node(self, node_id):
        res = self.client.post("/api/lgnn/node", json={"id": node_id, "text_content": "ws auth test"}, headers=AUTH)
        self.assertEqual(res.status_code, 200)
        self.assertIsNotNone(graph_instance.get_node_embedding(node_id))

    def test_delete_requires_auth(self):
        self._make_node("WsAuth_Victim")
        with self.client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "delete_nodes", "nodes": ["WsAuth_Victim"]})
            self.assertEqual(_recv_until(ws, {"ERROR"})["type"], "ERROR")
            _recv_until(ws, {"telemetry"})
        self.assertIsNotNone(graph_instance.get_node_embedding("WsAuth_Victim"))

    def test_fork_reality_cannot_wipe_graph_unauthenticated(self):
        self._make_node("WsAuth_Survivor")
        before = len(graph_instance.nodes)
        with self.client.websocket_connect("/api/lgnn/ws") as ws:
            ws.send_json({"type": "fork_reality", "timestamp": 0, "nodes": []})
            _recv_until(ws, {"ERROR"})
        self.assertIsNotNone(graph_instance.get_node_embedding("WsAuth_Survivor"))
        self.assertGreaterEqual(len(graph_instance.nodes), before - 1)  # only the viewport node goes away

    def test_wrong_token_is_rejected(self):
        with self.client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "AUTH", "token": "nope"})
            self.assertEqual(_recv_until(ws, {"AUTH_OK", "AUTH_FAILED"})["type"], "AUTH_FAILED")

    def test_auth_message_unlocks_mutations(self):
        self._make_node("WsAuth_Deletable")
        with self.client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "AUTH", "token": TOKEN})
            self.assertEqual(_recv_until(ws, {"AUTH_OK", "AUTH_FAILED"})["type"], "AUTH_OK")
            ws.send_json({"type": "delete_nodes", "nodes": ["WsAuth_Deletable"]})
            _recv_until(ws, {"telemetry"})
        self.assertIsNone(graph_instance.get_node_embedding("WsAuth_Deletable"))

    def test_query_token_unlocks_mutations(self):
        with self.client.websocket_connect(f"/ws?token={TOKEN}") as ws:
            ws.send_json({"type": "update_params", "decay_rate": 0.051})
            _recv_until(ws, {"telemetry"})
        self.assertAlmostEqual(graph_instance.decay_rate, 0.051)

    def test_client_id_cannot_hijack_existing_node(self):
        self._make_node("WsAuth_Existing")
        original = graph_instance.get_node_embedding("WsAuth_Existing").clone()
        with self.client.websocket_connect("/api/lgnn/ws/WsAuth_Existing") as ws:
            _recv_until(ws, {"telemetry"})
        after = graph_instance.get_node_embedding("WsAuth_Existing")
        self.assertIsNotNone(after, "disconnect must not remove a real node")
        self.assertTrue(bool((after == original).all()), "connect must not overwrite a real node")

    def test_viewport_node_is_removed_on_disconnect(self):
        with self.client.websocket_connect("/api/lgnn/ws/WsAuth_Viewport_1") as ws:
            _recv_until(ws, {"telemetry"})
            self.assertIsNotNone(graph_instance.get_node_embedding("WsAuth_Viewport_1"))
        self.assertIsNone(graph_instance.get_node_embedding("WsAuth_Viewport_1"))


class TestLocalDevWithoutToken(unittest.TestCase):
    def test_localhost_may_mutate_when_no_token_is_set(self):
        with patch.dict(os.environ, {"AETHELNET_AUTH_TOKEN": ""}):
            with TestClient(app).websocket_connect("/ws") as ws:
                ws.send_json({"type": "AUTH"})
                self.assertEqual(_recv_until(ws, {"AUTH_OK", "AUTH_FAILED"})["type"], "AUTH_OK")


class TestPeerSocketAuth(unittest.TestCase):
    def test_peer_token_required_when_set(self):
        with patch.dict(os.environ, {"AETHELNET_PEER_TOKEN": "mesh-secret"}):
            client = TestClient(app)
            with client.websocket_connect("/p2p/ws") as ws:
                ws.send_text('{"type": "resonance_wave", "node": "WsAuth_PeerNode", "text": "hello"}')
                self.assertEqual(ws.receive_json()["type"], "ERROR")
            self.assertIsNone(graph_instance.get_node_embedding("WsAuth_PeerNode"))

            with client.websocket_connect("/p2p/ws?token=mesh-secret") as ws:
                ws.send_text('{"type": "resonance_wave", "node": "WsAuth_PeerNode", "text": "hello"}')
                ws.send_text('{"type": "AUTH", "token": "mesh-secret"}')
                self.assertEqual(ws.receive_json()["type"], "AUTH_OK")  # wave processed before this reply
            self.assertIsNotNone(graph_instance.get_node_embedding("WsAuth_PeerNode"))

    def test_peer_cannot_overwrite_existing_node(self):
        with patch.dict(os.environ, {"AETHELNET_PEER_TOKEN": "", "AETHELNET_AUTH_TOKEN": TOKEN}):
            client = TestClient(app)
            client.post("/api/lgnn/node", json={"id": "WsAuth_Local", "text_content": "local"}, headers=AUTH)
            original = graph_instance.get_node_embedding("WsAuth_Local").clone()
            with client.websocket_connect("/p2p/ws") as ws:
                ws.send_text('{"type": "resonance_wave", "node": "WsAuth_Local", "text": "overwritten by a peer"}')
                ws.send_text('{"type": "AUTH"}')
                ws.receive_json()
            self.assertTrue(bool((graph_instance.get_node_embedding("WsAuth_Local") == original).all()))


if __name__ == "__main__":
    unittest.main()
