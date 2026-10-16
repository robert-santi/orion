"""Configuração e histórico locais. Nada daqui chama um serviço externo."""

from __future__ import annotations

import json
from datetime import datetime

from orion.models import Snapshot
from orion.paths import config_path, history_dir

DEFAULTS = {
    "git_url": "",
    "git_branch": "main",
    "auto_update": True,
    "git_token": "",
    "profile_override": "",
    "use_mode": "jogos",
}
OVERRIDES = {"", "fraco", "equilibrado", "forte"}


def load_config() -> dict:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    if "xai_api_key" in data:
        data.pop("xai_api_key", None)
        save_config(data)
    return data


def save_config(data: dict) -> None:
    data.pop("xai_api_key", None)
    config_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_settings() -> dict:
    data = load_config()
    override = str(data.get("profile_override") or "")
    branch = str(data.get("git_branch") or "main").strip() or "main"
    if "auto_update" in data:
        auto_update = bool(data.get("auto_update"))
    else:
        auto_update = True
    return {
        "git_url": str(data.get("git_url") or "").strip(),
        "git_branch": branch,
        "auto_update": auto_update,
        "git_token": str(data.get("git_token") or "").strip(),
        "profile_override": override if override in OVERRIDES else "",
        "use_mode": normalize_use(str(data.get("use_mode") or "")),
    }


def save_settings(settings: dict) -> None:
    data = load_config()
    if "git_url" in settings:
        data["git_url"] = str(settings.get("git_url") or "").strip()
    if "git_branch" in settings:
        data["git_branch"] = str(settings.get("git_branch") or "main").strip() or "main"
    if "git_token" in settings:
        data["git_token"] = str(settings.get("git_token") or "").strip()
    if "auto_update" in settings:
        data["auto_update"] = bool(settings.get("auto_update"))
    if "profile_override" in settings:
        override = str(settings.get("profile_override") or "")
        data["profile_override"] = override if override in OVERRIDES else ""
    if "use_mode" in settings:
        data["use_mode"] = normalize_use(str(settings.get("use_mode") or ""))
    save_config(data)


def normalize_use(value: str) -> str:
    from orion.scanner.care import normalize_use_mode

    return normalize_use_mode(value)


def save_history(snapshot: Snapshot, score: int, headline: str, profile: str = "") -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    payload = {
        "scanned_at": snapshot.scanned_at,
        "score": score,
        "headline": headline,
        "profile": profile,
        "games": [game.name for game in snapshot.games],
        "issues": [
            {"severity": issue.severity, "title": issue.title, "fix_id": issue.fix_id}
            for issue in snapshot.issues
        ],
    }
    (history_dir() / f"{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    files = sorted(history_dir().glob("*.json"))
    for old in files[:-20]:
        old.unlink(missing_ok=True)


def list_history() -> list[dict]:
    rows = []
    for path in sorted(history_dir().glob("*.json"), reverse=True):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows
