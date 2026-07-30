"""Minimal streamable-HTTP client for https://mcp.tafsir.net/mcp.

Used by offline pipeline scripts (audit / harvest). Not imported by the Flask
request path — production serves pre-built SQLite only.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_URL = "https://mcp.tafsir.net/mcp"
DEFAULT_TIMEOUT = 60


class TafsirMcpError(RuntimeError):
    pass


class TafsirMcpClient:
    def __init__(self, url: str = DEFAULT_URL, timeout: float = DEFAULT_TIMEOUT):
        self.url = url
        self.timeout = timeout
        self._req_id = 0

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            retry = exc.headers.get("Retry-After") if exc.headers else None
            raise TafsirMcpError(
                f"HTTP {exc.code} from Tafsir MCP"
                + (f" (Retry-After={retry})" if retry else "")
            ) from exc
        except urllib.error.URLError as exc:
            raise TafsirMcpError(f"Network error talking to Tafsir MCP: {exc}") from exc

        message = self._parse_sse_or_json(body)
        if "error" in message:
            raise TafsirMcpError(f"MCP error: {message['error']}")
        return message

    @staticmethod
    def _parse_sse_or_json(body: str) -> dict[str, Any]:
        text = body.strip()
        if not text:
            raise TafsirMcpError("Empty MCP response")
        if text[0] == "{":
            return json.loads(text)
        for line in text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise TafsirMcpError(f"Unrecognized MCP response: {text[:200]!r}")

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call an MCP tool and return the parsed JSON payload (when content is JSON text)."""
        message = self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        })
        result = message.get("result") or {}
        content = result.get("content") or []
        if not content:
            return result
        # Prefer first text block; Tafsir MCP wraps tool results as JSON-in-text.
        for block in content:
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                raw = block["text"]
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return raw
        return result

    def fetch_nuzool_reason(
        self,
        surah: int,
        ayah: int,
        sources: list[str] | None = None,
        part: int = 1,
        retries: int = 3,
        backoff: float = 1.5,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"surah": surah, "ayah": ayah, "part": part}
        if sources:
            args["sources"] = sources
        last_err: Exception | None = None
        for attempt in range(retries):
            try:
                payload = self.call_tool("fetch_nuzool_reason", args)
                if not isinstance(payload, dict):
                    raise TafsirMcpError(f"Unexpected fetch_nuzool payload: {type(payload)}")
                return payload
            except TafsirMcpError as exc:
                last_err = exc
                if attempt + 1 >= retries:
                    break
                time.sleep(backoff * (attempt + 1))
        assert last_err is not None
        raise last_err

    def fetch_ayah(
        self,
        surah: int,
        ayah: int,
        include: list[str] | None = None,
        retries: int = 3,
        backoff: float = 1.5,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"surah": surah, "ayah": ayah}
        if include:
            args["include"] = include
        last_err: Exception | None = None
        for attempt in range(retries):
            try:
                payload = self.call_tool("fetch_ayah", args)
                if not isinstance(payload, dict):
                    raise TafsirMcpError(f"Unexpected fetch_ayah payload: {type(payload)}")
                return payload
            except TafsirMcpError as exc:
                last_err = exc
                if attempt + 1 >= retries:
                    break
                time.sleep(backoff * (attempt + 1))
        assert last_err is not None
        raise last_err
