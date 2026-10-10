import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from aethelnet_node import security
from aethelnet_node.security import token_auth_middleware, is_within_directory


def _mini_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(token_auth_middleware)

    @app.get("/public")
    def public():
        return {"ok": True}

    @app.post("/api/lgnn/write")
    def write():
        return {"ok": True}

    @app.get("/api/lgnn/naas/{node_id}")
    def naas(node_id: str):
        return {"ok": True}

    @app.post("/p2p/sync")
    def p2p_sync():
        return {"ok": True}

    return app


REMOTE = ("203.0.113.7", 50000)


class TestTokenMiddlewareWithoutToken(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"AETHELNET_AUTH_TOKEN": "", "AETHELNET_PEER_TOKEN": ""})
        self.env.start()
        self.app = _mini_app()

    def tearDown(self):
        self.env.stop()

    def test_reads_are_public(self):
        res = TestClient(self.app, client=REMOTE).get("/public")
        self.assertEqual(res.status_code, 200)

    def test_local_writes_allowed(self):
        res = TestClient(self.app).post("/api/lgnn/write")
        self.assertEqual(res.status_code, 200)

    def test_remote_writes_rejected(self):
        res = TestClient(self.app, client=REMOTE).post("/api/lgnn/write")
        self.assertEqual(res.status_code, 401)

    def test_proxied_requests_are_not_local(self):
        res = TestClient(self.app).post("/api/lgnn/write", headers={"X-Forwarded-For": "203.0.113.7"})
        self.assertEqual(res.status_code, 401)

    def test_peer_routes_stay_open(self):
        res = TestClient(self.app, client=REMOTE).post("/p2p/sync")
        self.assertEqual(res.status_code, 200)


class TestTokenMiddlewareWithToken(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"AETHELNET_AUTH_TOKEN": "s3cret-token", "AETHELNET_PEER_TOKEN": ""})
        self.env.start()
        self.client = TestClient(_mini_app(), client=REMOTE)

    def tearDown(self):
        self.env.stop()

    def test_missing_token_rejected(self):
        self.assertEqual(self.client.post("/api/lgnn/write").status_code, 401)

    def test_wrong_token_rejected(self):
        res = self.client.post("/api/lgnn/write", headers={"Authorization": "Bearer nope"})
        self.assertEqual(res.status_code, 401)

    def test_bearer_token_accepted(self):
        res = self.client.post("/api/lgnn/write", headers={"Authorization": "Bearer s3cret-token"})
        self.assertEqual(res.status_code, 200)

    def test_header_token_accepted(self):
        res = self.client.post("/api/lgnn/write", headers={"X-Aethelnet-Token": "s3cret-token"})
        self.assertEqual(res.status_code, 200)

    def test_local_writes_also_need_token(self):
        res = TestClient(_mini_app()).post("/api/lgnn/write")
        self.assertEqual(res.status_code, 401)

    def test_naas_get_needs_token(self):
        self.assertEqual(self.client.get("/api/lgnn/naas/x").status_code, 401)
        res = self.client.get("/api/lgnn/naas/x", headers={"Authorization": "Bearer s3cret-token"})
        self.assertEqual(res.status_code, 200)

    def test_auth_headers_helper(self):
        self.assertEqual(security.auth_headers(), {"Authorization": "Bearer s3cret-token"})
        self.assertEqual(security.auth_headers(""), {})


class TestPeerToken(unittest.TestCase):
    def test_peer_token_enforced_when_set(self):
        with patch.dict(os.environ, {"AETHELNET_AUTH_TOKEN": "op", "AETHELNET_PEER_TOKEN": "mesh"}):
            client = TestClient(_mini_app(), client=REMOTE)
            self.assertEqual(client.post("/p2p/sync").status_code, 401)
            self.assertEqual(client.post("/p2p/sync", headers={"Authorization": "Bearer mesh"}).status_code, 200)


class TestPathContainment(unittest.TestCase):
    def test_is_within_directory(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertTrue(is_within_directory(root, os.path.join(root, "a", "b.md")))
            self.assertFalse(is_within_directory(root, os.path.join(root, "..", "evil.md")))
            self.assertFalse(is_within_directory(root, os.path.join(root + "_sibling", "x.md")))


class TestNodeEndpoints(unittest.TestCase):
    """Integration checks against the real app (requests come from 'testclient', i.e. localhost)."""

    @classmethod
    def setUpClass(cls):
        from aethelnet_node.database import init_db
        from aethelnet_node.main import app
        init_db()
        cls.client = TestClient(app)

    def test_naas_code_execution_disabled_by_default(self):
        with patch.dict(os.environ, {"AETHELNET_AUTH_TOKEN": "", "AETHELNET_ALLOW_CODE_EXEC": ""}):
            res = self.client.post("/api/lgnn/node", json={"id": "SecTest_PyApp", "text_content": "APP:Python\nresult = 6 * 7"})
            self.assertEqual(res.status_code, 200)
            res = self.client.get("/api/lgnn/naas/SecTest_PyApp")
            self.assertEqual(res.status_code, 403)

    def test_naas_code_execution_opt_in(self):
        with patch.dict(os.environ, {"AETHELNET_AUTH_TOKEN": "", "AETHELNET_ALLOW_CODE_EXEC": "1"}):
            self.client.post("/api/lgnn/node", json={"id": "SecTest_PyApp2", "text_content": "APP:Python\nresult = 6 * 7"})
            res = self.client.get("/api/lgnn/naas/SecTest_PyApp2")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["result"], 42)

    def test_vault_save_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as vault, \
                patch.dict(os.environ, {"AETHELNET_AUTH_TOKEN": "", "AETHELNET_VAULT_PATH": vault}):
            outside = os.path.join(os.path.dirname(vault), "outside_target.md")
            with open(outside, "w") as f:
                f.write("original")
            try:
                res = self.client.post("/api/lgnn/vault/save_note", json={"id": "../../evil", "text_content": "x"})
                self.assertEqual(res.status_code, 400)
                res = self.client.post("/api/lgnn/vault/save_note", json={
                    "id": "note", "text_content": "pwned", "vault_path": os.path.join("..", "outside_target.md")
                })
                self.assertEqual(res.status_code, 400)
                with open(outside) as f:
                    self.assertEqual(f.read(), "original")
            finally:
                os.remove(outside)


if __name__ == "__main__":
    unittest.main()
