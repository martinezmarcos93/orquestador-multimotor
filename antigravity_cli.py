"""Adaptador mínimo y aislado para Google Antigravity CLI (agy).

Usa el modo headless documentado y exige una respuesta JSON final válida. No omite
permisos de herramientas. --sandbox se solicita explícitamente, pero su eficacia
depende de la versión y de la disponibilidad del sandbox del sistema anfitrión.
"""
from __future__ import annotations

import json
from typing import Any


def construir_comando(prompt: str, timeout_min: int, *, model: str | None = None,
                      effort: str | None = None, sandbox: bool = True) -> list[str]:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("el prompt de Antigravity no puede estar vacío")
    if not isinstance(timeout_min, int) or isinstance(timeout_min, bool) or timeout_min < 1:
        raise ValueError("timeout_min debe ser un entero positivo")
    cmd = ["agy", "--print", prompt, "--output-format", "json",
           "--print-timeout", f"{timeout_min}m"]
    if model:
        cmd.extend(["--model", model])
    if effort:
        if effort not in ("low", "medium", "high"):
            raise ValueError("effort debe ser low, medium o high")
        cmd.extend(["--effort", effort])
    if sandbox:
        cmd.append("--sandbox")
    return cmd


def interpretar_resultado(stdout: str, returncode: int, timeout: bool = False) -> dict[str, Any]:
    """Normaliza el sobre JSON de agy; un proceso cero no basta si el estado no es SUCCESS."""
    if timeout:
        return {"ok": False, "status": "TIMEOUT", "error": "Antigravity excedió el timeout"}
    try:
        envelope = json.loads(stdout)
    except (TypeError, json.JSONDecodeError):
        return {"ok": False, "status": "INVALID_OUTPUT",
                "error": "agy no devolvió un sobre JSON válido"}
    if not isinstance(envelope, dict):
        return {"ok": False, "status": "INVALID_OUTPUT",
                "error": "el sobre JSON de agy no es un objeto"}
    status = envelope.get("status")
    response = envelope.get("response")
    denied_actions = envelope.get("denied_actions")
    if not isinstance(denied_actions, list):
        denied_actions = []
    if denied_actions:
        return {"ok": False, "status": "SUCCESS", "motivo": "permisos_denegados",
                "denied_actions": denied_actions,
                "conversation_id": envelope.get("conversation_id"),
                "usage": envelope.get("usage")}
    if returncode != 0 or status != "SUCCESS":
        return {"ok": False, "status": str(status or "PROCESS_ERROR"),
                "error": str(envelope.get("error") or f"agy terminó con código {returncode}"),
                "conversation_id": envelope.get("conversation_id"),
                "usage": envelope.get("usage")}
    if not isinstance(response, str) or not response.strip():
        return {"ok": False, "status": "INVALID_OUTPUT",
                "error": "agy indicó SUCCESS pero no devolvió response textual",
                "conversation_id": envelope.get("conversation_id"),
                "usage": envelope.get("usage"), "denied_actions": denied_actions}
    return {"ok": True, "status": "SUCCESS", "response": response,
            "conversation_id": envelope.get("conversation_id"),
            "usage": envelope.get("usage"),
            "duration_seconds": envelope.get("duration_seconds"),
            "num_turns": envelope.get("num_turns")}
