"""Lê e altera só as chaves conhecidas de cfg/ini, preservando o resto do arquivo."""

from __future__ import annotations

import re
from pathlib import Path


def read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16"), "utf-16"
    if raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16-be"), "utf-16-be"
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("utf-16"), "utf-16"


def write_text(path: Path, text: str, encoding: str) -> None:
    path.write_bytes(text.encode(encoding))


def vdf_values(text: str, keys: set[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for key in keys:
        match = re.search(rf'"{re.escape(key)}"\s+"([^"]*)"', text)
        if match:
            found[key] = match.group(1)
    return found


def set_vdf_values(text: str, updates: dict[str, str]) -> str:
    for key, value in updates.items():
        pattern = rf'("{re.escape(key)}")(\s+")([^"]*)(")'
        replaced, count = re.subn(pattern, lambda m, v=value: f"{m.group(1)}{m.group(2)}{v}{m.group(4)}", text, count=1)
        if count:
            text = replaced
            continue
        insert = f'\t"{key}"\t\t"{value}"\n'
        stripped = text.rstrip()
        if stripped.endswith("}"):
            body = stripped[:-1].rstrip()
            newline = "\r\n" if "\r\n" in text else "\n"
            text = body + newline + insert + "}" + newline
        else:
            text = text + f'\n"{key}"\t\t"{value}"\n'
    return text


def ini_values(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in text.splitlines():
        body = line.strip()
        if not body or body.startswith((";", "#", "[")):
            continue
        if "=" not in body:
            continue
        key, value = body.split("=", 1)
        found[key.strip()] = value.strip()
    return found


def set_ini_values(text: str, updates: dict[str, str]) -> str:
    wanted = {key.lower(): (key, value) for key, value in updates.items()}
    seen: set[str] = set()
    output: list[str] = []
    for line in text.splitlines(keepends=True):
        newline = ""
        body = line
        if body.endswith("\r\n"):
            newline = "\r\n"
            body = body[:-2]
        elif body.endswith("\n"):
            newline = "\n"
            body = body[:-1]
        stripped = body.strip()
        if stripped and not stripped.startswith((";", "#", "[")) and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            replacement = wanted.get(key.lower())
            if replacement:
                output.append(f"{key}={replacement[1]}{newline or chr(10)}")
                seen.add(key.lower())
                continue
        output.append(line if newline or line.endswith("\n") else body)
        if line and not line.endswith(("\n", "\r\n")):
            output[-1] = body
    missing = [item for key, item in wanted.items() if key not in seen]
    if missing:
        if output and not str(output[-1]).endswith(("\n", "\r\n")):
            output[-1] = output[-1] + "\n"
        for key, value in missing:
            output.append(f"{key}={value}\n")
    return "".join(output)
