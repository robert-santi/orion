"""Pastas do aplicativo. Tudo fica dentro da pasta do projeto ou do .exe."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_path(*parts: str) -> Path:
    """Arquivo empacotado. No .exe vem da pasta extraída; no código, da raiz do projeto."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).joinpath(*parts)
    return Path(__file__).resolve().parents[1].joinpath(*parts)


def data_dir() -> Path:
    path = app_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def history_dir() -> Path:
    path = data_dir() / "history"
    path.mkdir(parents=True, exist_ok=True)
    return path


def backup_dir() -> Path:
    path = data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return data_dir() / "config.json"


def models_dir() -> Path:
    path = data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def tools_dir() -> Path:
    path = data_dir() / "tools"
    path.mkdir(parents=True, exist_ok=True)
    return path


def updates_dir() -> Path:
    path = data_dir() / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def setup_logging() -> None:
    logging.basicConfig(
        filename=log_dir() / "orion.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
