"""IPC message protocol for llming subprocess isolation.

Defines message types exchanged between the main process (router)
and llming subprocesses over Unix domain sockets.

Messages are newline-delimited JSON. Request/response pairs use
correlation IDs. Events flow one-way from subprocess to main.

This module is imported by both sides (main + subprocess), so it
MUST NOT import any heavy framework code.
"""

from __future__ import annotations

import uuid
from typing import Any


# Protocol version — bump when message format changes.
PROTOCOL_VERSION = 1


# ── Message types: Main → Subprocess ──

def msg_activate(config: dict[str, Any], llming: str = "") -> dict[str, Any]:
    return {"type": "activate", "id": _id(), "config": config, "llming": llming}


def msg_deactivate(llming: str = "") -> dict[str, Any]:
    return {"type": "deactivate", "id": _id(), "llming": llming}


def msg_execute_power(name: str, args: dict[str, Any], llming: str = "") -> dict[str, Any]:
    return {"type": "execute_power", "id": _id(), "name": name, "args": args, "llming": llming}


def msg_get_powers(llming: str = "") -> dict[str, Any]:
    return {"type": "get_powers", "id": _id(), "llming": llming}


def msg_viewer_connect(session_id: str) -> dict[str, Any]:
    return {"type": "viewer_connect", "id": _id(), "session_id": session_id}


def msg_viewer_disconnect(session_id: str) -> dict[str, Any]:
    return {"type": "viewer_disconnect", "id": _id(), "session_id": session_id}


def msg_set_credential(key: str, value: str) -> dict[str, Any]:
    return {"type": "set_credential", "id": _id(), "key": key, "value": value}


# ── Message types: Subprocess → Main (responses) ──

def msg_result(request_id: str, value: Any) -> dict[str, Any]:
    return {"type": "result", "id": request_id, "value": value}


def msg_error(request_id: str, error: str) -> dict[str, Any]:
    return {"type": "error", "id": request_id, "error": error}


# ── Message types: Subprocess → Main (events) ──

def msg_register_powers(powers: list[dict[str, Any]], llming: str = "") -> dict[str, Any]:
    return {"type": "register_powers", "powers": powers, "llming": llming}


def msg_pulse_emit(event: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"type": "pulse_emit", "event": event, "data": data}


def msg_log(level: str, message: str) -> dict[str, Any]:
    return {"type": "log", "level": level, "message": message}


def msg_ready() -> dict[str, Any]:
    return {"type": "ready"}


# ── Power serialization ──

def power_to_dict(power: Any) -> dict[str, Any]:
    """Serialize a Power dataclass for IPC transport."""
    from pydantic import BaseModel

    input_schema = power.input_schema
    if isinstance(input_schema, type) and issubclass(input_schema, BaseModel):
        input_schema = input_schema.model_json_schema()

    output_schema = power.output_schema
    if isinstance(output_schema, type) and issubclass(output_schema, BaseModel):
        output_schema = output_schema.model_json_schema()

    return {
        "name": power.name,
        "type": power.type.value,
        "description": power.description,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "admin_only": power.admin_only,
    }


def dict_to_power(d: dict[str, Any]) -> Any:
    """Deserialize a dict back to a Power dataclass."""
    from hort.llming.powers import Power, PowerType

    return Power(
        name=d["name"],
        type=PowerType(d["type"]),
        description=d["description"],
        input_schema=d.get("input_schema", {"type": "object", "properties": {}}),
        output_schema=d.get("output_schema"),
        admin_only=d.get("admin_only", False),
    )


def _id() -> str:
    return uuid.uuid4().hex[:12]
