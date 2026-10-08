"""Throwaway probe: a health service, and a job that checks jobs-run.

The Cloud Run service starts this module with the argument ``serve``.
The Cloud Run job starts it with no arguments. Pre-Prod prints ok.
Production uses jobs-run for real: a secret, one Firestore document,
and a write then delete in the staging bucket.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROD_PROJECT = "sujho-478914"
BUCKET = "sujho-knowledge-store-staging"
SECRET = "NEO4J_URI"
TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/"
    "instance/service-accounts/default/token"
)


def _request(
    url: str,
    token: str | None,
    urlopen,
    data: bytes | None = None,
    content_type: str = "application/json",
) -> tuple[int, bytes]:
    """Perform one HTTP call and return status plus body.

    Args:
        url: the full URL.
        token: a bearer token, or None for the metadata server.
        urlopen: urllib-style opener, so tests can substitute one.
        data: optional request body. None means GET.
        content_type: used only when data is set.
    Returns:
        HTTP status and response body.
    Raises:
        None.
    """
    headers = {}
    if token is None:
        headers["Metadata-Flavor"] = "Google"
    else:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = content_type
    method = "POST" if data is not None else "GET"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=20) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def _token(urlopen) -> str:
    """The metadata-server access token for the runtime account.

    Args:
        urlopen: urllib-style opener.
    Returns:
        The access token string.
    Raises:
        RuntimeError: the metadata server did not return a token.
    """
    status, raw = _request(TOKEN_URL, None, urlopen)
    if status != 200:
        raise RuntimeError(f"metadata token failed: HTTP {status}")
    token = json.loads(raw.decode()).get("access_token", "")
    if not token:
        raise RuntimeError("metadata token failed: empty token")
    return token


def _read_secret(project: str, token: str, urlopen) -> None:
    """Confirm NEO4J_URI can be read. The value is never printed.

    Args:
        project: the Google project that holds the secret.
        token: bearer token for jobs-run.
        urlopen: urllib-style opener.
    Returns:
        None.
    Raises:
        RuntimeError: the secret could not be read, or was empty.
    """
    url = (
        "https://secretmanager.googleapis.com/v1/projects/"
        f"{project}/secrets/{SECRET}/versions/latest:access"
    )
    status, raw = _request(url, token, urlopen)
    if status != 200:
        raise RuntimeError(f"secret read failed: HTTP {status}")
    encoded = json.loads(raw.decode()).get("payload", {}).get("data", "")
    if not encoded or not base64.b64decode(encoded):
        raise RuntimeError("secret read failed: empty value")


def _read_one_document(project: str, token: str, urlopen) -> None:
    """Read a single existing Firestore document.

    Args:
        project: the Google project whose default database is read.
        token: bearer token for jobs-run.
        urlopen: urllib-style opener.
    Returns:
        None.
    Raises:
        RuntimeError: no collection, no document, or the call failed.
    """
    base = (
        "https://firestore.googleapis.com/v1/projects/"
        f"{project}/databases/(default)/documents"
    )
    status, raw = _request(f"{base}:listCollectionIds", token, urlopen, b"{}")
    if status != 200:
        raise RuntimeError(f"firestore list failed: HTTP {status}")
    names = json.loads(raw.decode()).get("collectionIds") or []
    if not names:
        raise RuntimeError("firestore list failed: no collections")
    status, raw = _request(
        f"{base}/{names[0]}?pageSize=1", token, urlopen
    )
    if status != 200:
        raise RuntimeError(f"firestore read failed: HTTP {status}")
    if not json.loads(raw.decode()).get("documents"):
        raise RuntimeError("firestore read failed: no documents")


def _write_then_delete(token: str, urlopen) -> None:
    """Write probe/<timestamp> to the staging bucket, then delete it.

    Args:
        token: bearer token for jobs-run.
        urlopen: urllib-style opener.
    Returns:
        None.
    Raises:
        RuntimeError: the write or the delete failed.
    """
    name = f"probe/{int(time.time())}"
    quoted = name.replace("/", "%2F")
    upload = (
        "https://storage.googleapis.com/upload/storage/v1/b/"
        f"{BUCKET}/o?uploadType=media&name={quoted}"
    )
    status, _raw = _request(
        upload, token, urlopen, b"ok", content_type="text/plain"
    )
    if status not in (200, 201):
        raise RuntimeError(f"bucket write failed: HTTP {status}")
    delete = (
        "https://storage.googleapis.com/storage/v1/b/"
        f"{BUCKET}/o/{quoted}"
    )
    req = urllib.request.Request(
        delete, headers={"Authorization": f"Bearer {token}"}, method="DELETE"
    )
    try:
        with urlopen(req, timeout=20) as resp:
            status = resp.status
    except urllib.error.HTTPError as err:
        status = err.code
    if status not in (200, 204):
        raise RuntimeError(f"bucket delete failed: HTTP {status}")


def run_production(project: str, urlopen) -> None:
    """Run the three production checks. Stop on the first failure.

    Args:
        project: must be the production project.
        urlopen: urllib-style opener.
    Returns:
        None.
    Raises:
        RuntimeError: one of the three checks failed.
    """
    token = _token(urlopen)
    _read_secret(project, token, urlopen)
    _read_one_document(project, token, urlopen)
    _write_then_delete(token, urlopen)


def run_job(project: str, urlopen) -> int:
    """Pre-Prod prints ok. Production runs the three jobs-run checks.

    Args:
        project: GOOGLE_CLOUD_PROJECT, or empty when it is unset.
        urlopen: urllib-style opener.
    Returns:
        0 on success.
    Raises:
        RuntimeError: a production check failed.
    """
    if project != PROD_PROJECT:
        print("ok")
        return 0
    run_production(project, urlopen)
    print("ok")
    return 0


def version_body() -> bytes:
    """The release env vars the real services expose, as JSON.

    Args:
        None.
    Returns:
        UTF-8 JSON naming the commit and image digest.
    Raises:
        None.
    """
    payload = {
        "RELEASE_COMMIT_SHA": os.environ.get("RELEASE_COMMIT_SHA", ""),
        "RELEASE_IMAGE_DIGEST": os.environ.get("RELEASE_IMAGE_DIGEST", ""),
    }
    return json.dumps(payload).encode()


class ProbeHandler(BaseHTTPRequestHandler):
    """GET /health and GET /version. Anything else is 404."""

    def do_GET(self) -> None:  # noqa: N802
        """Answer /health and /version.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        if self.path.split("?", 1)[0] == "/health":
            body = b"ok"
        elif self.path.split("?", 1)[0] == "/version":
            body = version_body()
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        """Drop the default access log.

        Args:
            fmt: unused format string from the base class.
            args: unused format values.
        Returns:
            None.
        Raises:
            None.
        """
        return


def serve() -> None:
    """Listen on PORT (Cloud Run sets it) until the process is stopped.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    port = int(os.environ.get("PORT", "8080"))
    ThreadingHTTPServer(("0.0.0.0", port), ProbeHandler).serve_forever()


def main(argv: list[str]) -> int:
    """Serve HTTP, or run the job, depending on the first argument.

    Args:
        argv: sys.argv. ``serve`` starts the HTTP server.
    Returns:
        Process exit code. The server does not return.
    Raises:
        None.
    """
    if len(argv) > 1 and argv[1] == "serve":
        serve()
        return 0
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    try:
        return run_job(project, urllib.request.urlopen)
    except RuntimeError as err:
        print(f"probe-job failed: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
