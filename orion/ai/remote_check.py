"""Verificação por serviço externo. A tela não mostra conversa nem o nome do serviço."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from orion.store import load_config

log = logging.getLogger("orion")

_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
)
_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def service_key() -> str:
    env = os.environ.get("ORION_SERVICE_KEY", "").strip()
    if env:
        return env
    return str(load_config().get("service_key") or "").strip()


def configured() -> bool:
    return bool(service_key()) and os.environ.get("ORION_SKIP_REMOTE") != "1"


def _redact(text: str, key: str) -> str:
    if key and text:
        return text.replace(key, "••••")
    return text


def complete(prompt: str, timeout: int = 25) -> str:
    key = service_key()
    if not key or os.environ.get("ORION_SKIP_REMOTE") == "1":
        return ""
    body = json.dumps(
        {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 500,
                "responseMimeType": "application/json",
            },
        }
    ).encode("utf-8")
    last = ""
    for model in _MODELS:
        request = urllib.request.Request(
            _URL.format(model=model),
            data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = _redact(error.read().decode("utf-8", "replace")[:240], key)
            last = f"{error.code} {detail}"
            if error.code in {400, 404, 429, 503}:
                continue
            log.info("verificacao remota indisponivel: %s", last)
            return ""
        except Exception as error:
            log.info("verificacao remota indisponivel: %s", _redact(str(error), key))
            return ""
        parts: list[str] = []
        for candidate in payload.get("candidates") or []:
            content = candidate.get("content") or {}
            for part in content.get("parts") or []:
                text = part.get("text")
                if text:
                    parts.append(text)
        text = "\n".join(parts).strip()
        if text:
            log.info("verificacao remota concluida")
            return text
    if last:
        log.info("verificacao remota indisponivel: %s", last)
    return ""
