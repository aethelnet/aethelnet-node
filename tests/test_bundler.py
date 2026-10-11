import importlib
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


def _load_bundler(env):
    """Import the bundler with a controlled environment (CORS is configured at import time)."""
    with patch.dict(os.environ, env):
        import aethelnet_node.bundler as bundler
        return importlib.reload(bundler)


USER_OP = {
    "sender": "0x0000000000000000000000000000000000000001",
    "nonce": "0x0",
    "callData": "0x",
    "accountGasLimits": "0x" + "00" * 32,
    "preVerificationGas": "0x0",
    "gasFees": "0x" + "00" * 32,
    "signature": "0x",
}


class TestBundlerKeyHandling(unittest.TestCase):
    def test_no_fallback_key(self):
        bundler = _load_bundler({"AETHELNET_BUNDLER_KEY": ""})
        with patch.dict(os.environ, {"AETHELNET_BUNDLER_KEY": ""}):
            with self.assertRaises(bundler.BundlerKeyMissing):
                bundler.get_bundler_key()

            res = TestClient(bundler.app).post("/rpc", json={
                "jsonrpc": "2.0", "id": 7, "method": "eth_sendUserOperation", "params": [USER_OP]
            })
        body = res.json()
        self.assertEqual(body["id"], 7)
        self.assertIn("AETHELNET_BUNDLER_KEY is not set", body["error"]["message"])

    def test_read_only_methods_work_without_key(self):
        bundler = _load_bundler({"AETHELNET_BUNDLER_KEY": ""})
        res = TestClient(bundler.app).post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "eth_chainId"})
        self.assertEqual(res.json()["result"], hex(11155111))

    def test_main_refuses_to_start_without_key(self):
        bundler = _load_bundler({"AETHELNET_BUNDLER_KEY": ""})
        with patch.dict(os.environ, {"AETHELNET_BUNDLER_KEY": ""}), patch("uvicorn.run") as run:
            with self.assertRaises(SystemExit):
                bundler.main()
            run.assert_not_called()

    def test_main_binds_to_localhost_by_default(self):
        bundler = _load_bundler({"AETHELNET_BUNDLER_KEY": ""})
        env = {"AETHELNET_BUNDLER_KEY": "set-but-unused", "AETHELNET_BUNDLER_HOST": ""}
        with patch.dict(os.environ, env), patch("uvicorn.run") as run:
            os.environ.pop("AETHELNET_BUNDLER_HOST")
            bundler.main()
        self.assertEqual(run.call_args.kwargs["host"], "127.0.0.1")


class TestBundlerCors(unittest.TestCase):
    def test_no_cors_headers_by_default(self):
        bundler = _load_bundler({"AETHELNET_BUNDLER_CORS_ORIGINS": ""})
        res = TestClient(bundler.app).post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "eth_chainId"},
                                           headers={"Origin": "https://evil.example"})
        self.assertNotIn("access-control-allow-origin", res.headers)

    def test_allowed_origin_gets_cors_headers(self):
        bundler = _load_bundler({"AETHELNET_BUNDLER_CORS_ORIGINS": "http://localhost:5173"})
        res = TestClient(bundler.app).post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "eth_chainId"},
                                           headers={"Origin": "http://localhost:5173"})
        self.assertEqual(res.headers.get("access-control-allow-origin"), "http://localhost:5173")

    @classmethod
    def tearDownClass(cls):
        _load_bundler({"AETHELNET_BUNDLER_CORS_ORIGINS": ""})


if __name__ == "__main__":
    unittest.main()
