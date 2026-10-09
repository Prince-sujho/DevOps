"""Throwaway probe: a health service, and a job that checks jobs-run.

The Cloud Run service starts this module with the argument ``serve``.
The Cloud Run job starts it with no arguments. PROBE_CHECKS=on runs the
real jobs-run checks: a secret, one Firestore document, and a write then
delete in the bucket named by the KNOWLEDGE_STORE_GCS_BUCKET secret.
Anything else just prints ok.
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

SECRET = "NEO4J_URI"
BUCKET_SECRET = "KNOWLEDGE_STORE_GCS_BUCKET"
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


def _read_secret_value(
    project: str, region: str, secret_name: str, token: str, urlopen
) -> bytes:
    """Fetch one secret's latest version and return its decoded value.

    Args:
        project: the Google project that holds the secret.
        region: the region the secret lives in (secrets are regional).
        secret_name: the Secret Manager secret id.
        token: bearer token for jobs-run.
        urlopen: urllib-style opener.
    Returns:
        The decoded secret payload.
    Raises:
        RuntimeError: the secret could not be read, or was empty.
    """
    url = (
        f"https://secretmanager.{region}.rep.googleapis.com/v1/projects/"
        f"{project}/locations/{region}/secrets/{secret_name}/versions/latest:access"
    )
    status, raw = _request(url, token, urlopen)
    if status != 200:
        raise RuntimeError(f"secret read failed ({secret_name}): HTTP {status}")
    encoded = json.loads(raw.decode()).get("payload", {}).get("data", "")
    decoded = base64.b64decode(encoded) if encoded else b""
    if not decoded:
        raise RuntimeError(f"secret read failed ({secret_name}): empty value")
    return decoded


def _read_secret(project: str, region: str, token: str, urlopen) -> None:
    """Confirm NEO4J_URI can be read. The value is never printed.

    Args:
        project: the Google project that holds the secret.
        region: the region the secret lives in.
        token: bearer token for jobs-run.
        urlopen: urllib-style opener.
    Returns:
        None.
    Raises:
        RuntimeError: the secret could not be read, or was empty.
    """
    _read_secret_value(project, region, SECRET, token, urlopen)


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


def _write_then_delete(bucket: str, token: str, urlopen) -> None:
    """Write probe/<timestamp> to the bucket, then delete it.

    Args:
        bucket: the GCS bucket name to write to.
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
        f"{bucket}/o?uploadType=media&name={quoted}"
    )
    status, _raw = _request(
        upload, token, urlopen, b"ok", content_type="text/plain"
    )
    if status not in (200, 201):
        raise RuntimeError(f"bucket write failed: HTTP {status}")
    delete = (
        "https://storage.googleapis.com/storage/v1/b/"
        f"{bucket}/o/{quoted}"
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


def run_production(project: str, region: str, urlopen) -> None:
    """Run the three jobs-run checks. Stop on the first failure.

    Args:
        project: the Google project the checks run against.
        region: the region secrets and the bucket live in.
        urlopen: urllib-style opener.
    Returns:
        None.
    Raises:
        RuntimeError: one of the three checks failed.
    """
    token = _token(urlopen)
    _read_secret(project, region, token, urlopen)
    bucket = _read_secret_value(
        project, region, BUCKET_SECRET, token, urlopen
    ).decode()
    _read_one_document(project, token, urlopen)
    _write_then_delete(bucket, token, urlopen)


def run_job(project: str, region: str, checks_on: bool, urlopen) -> int:
    """checks_on decides whether the real jobs-run checks run.

    Args:
        project: GOOGLE_CLOUD_PROJECT, or empty when it is unset.
        region: GOOGLE_CLOUD_LOCATION, or empty when it is unset.
        checks_on: PROBE_CHECKS == "on".
        urlopen: urllib-style opener.
    Returns:
        0 on success.
    Raises:
        RuntimeError: a jobs-run check failed, or PROBE_CHECKS is on and
            project or region is empty.
    """
    if not checks_on:
        print("ok")
        return 0
    if not project or not region:
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION are required "
            "when PROBE_CHECKS=on"
        )
    run_production(project, region, urlopen)
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
    region = os.environ.get("GOOGLE_CLOUD_LOCATION", "")
    checks_on = os.environ.get("PROBE_CHECKS", "") == "on"
    try:
        return run_job(project, region, checks_on, urllib.request.urlopen)
    except RuntimeError as err:
        print(f"probe-job failed: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
