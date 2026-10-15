"""Latência e perda de pacote. Não mistura problema de internet com problema de FPS."""

from __future__ import annotations

import re

from orion.winutil import run_hidden

TARGETS = (
    ("Internet", "1.1.1.1"),
    ("Steam", "store.steampowered.com"),
    ("Epic", "epicgames.com"),
)


def ping(host: str) -> dict:
    completed = run_hidden(["ping", "-n", "3", "-w", "1000", host], timeout=12)
    text = f"{completed.stdout}\n{completed.stderr}"
    loss_match = re.search(r"\((\d+)\s*%", text)
    avg_match = re.search(r"(?:M[eé]dia|Average)\s*=\s*(\d+)\s*ms", text, re.IGNORECASE)
    loss = int(loss_match.group(1)) if loss_match else None
    average = int(avg_match.group(1)) if avg_match else None
    # Site que bloqueia ICMP aparece como 100% de perda. Isso não é a internet do usuário.
    blocked = average is None or loss == 100
    return {"host": host, "ok": average is not None and not blocked, "loss_percent": loss, "avg_ms": average, "blocked": blocked}


def probe() -> list[dict]:
    results = []
    for label, host in TARGETS:
        try:
            item = ping(host)
        except Exception as error:
            item = {"host": host, "ok": False, "loss_percent": None, "avg_ms": None, "error": str(error)}
        item["label"] = label
        results.append(item)
    return results
