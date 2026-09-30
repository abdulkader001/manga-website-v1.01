"""Lightweight stand-in for the httpx package used by Starlette's TestClient."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from . import _client, _types

__all__ = [
    "BaseTransport",
    "ByteStream",
    "Client",
    "Request",
    "Response",
    "USE_CLIENT_DEFAULT",
    "_client",
    "_types",
]

USE_CLIENT_DEFAULT = _client.USE_CLIENT_DEFAULT


class Headers:
    """A minimal header container supporting the subset used in tests."""

    def __init__(self, items: Optional[Mapping[str, str]] = None) -> None:
        self._items: List[Tuple[str, str]] = []
        if items:
            for key, value in items.items():
                self.add(key, value)

    def add(self, key: str, value: str) -> None:
        self._items.append((key, value))

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        key_lower = key.lower()
        for stored_key, stored_value in reversed(self._items):
            if stored_key.lower() == key_lower:
                return stored_value
        return default

    def multi_items(self) -> Iterable[Tuple[str, str]]:
        return list(self._items)

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        key_lower = key.lower()
        return any(stored_key.lower() == key_lower for stored_key, _ in self._items)


@dataclass
class URL:
    scheme: str
    host: str
    port: Optional[int]
    path: str
    query: bytes

    @property
    def netloc(self) -> bytes:
        if self.port is None:
            return self.host.encode("ascii")
        return f"{self.host}:{self.port}".encode("ascii")

    @property
    def raw_path(self) -> bytes:
        return (self.path or "/").encode("ascii")


class Request:
    def __init__(
        self,
        method: str,
        url: str,
        headers: Optional[Mapping[str, str]] = None,
        content: Optional[bytes] = None,
    ) -> None:
        split = urlsplit(url)
        self.url = URL(
            scheme=split.scheme or "http",
            host=split.hostname or "",
            port=split.port,
            path=split.path or "/",
            query=(split.query.encode("ascii") if split.query else b""),
        )
        self.method = method.upper()
        self.headers = Headers(headers)
        self._body = content or b""
        self.stream = ByteStream(self._body)

    def read(self) -> bytes:
        return self._body


class ByteStream:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class Response:
    def __init__(
        self,
        status_code: int,
        headers: Optional[List[Tuple[str, str]]] = None,
        stream: Optional[ByteStream] = None,
        request: Optional[Request] = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or []
        self.request = request
        self._content = stream.read() if stream is not None else b""

    @property
    def content(self) -> bytes:
        return self._content

    @property
    def text(self) -> str:
        return self._content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text or "null")


class BaseTransport:
    def handle_request(
        self, request: Request
    ) -> Response:  # pragma: no cover - interface only
        raise NotImplementedError


class Client:
    def __init__(
        self,
        base_url: str = "http://testserver",
        headers: Optional[Mapping[str, str]] = None,
        transport: Optional[BaseTransport] = None,
        follow_redirects: bool = True,
        cookies: Optional[Any] = None,
    ) -> None:
        self.base_url = base_url
        self.headers = Headers(headers)
        self.transport = transport or BaseTransport()
        self.follow_redirects = follow_redirects
        self.cookies = cookies

    # Context manager support -------------------------------------------------
    def __enter__(self) -> "Client":  # pragma: no cover - convenience
        return self

    def __exit__(self, *args: Any) -> None:  # pragma: no cover - convenience
        return None

    # Internal helpers -------------------------------------------------------
    def _merge_url(self, url: Any) -> str:
        if isinstance(url, str):
            if url.startswith("http://") or url.startswith("https://"):
                return url
            return urljoin(self.base_url, url)
        return str(url)

    def _build_request(
        self,
        method: str,
        url: str,
        *,
        content: Optional[bytes] = None,
        data: Optional[Mapping[str, Any]] = None,
        json_data: Any = None,
        headers: Optional[Mapping[str, str]] = None,
        files: Optional[Mapping[str, Any]] = None,
    ) -> Request:
        body: Optional[bytes] = content
        final_headers: Dict[str, str] = {
            key: value for key, value in self.headers.multi_items()
        }
        if headers:
            final_headers.update(headers)
        if body is None and data is not None:
            encoded = []
            for key, value in data.items():
                encoded.append(f"{key}={value}")
            body = "&".join(encoded).encode("utf-8")
            final_headers.setdefault(
                "content-type", "application/x-www-form-urlencoded"
            )
        if body is None and json_data is not None:
            body = json.dumps(json_data).encode("utf-8")
            final_headers.setdefault("content-type", "application/json")
        if body is None and files:
            boundary = "----httpxboundary"
            parts: List[bytes] = []
            items = files.items() if hasattr(files, "items") else list(files)
            for item in items:
                if hasattr(files, "items"):
                    field, file_info = item
                else:
                    field, file_info = item
                if isinstance(file_info, (list, tuple)):
                    if len(file_info) == 3:
                        filename, file_content, content_type = file_info
                    elif len(file_info) == 2:
                        filename, file_content = file_info
                        content_type = "application/octet-stream"
                    else:
                        filename = str(file_info[0])
                        file_content = file_info[1] if len(file_info) > 1 else b""
                        content_type = "application/octet-stream"
                else:
                    filename = field
                    file_content = file_info
                    content_type = "application/octet-stream"

                if hasattr(file_content, "read"):
                    data_bytes = file_content.read()
                    if hasattr(file_content, "seek"):
                        try:
                            file_content.seek(0)
                        except Exception:  # pragma: no cover - best effort
                            pass
                else:
                    data_bytes = (
                        file_content
                        if isinstance(file_content, bytes)
                        else bytes(file_content)
                    )

                header = (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
                    f"Content-Type: {content_type}\r\n\r\n"
                ).encode("utf-8")
                parts.append(header + data_bytes + b"\r\n")
            parts.append(f"--{boundary}--\r\n".encode("utf-8"))
            body = b"".join(parts)
            final_headers["content-type"] = f"multipart/form-data; boundary={boundary}"
            final_headers["content-length"] = str(len(body))
        return Request(method, url, headers=final_headers, content=body)

    # Public request APIs ----------------------------------------------------
    def request(
        self,
        method: str,
        url: _types.URLTypes,
        *,
        content: _types.RequestContent | None = None,
        data: Mapping[str, Any] | None = None,
        files: _types.RequestFiles | None = None,
        json: Any = None,
        params: _types.QueryParamTypes | None = None,
        headers: _types.HeaderTypes | None = None,
        cookies: _types.CookieTypes | None = None,
        auth: _types.AuthTypes | _client.UseClientDefault = USE_CLIENT_DEFAULT,
        follow_redirects: bool | _client.UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: _types.TimeoutTypes | _client.UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: Dict[str, Any] | None = None,
    ) -> Response:
        if params:
            separator = "&" if "?" in str(url) else "?"
            url = f"{url}{separator}" + "&".join(f"{k}={v}" for k, v in params.items())
        full_url = self._merge_url(url)
        request = self._build_request(
            method,
            full_url,
            content=content if isinstance(content, bytes) else None,
            data=data,
            json_data=json,
            headers=headers,
            files=files,
        )
        response = self.transport.handle_request(request)
        response.request = request
        return response

    def get(self, url: _types.URLTypes, **kwargs: Any) -> Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: _types.URLTypes, **kwargs: Any) -> Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: _types.URLTypes, **kwargs: Any) -> Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: _types.URLTypes, **kwargs: Any) -> Response:
        return self.request("DELETE", url, **kwargs)

    def options(self, url: _types.URLTypes, **kwargs: Any) -> Response:
        return self.request("OPTIONS", url, **kwargs)

    def head(self, url: _types.URLTypes, **kwargs: Any) -> Response:
        return self.request("HEAD", url, **kwargs)

    def patch(self, url: _types.URLTypes, **kwargs: Any) -> Response:
        return self.request("PATCH", url, **kwargs)

    def close(self) -> None:  # pragma: no cover - compatibility
        return None
