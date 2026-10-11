import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from aethelnet_node import agents
from aethelnet_node.database import get_db_connection, init_db
from aethelnet_node.main import app

init_db()


def _provenance(table, key_column, key):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT created_by, updated_by FROM {table} WHERE {key_column} = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return (row["created_by"], row["updated_by"]) if row else None


class TestAgentRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "agents.json")
        self.env = patch.dict(os.environ, {"AETHELNET_AGENTS_FILE": self.path, "AETHELNET_AUTH_TOKEN": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_only_the_hash_is_stored(self):
        token = agents.add_agent("gemini", description="editor agent")
        with open(self.path, encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn(token, raw)
        self.assertEqual(json.loads(raw)["agents"]["gemini"]["token_sha256"], agents.hash_token(token))

    def test_resolve_rotate_revoke(self):
        token = agents.add_agent("gemini")
        self.assertEqual(agents.resolve_token(token).agent_id, "gemini")
        self.assertIsNone(agents.resolve_token("not-a-token"))

        new_token = agents.rotate_agent("gemini")
        self.assertIsNone(agents.resolve_token(token), "old token must stop working")
        self.assertEqual(agents.resolve_token(new_token).agent_id, "gemini")

        agents.revoke_agent("gemini")
        self.assertIsNone(agents.resolve_token(new_token))
        self.assertFalse(agents.has_registered_agents())

    def test_invalid_reserved_and_duplicate_ids(self):
        for bad in ("operator", "local", "system", "Has Spaces", "UPPER", ""):
            with self.assertRaises(ValueError, msg=bad):
                agents.add_agent(bad)
        agents.add_agent("claude")
        with self.assertRaises(ValueError):
            agents.add_agent("claude")

    def test_legacy_operator_token(self):
        with patch.dict(os.environ, {"AETHELNET_AUTH_TOKEN": "legacy-op"}):
            identity = agents.resolve_token("legacy-op")
        self.assertEqual((identity.agent_id, identity.role), ("operator", "operator"))

    def test_cli_shows_token_once_and_never_lists_secrets(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(agents.main(["--file", self.path, "add", "claude", "--description", "fork PRs"]), 0)
        token = out.getvalue().strip().splitlines()[-1]
        self.assertEqual(agents.resolve_token(token).agent_id, "claude")

        listing = io.StringIO()
        with contextlib.redirect_stdout(listing):
            agents.main(["--file", self.path, "list"])
        self.assertIn("claude", listing.getvalue())
        self.assertNotIn(token, listing.getvalue())
        self.assertNotIn(agents.hash_token(token), listing.getvalue())


class TestAgentProvenance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        path = os.path.join(cls.tmp, "agents.json")
        cls.gemini = agents.add_agent("gemini", path=path)
        cls.claude = agents.add_agent("claude", path=path)
        cls.env = patch.dict(os.environ, {"AETHELNET_AGENTS_FILE": path, "AETHELNET_AUTH_TOKEN": "",
                                          "AETHELNET_PEER_TOKEN": ""})
        cls.env.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_registered_agents_make_writes_require_a_token(self):
        res = self.client.post("/api/lgnn/node", json={"id": "Prov_NoToken", "text_content": "x"})
        self.assertEqual(res.status_code, 401)
        res = self.client.post("/api/lgnn/node", json={"id": "Prov_NoToken", "text_content": "x"},
                               headers=self._auth("forged"))
        self.assertEqual(res.status_code, 401)

    def test_node_created_by_and_updated_by(self):
        res = self.client.post("/api/lgnn/node", json={"id": "Prov_Node_1", "text_content": "first"},
                               headers=self._auth(self.gemini))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(_provenance("lgnn_nodes", "id", "Prov_Node_1"), ("gemini", "gemini"))

        res = self.client.post("/api/lgnn/node", json={"id": "Prov_Node_1", "text_content": "second"},
                               headers=self._auth(self.claude))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(_provenance("lgnn_nodes", "id", "Prov_Node_1"), ("gemini", "claude"))

    def test_claims_carry_their_author(self):
        for node_id in ("Prov_Mine", "Prov_Museum"):
            self.client.post("/api/lgnn/node", json={"id": node_id, "text_content": node_id},
                             headers=self._auth(self.gemini))
        res = self.client.post("/api/ontology/multigraph/edge", headers=self._auth(self.claude), json={
            "edge_id": "prov_claim_1", "app_id": "prov_test", "source": "Prov_Mine", "target": "Prov_Museum",
            "relation_type": "verwahrt_in", "evidence_quote": "Inventory entry 1908", "source_doc_id": "doc_1"
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(_provenance("lgnn_multigraph_edges", "edge_id", "prov_claim_1"), ("claude", "claude"))

    def test_audit_log_and_agent_listing(self):
        self.client.post("/api/lgnn/node", json={"id": "Prov_Audit", "text_content": "x"},
                         headers=self._auth(self.claude))
        listing = self.client.get("/api/agents").json()["agents"]
        by_id = {a["agent_id"]: a for a in listing}
        self.assertIn("claude", by_id)
        self.assertTrue(by_id["claude"]["registered"])
        self.assertGreaterEqual(by_id["claude"]["writes"], 1)
        self.assertNotIn("token_sha256", json.dumps(listing))

    def test_whoami(self):
        me = self.client.get("/api/agents/whoami", headers=self._auth(self.gemini)).json()
        self.assertEqual((me["agent_id"], me["authenticated"], me["auth_required_for_writes"]), ("gemini", True, True))
        anon = self.client.get("/api/agents/whoami").json()
        self.assertEqual((anon["agent_id"], anon["writes_attributed_to"]), (None, None))

    def test_websocket_session_carries_agent(self):
        with self.client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "AUTH", "token": self.claude})
            for _ in range(10):
                msg = ws.receive_json()
                if msg.get("type") in ("AUTH_OK", "AUTH_FAILED"):
                    break
        self.assertEqual((msg["type"], msg.get("agent_id")), ("AUTH_OK", "claude"))


class TestLocalDevelopment(unittest.TestCase):
    def test_localhost_without_auth_writes_as_local(self):
        tmp = tempfile.mkdtemp()
        try:
            with patch.dict(os.environ, {"AETHELNET_AGENTS_FILE": os.path.join(tmp, "none.json"),
                                         "AETHELNET_AUTH_TOKEN": ""}):
                client = TestClient(app)
                self.assertEqual(client.get("/api/agents/whoami").json()["writes_attributed_to"], "local")
                res = client.post("/api/lgnn/node", json={"id": "Prov_Local", "text_content": "x"})
                self.assertEqual(res.status_code, 200)
            self.assertEqual(_provenance("lgnn_nodes", "id", "Prov_Local"), ("local", "local"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
