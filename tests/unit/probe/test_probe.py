"""Local checks for the throwaway probe. No Google calls."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from urllib.error import HTTPError

from probe.jobs.job import PROD_PROJECT, ProbeHandler, run_job, version_body


class _Resp:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None


class ProbeTests(unittest.TestCase):
    def test_preprod_prints_ok_and_does_not_call_google(self) -> None:
        """A non-production project exits 0 after printing ok.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        def urlopen(req, timeout=20):
            raise AssertionError("preprod must not call Google")

        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(run_job("sujho-preprod", urlopen), 0)
        self.assertEqual(out.getvalue().strip(), "ok")

    def test_production_runs_secret_firestore_and_bucket(self) -> None:
        """Production walks the three checks and then exits 0.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        replies = [
            (200, {"access_token": "tok"}),
            (200, {"payload": {"data": "eA=="}}),
            (200, {"collectionIds": ["threads"]}),
            (200, {"documents": [{"name": "threads/1"}]}),
            (200, {}),
        ]

        def urlopen(req, timeout=20):
            if req.get_method() == "DELETE":
                self.assertIn("sujho-knowledge-store-staging", req.full_url)
                return _Resp(204, b"")
            status, payload = replies.pop(0)
            if status >= 400:
                raise HTTPError(req.full_url, status, "err", hdrs=None, fp=None)
            return _Resp(status, json.dumps(payload).encode())

        self.assertEqual(run_job(PROD_PROJECT, urlopen), 0)
        self.assertEqual(replies, [])

    def test_health_and_version(self) -> None:
        """/health is 200 and /version names the release env vars.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        handler = ProbeHandler.__new__(ProbeHandler)
        handler.path = "/health"
        handler.wfile = io.BytesIO()
        sent = {}
        handler.send_response = lambda code, message=None: sent.__setitem__(
            "code", code
        )
        handler.send_header = lambda key, value: None
        handler.end_headers = lambda: None
        handler.do_GET()
        self.assertEqual(sent["code"], 200)
        body = version_body()
        self.assertIn(b"RELEASE_COMMIT_SHA", body)
        self.assertIn(b"RELEASE_IMAGE_DIGEST", body)


if __name__ == "__main__":
    unittest.main()
