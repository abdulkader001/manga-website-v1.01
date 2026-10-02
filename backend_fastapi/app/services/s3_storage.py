"""Minimal S3-compatible storage client for backups (AWS Signature V4).

Works with any S3-compatible service: Cloudflare R2, Backblaze B2, Wasabi,
MinIO on your own server, AWS S3. Uses path-style URLs
(``{endpoint}/{bucket}/{key}``), which all of them accept, and ``requests``,
which the app already ships -- no boto3. Bodies are sent as ``UNSIGNED-PAYLOAD`` (the
request itself is signed; the transport is HTTPS), so a multi-gigabyte backup
is streamed from disk instead of being hashed first.

Only what backups need: put (single or multipart), get to a file, list,
delete, and a connection test.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional
from urllib.parse import quote, urlparse

import requests

UNSIGNED = "UNSIGNED-PAYLOAD"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
PART_SIZE = 64 * 1024 * 1024  # multipart above this; S3 allows 5 MB - 5 GB parts
TIMEOUT = (30.0, 600.0)  # connect, read
_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


class StorageError(RuntimeError):
    """The storage answered with an error (message is safe to show)."""


@dataclass(frozen=True)
class S3Target:
    endpoint: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    region: str = "auto"
    prefix: str = ""

    def key(self, name: str) -> str:
        prefix = self.prefix.strip("/")
        return f"{prefix}/{name}" if prefix else name

    def public_summary(self) -> Dict[str, str]:
        return {
            "endpoint": self.endpoint,
            "bucket": self.bucket,
            "region": self.region,
            "prefix": self.prefix,
            "access_key_id": self.access_key_id[:4] + "…" if self.access_key_id else "",
        }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _encode_path(path: str) -> str:
    return quote(path, safe="/-_.~")


def _canonical_query(params: Dict[str, str]) -> str:
    return "&".join(
        f"{quote(k, safe='-_.~')}={quote(str(v), safe='-_.~')}" for k, v in sorted(params.items())
    )


def sign(
    *,
    method: str,
    url: str,
    headers: Dict[str, str],
    access_key_id: str,
    secret_access_key: str,
    region: str,
    payload_hash: str,
    now: Optional[datetime] = None,
    service: str = "s3",
) -> Dict[str, str]:
    """Return ``headers`` plus the SigV4 ``Authorization``/``x-amz-*`` headers.

    ``url`` must already carry its canonical (encoded) path and query.
    """

    now = now or datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date = amz_date[:8]
    parsed = urlparse(url)
    out = {k: v for k, v in headers.items()}
    out["host"] = parsed.netloc
    out["x-amz-date"] = amz_date
    out["x-amz-content-sha256"] = payload_hash

    query: Dict[str, str] = {}
    if parsed.query:
        for part in parsed.query.split("&"):
            k, _, v = part.partition("=")
            query[_unquote(k)] = _unquote(v)

    lowered = {k.lower(): " ".join(str(v).strip().split()) for k, v in out.items()}
    signed_names = sorted(lowered)
    canonical_headers = "".join(f"{name}:{lowered[name]}\n" for name in signed_names)
    signed_headers = ";".join(signed_names)
    canonical_request = "\n".join(
        [
            method.upper(),
            parsed.path or "/",
            _canonical_query(query),
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )
    scope = f"{date}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, _sha256(canonical_request.encode("utf-8"))]
    )
    key = _hmac(("AWS4" + secret_access_key).encode("utf-8"), date)
    key = _hmac(key, region)
    key = _hmac(key, service)
    key = _hmac(key, "aws4_request")
    signature = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    out["Authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key_id}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return out


def _unquote(text: str) -> str:
    from urllib.parse import unquote

    return unquote(text)


class S3Client:
    def __init__(self, target: S3Target, *, session: Optional[requests.Session] = None):
        if not (target.endpoint and target.bucket and target.access_key_id and target.secret_access_key):
            raise StorageError("Storage is not fully set up (endpoint, bucket and both keys are needed).")
        self.target = target
        self._session = session or requests.Session()

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "S3Client":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # -- plumbing ---------------------------------------------------------
    def _url(self, key: str = "", params: Optional[Dict[str, str]] = None) -> str:
        base = self.target.endpoint.rstrip("/")
        path = f"/{self.target.bucket}" + (f"/{_encode_path(key)}" if key else "")
        query = _canonical_query(params) if params else ""
        return f"{base}{path}" + (f"?{query}" if query else "")

    def _request(
        self,
        method: str,
        key: str = "",
        *,
        params: Optional[Dict[str, str]] = None,
        content=None,
        headers: Optional[Dict[str, str]] = None,
        payload_hash: str = EMPTY_SHA256,
        stream: bool = False,
    ) -> requests.Response:
        url = self._url(key, params)
        signed = sign(
            method=method,
            url=url,
            headers=headers or {},
            access_key_id=self.target.access_key_id,
            secret_access_key=self.target.secret_access_key,
            region=self.target.region or "auto",
            payload_hash=payload_hash,
        )
        try:
            response = self._session.request(
                method, url, headers=signed, data=content, stream=stream, timeout=TIMEOUT, allow_redirects=False
            )
        except requests.RequestException as exc:
            raise StorageError(f"Could not reach the storage: {exc.__class__.__name__}") from exc
        if response.status_code >= 300:
            body = response.text
            response.close()
            raise StorageError(_error_message(response.status_code, body))
        return response

    # -- operations -------------------------------------------------------
    def test(self) -> None:
        """Write, read back and delete a tiny object: proves every permission backups use."""

        name = self.target.key(f".connection-test-{uuid.uuid4().hex}")
        payload = b"mangaworld backup connection test"
        self._request("PUT", name, content=payload, payload_hash=_sha256(payload))
        try:
            got = self._request("GET", name).content
            if got != payload:
                raise StorageError("The storage returned different data than was written.")
        finally:
            self._request("DELETE", name)

    def put_file(self, path: Path, name: str, *, progress: Optional[Callable[[int], None]] = None) -> str:
        key = self.target.key(name)
        size = path.stat().st_size
        if size <= PART_SIZE:
            with open(path, "rb") as fh:
                self._request(
                    "PUT",
                    key,
                    content=fh,
                    headers={"content-length": str(size)},
                    payload_hash=UNSIGNED,
                )
            if progress:
                progress(size)
            return key
        return self._multipart(path, key, progress)

    def _multipart(self, path: Path, key: str, progress) -> str:
        created = self._request("POST", key, params={"uploads": ""})
        upload_id = _find_text(created.text, "UploadId")
        if not upload_id:
            raise StorageError("The storage did not start a multipart upload.")
        parts: List[tuple[int, str]] = []
        try:
            with open(path, "rb") as fh:
                number = 0
                while True:
                    chunk = fh.read(PART_SIZE)
                    if not chunk:
                        break
                    number += 1
                    response = self._request(
                        "PUT",
                        key,
                        params={"partNumber": str(number), "uploadId": upload_id},
                        content=chunk,
                        headers={"content-length": str(len(chunk))},
                        payload_hash=UNSIGNED,
                    )
                    parts.append((number, response.headers.get("etag", "")))
                    if progress:
                        progress(fh.tell())
            body = "<CompleteMultipartUpload>" + "".join(
                f"<Part><PartNumber>{n}</PartNumber><ETag>{etag}</ETag></Part>" for n, etag in parts
            ) + "</CompleteMultipartUpload>"
            data = body.encode("utf-8")
            done = self._request(
                "POST", key, params={"uploadId": upload_id}, content=data, payload_hash=_sha256(data)
            )
            if "<Error>" in done.text:  # S3 can report a failed completion with 200
                raise StorageError(_error_message(200, done.text))
        except Exception:
            try:
                self._request("DELETE", key, params={"uploadId": upload_id})
            except StorageError:
                pass
            raise
        return key

    def get_to_file(self, name: str, dest: Path) -> int:
        response = self._request("GET", self.target.key(name), stream=True)
        written = 0
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with open(tmp, "wb") as fh:
                for chunk in response.iter_content(1024 * 1024):
                    fh.write(chunk)
                    written += len(chunk)
        finally:
            response.close()
        os.replace(tmp, dest)
        return written

    def delete(self, name: str) -> None:
        self._request("DELETE", self.target.key(name))

    def list(self) -> Iterator[Dict[str, object]]:
        prefix = self.target.key("") if self.target.prefix.strip("/") else ""
        token: Optional[str] = None
        while True:
            params = {"list-type": "2", "prefix": prefix}
            if token:
                params["continuation-token"] = token
            root = ET.fromstring(self._request("GET", params=params).text)
            for item in root.iter(f"{_NS}Contents"):
                key = item.findtext(f"{_NS}Key") or ""
                yield {
                    "key": key,
                    "name": key[len(prefix):] if prefix and key.startswith(prefix) else key,
                    "size": int(item.findtext(f"{_NS}Size") or 0),
                    "modified": item.findtext(f"{_NS}LastModified"),
                }
            if (root.findtext(f"{_NS}IsTruncated") or "").lower() != "true":
                break
            token = root.findtext(f"{_NS}NextContinuationToken")
            if not token:
                break


def _find_text(xml: str, tag: str) -> Optional[str]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    for el in root.iter():
        if el.tag.split("}")[-1] == tag:
            return el.text
    return None


def _error_message(status: int, body: str) -> str:
    code = _find_text(body, "Code") if body else None
    message = _find_text(body, "Message") if body else None
    hints = {
        "InvalidAccessKeyId": "The access key ID is wrong.",
        "SignatureDoesNotMatch": "The secret access key is wrong (or the region is).",
        "NoSuchBucket": "That bucket doesn't exist.",
        "AccessDenied": "These keys aren't allowed to do that in this bucket.",
        "NoSuchKey": "That file isn't in the storage.",
    }
    if code in hints:
        return hints[code]
    return f"Storage error {status}" + (f": {code}" if code else "") + (f" ({message})" if message else "")


__all__ = ["S3Target", "S3Client", "StorageError", "sign", "PART_SIZE"]
