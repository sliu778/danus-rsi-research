import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from danus_rsi.protocol import ProtocolError
from danus_rsi.store import Store
from danus_rsi.valency import _call, import_snapshot, normalize_snapshot, search, unwrap


class ValencyTests(unittest.TestCase):
    def snapshot(self):
        return {"query": "proof verification", "papers": [
            {"id": "example-v1", "source": "arxiv", "title": "A fixture paper",
             "url": "https://arxiv.org/abs/example"}],
            "_meta": {"server_version": "fixture", "tool": "semantic_search_papers"}}

    def test_connector_and_mcp_text_envelopes(self):
        value = self.snapshot()
        self.assertEqual(normalize_snapshot({"structuredContent": value})["papers"], value["papers"])
        self.assertEqual(unwrap({"content": [{"type": "text", "text": json.dumps(value)}]}), value)

    def test_error_and_unsafe_permalink_rejected(self):
        with self.assertRaises(ValueError):
            unwrap({"isError": True, "content": []})
        value = self.snapshot()
        value["papers"][0]["url"] = "javascript:alert(1)"
        with self.assertRaises(ProtocolError):
            normalize_snapshot(value)

    def test_versions_remain_distinct_and_duplicate_import_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            value = self.snapshot()
            first = import_snapshot(store, value)
            self.assertEqual(import_snapshot(store, value), first)
            value["papers"][0]["id"] = "example-v2"
            import_snapshot(store, value)
            self.assertEqual(len(store.artifacts("paper")), 2)

    def test_credentials_required_and_not_sent_to_other_hosts(self):
        with patch.dict(os.environ, {"VALENCY_TOKEN": ""}):
            with self.assertRaisesRegex(ProtocolError, "VALENCY_TOKEN"):
                asyncio.run(_call("list_sources", {}))

    def test_sdk_error_details_cannot_expose_token(self):
        async def failure(*args):
            raise ValueError("Authorization: Bearer fixture-secret")
        with patch("danus_rsi.valency._call", failure):
            with self.assertRaises(RuntimeError) as caught:
                search("fixture query")
        self.assertNotIn("fixture-secret", str(caught.exception))
        with patch.dict(os.environ, {"VALENCY_TOKEN": "fixture-secret", "VALENCY_URL": "https://other.example/"}):
            with self.assertRaisesRegex(ProtocolError, "endpoint"):
                asyncio.run(_call("list_sources", {}))


if __name__ == "__main__":
    unittest.main()
