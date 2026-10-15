"""Chamadas pequenas ao Windows: registro, processo oculto e administrador."""

from __future__ import annotations

import ctypes
import json
import subprocess
from pathlib import Path
from typing import Any

CREATE_NO_WINDOW = 0x08000000

HKCU = 0x80000001
HKLM = 0x80000002
KEY_READ = 0x20019
KEY_WRITE = 0x20006
KEY_WOW64_64KEY = 0x0100

REG_DWORD = 4
REG_SZ = 1
REG_EXPAND_SZ = 2
REG_QWORD = 11

ROOTS = {"HKCU": HKCU, "HKLM": HKLM}
TYPE_TO_WIN = {"dword": REG_DWORD, "sz": REG_SZ, "expand": REG_EXPAND_SZ, "qword": REG_QWORD}
WIN_TO_TYPE = {value: key for key, value in TYPE_TO_WIN.items()}


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def run_hidden(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )


def run_powershell_json(script: str, out_path: Path, timeout: int = 60) -> dict[str, Any]:
    """Grava o JSON em arquivo UTF-8. O PowerShell 5.1 mistura codificações no console."""
    if out_path.exists():
        out_path.unlink()
    wrapped = (
        "$ErrorActionPreference = 'Stop'\n"
        f"{script}\n"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", wrapped],
        capture_output=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )
    if not out_path.exists():
        stderr = completed.stderr.decode("utf-8", errors="replace")
        stdout = completed.stdout.decode("utf-8", errors="replace")
        raise RuntimeError((stderr or stdout or "PowerShell não gerou o inventário.").strip())
    raw = out_path.read_text(encoding="utf-8-sig", errors="replace")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError("Inventário do Windows veio em formato inesperado.")
    return data


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def read_value(root_name: str, path: str, name: str) -> tuple[bool, int | None, Any]:
    root = ROOTS[root_name]
    try:
        with winreg_open(root, path, KEY_READ | KEY_WOW64_64KEY) as key:
            value, reg_type = ctypes_query(key, name)
            return True, reg_type, value
    except FileNotFoundError:
        return False, None, None
    except OSError:
        return False, None, None


def winreg_open(root: int, path: str, access: int):
    import winreg

    return winreg.OpenKey(root, path, 0, access)


def ctypes_query(key, name: str):
    import winreg

    return winreg.QueryValueEx(key, name)


def write_value(root_name: str, path: str, name: str, reg_type: int, value: Any) -> None:
    import winreg

    root = ROOTS[root_name]
    with winreg.CreateKeyEx(root, path, 0, KEY_WRITE | KEY_WOW64_64KEY) as key:
        winreg.SetValueEx(key, name, 0, reg_type, value)


def delete_value(root_name: str, path: str, name: str) -> None:
    import winreg

    root = ROOTS[root_name]
    try:
        with winreg.OpenKey(root, path, 0, KEY_WRITE | KEY_WOW64_64KEY) as key:
            winreg.DeleteValue(key, name)
    except FileNotFoundError:
        return
    except OSError:
        return
