"""The wire protocol between the Tauri shell and this core.

Newline-delimited JSON over stdin/stdout. One JSON object per line, no framing
headers, no partial writes.

    request   {"id": 1, "method": "ping", "params": {}}
    response  {"id": 1, "ok": true,  "result": {...}}
    error     {"id": 1, "ok": false, "error": {"code": "...", "message": "..."}}

`id` is opaque to the core and echoed back verbatim; the shell uses it to match a
response to its caller. That matching is what lets the core answer requests **on a
thread each**, so a handler that spawns a subprocess does not stop it answering
anything else -- responses come back in whatever order the handlers finish, and
nothing may ever be inferred from their order. stdout carries the wire and nothing
else -- every log line goes to stderr, or it corrupts the stream.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 1


class ProtocolError(Exception):
    """A malformed line. Carries the code reported back to the shell."""

    def __init__(self, code: str, message: str, request_id: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.request_id = request_id


@dataclass(frozen=True)
class Request:
    id: Any
    method: str
    params: dict[str, Any]


def decode_request(line: str) -> Request:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError("invalid_json", f"not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ProtocolError("invalid_request", "request must be a JSON object")

    request_id = payload.get("id")
    method = payload.get("method")
    if not isinstance(method, str) or not method:
        raise ProtocolError("invalid_request", "missing 'method'", request_id)

    params = payload.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ProtocolError("invalid_request", "'params' must be an object", request_id)

    return Request(id=request_id, method=method, params=params)


def encode_result(request_id: Any, result: Any) -> str:
    return json.dumps({"id": request_id, "ok": True, "result": result}, default=str)


def encode_error(request_id: Any, code: str, message: str) -> str:
    return json.dumps({"id": request_id, "ok": False, "error": {"code": code, "message": message}})
