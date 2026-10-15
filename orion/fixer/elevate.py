"""Pede administrador só na hora de escrever no sistema."""

from __future__ import annotations

import ctypes
import sys

from orion.paths import app_root
from orion.winutil import is_admin


def launch_elevated(argument_tail: str) -> tuple[bool, str]:
    if is_admin():
        return False, "Já está elevado."
    shell32 = ctypes.windll.shell32
    shell32.ShellExecuteW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_int,
    ]
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    if getattr(sys, "frozen", False):
        target = sys.executable
        params = argument_tail
    else:
        target = sys.executable
        params = f'"{app_root() / "main.py"}" {argument_tail}'
    result = shell32.ShellExecuteW(None, "runas", target, params, str(app_root()), 1)
    if result is None or int(result) <= 32:
        return False, "A permissão de administrador foi cancelada. Nada foi alterado."
    return True, "Processo elevado iniciado."
