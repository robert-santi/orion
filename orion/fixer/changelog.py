"""Guarda o valor anterior de cada registro e uma cópia de cada arquivo."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from orion.paths import backup_dir
from orion.winutil import TYPE_TO_WIN, WIN_TO_TYPE, delete_value, read_value, write_value


class ChangeLog:
    def __init__(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.folder = backup_dir() / stamp
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "files").mkdir(exist_ok=True)
        self.registry: list[dict[str, Any]] = []
        self.files: list[dict[str, str]] = []
        self.removed_startups: list[dict[str, Any]] = []
        self.extra: list[dict[str, Any]] = []

    def remember(self, kind: str, **payload: Any) -> None:
        item = {"kind": kind}
        item.update(payload)
        self.extra.append(item)

    def set_value(self, root: str, path: str, name: str, kind: str, value: Any) -> None:
        existed, reg_type, old = read_value(root, path, name)
        self.registry.append(
            {
                "root": root,
                "path": path,
                "name": name,
                "existed": existed,
                "type": WIN_TO_TYPE.get(reg_type or 0, ""),
                "value": old if not isinstance(old, bytes) else old.hex(),
            }
        )
        write_value(root, path, name, TYPE_TO_WIN[kind], value)

    def replace_file(self, path: Path, new_text: str, encoding: str) -> Path:
        target = self.folder / "files" / f"{len(self.files):02d}-{path.name}"
        shutil.copy2(path, target)
        path.write_bytes(new_text.encode(encoding))
        self.files.append({"path": str(path), "backup": str(target), "encoding": encoding})
        return target

    def remember_startup(self, root: str, path: str, name: str, reg_type: int, value: Any) -> None:
        self.removed_startups.append(
            {
                "root": root,
                "path": path,
                "name": name,
                "type": WIN_TO_TYPE.get(reg_type, "sz"),
                "value": value,
            }
        )

    def save(self, summary: dict[str, Any]) -> Path:
        payload = {
            "created": datetime.now().isoformat(timespec="seconds"),
            "registry": self.registry,
            "files": self.files,
            "startups": self.removed_startups,
            "extra": self.extra,
            "summary": summary,
        }
        destination = self.folder / "backup.json"
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return destination


def latest_backup() -> Path | None:
    folders = [path for path in backup_dir().glob("*") if (path / "backup.json").is_file()]
    if not folders:
        return None
    return max(folders, key=lambda path: path.name)


def restore_backup(folder: Path) -> list[str]:
    payload = json.loads((folder / "backup.json").read_text(encoding="utf-8"))
    messages: list[str] = []
    for item in payload.get("files") or []:
        source = Path(item["backup"])
        destination = Path(item["path"])
        if source.is_file():
            shutil.copy2(source, destination)
            messages.append(f"Arquivo restaurado: {destination.name}")
    for item in payload.get("registry") or []:
        if item.get("existed"):
            kind = item.get("type") or "dword"
            if kind not in TYPE_TO_WIN:
                kind = "sz"
            write_value(item["root"], item["path"], item["name"], TYPE_TO_WIN[kind], item.get("value"))
            messages.append(f"Registro restaurado: {item['name']}")
        else:
            delete_value(item["root"], item["path"], item["name"])
            messages.append(f"Registro removido: {item['name']}")
    for item in payload.get("startups") or []:
        kind = item.get("type") or "sz"
        write_value(item["root"], item["path"], item["name"], TYPE_TO_WIN[kind], item.get("value"))
        messages.append(f"Inicialização restaurada: {item['name']}")
    for item in payload.get("extra") or []:
        try:
            from orion.fixer.debloat import undo_extra

            messages.append(undo_extra(item))
        except Exception as error:
            messages.append(f"Não desfez {item.get('kind') or 'item'}: {error}")
    if not messages:
        messages.append("O backup não tinha alterações para desfazer.")
    return messages
