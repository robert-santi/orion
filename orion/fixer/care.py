"""Ações da seção Cuidados. O ponto de restauração vem antes de qualquer escrita."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from orion.fixer.changelog import ChangeLog
from orion.fixer.restore import create_restore_point
from orion.scanner.care import RUN_KEY, cleanup_root_kind, startup_locked
from orion.scanner.processes import running_names
from orion.winutil import delete_value, read_value, run_hidden

GAME_BLOCK = {"cs2.exe", "rocketleague.exe"}


def apply_care(plan: dict) -> dict:
    steps = []
    ok, message = create_restore_point("ORION antes do cuidado")
    steps.append({"id": "restore_point", "ok": ok, "message": message})
    if not ok:
        return {"ok": False, "aborted": True, "reboot": False, "steps": steps, "backup": ""}
    if plan.get("only_restore"):
        return {
            "ok": True,
            "aborted": False,
            "reboot": False,
            "steps": steps,
            "backup": "",
            "note": "O ponto foi criado. Nenhuma outra mudança foi feita.",
        }
    changelog = ChangeLog()
    failed = False
    for label, action in (
        ("limpeza", _cleanup),
        ("inicializacao", _disable_startups),
        ("discord", _discord),
    ):
        try:
            text = action(plan, changelog)
        except Exception as error:
            failed = True
            steps.append({"id": label, "ok": False, "message": str(error)})
            continue
        if text:
            steps.append({"id": label, "ok": True, "message": text})
    backup = changelog.save({"steps": steps, "kind": "care"})
    return {
        "ok": not failed,
        "aborted": False,
        "reboot": False,
        "steps": steps,
        "backup": str(backup),
        "note": (
            "O ponto de restauração cobre registro e sistema. "
            "Arquivo temporário e cache de shader não voltam com esse ponto. "
            "A inicialização e a sobreposição do Discord podem ser desfeitas pelo backup do ORION."
        ),
    }


def _cleanup(plan: dict, changelog: ChangeLog) -> str:
    chosen = {str(item) for item in plan.get("cleanup") or []}
    if not chosen:
        return ""
    if "shader_user" in chosen or "shader_steam" in chosen:
        blocked = sorted(running_names() & GAME_BLOCK)
        if blocked:
            raise RuntimeError(
                "CS2 ou Rocket League está aberto. Feche o jogo antes de limpar. Nada foi apagado."
            )
    lines = []
    if "temp" in chosen:
        lines.append(_empty_temp())
    if "recycle" in chosen:
        lines.append(_empty_recycle())
    if "shader_user" in chosen or "shader_steam" in chosen:
        scopes = set()
        if "shader_user" in chosen:
            scopes.add("user")
        if "shader_steam" in chosen:
            scopes.add("steam")
        lines.append(_empty_shaders(plan.get("shader_paths") or [], scopes))
    return " ".join(line for line in lines if line)


def _empty_temp() -> str:
    folder = Path(os.environ.get("TEMP") or "")
    if cleanup_root_kind(folder) != "temp":
        raise RuntimeError("A limpeza recusou a pasta Temp porque ela não é a deste usuário.")
    removed, skipped = _empty_directory(folder)
    return f"Temp: {removed} item(ns) removidos, {skipped} em uso."


def _empty_recycle() -> str:
    completed = run_hidden(
        ["powershell", "-NoProfile", "-Command", "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"],
        timeout=60,
    )
    if completed.returncode not in {0, None}:
        detail = (completed.stderr or completed.stdout or "").strip()
        if detail:
            return f"Lixeira deste usuário: o Windows respondeu {detail[:180]}"
    return "Lixeira deste usuário esvaziada. A lixeira de outras contas não entra nesse comando."


def _empty_shaders(raw_paths: list, scopes: set[str]) -> str:
    removed = 0
    skipped = 0
    used = 0
    for raw in raw_paths:
        folder = Path(str(raw))
        kind = cleanup_root_kind(folder)
        if kind not in scopes or not folder.is_dir():
            continue
        used += 1
        gone, kept = _empty_directory(folder)
        removed += gone
        skipped += kept
    if not used:
        return "Nenhuma pasta de shader marcada ainda existia."
    return (
        f"Shader: {removed} item(ns) removidos em {used} pasta(s), {skipped} em uso. "
        "A primeira partida pode engasgar enquanto o cache é refeito."
    )


def _empty_directory(folder: Path) -> tuple[int, int]:
    removed = 0
    skipped = 0
    for child in folder.iterdir():
        try:
            if child.is_symlink():
                skipped += 1
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            removed += 1
        except OSError:
            skipped += 1
    return removed, skipped


def _disable_startups(plan: dict, changelog: ChangeLog) -> str:
    names = [str(item) for item in plan.get("startup_names") or [] if str(item).strip()]
    if not names:
        return ""
    removed = []
    refused = []
    for name in names:
        existed, reg_type, value = read_value("HKCU", RUN_KEY, name)
        if not existed or reg_type is None:
            refused.append(name)
            continue
        if startup_locked(name, str(value)):
            refused.append(name)
            continue
        changelog.remember_startup("HKCU", RUN_KEY, name, reg_type, value)
        delete_value("HKCU", RUN_KEY, name)
        removed.append(name)
    text = ""
    if removed:
        text += "Inicialização deste usuário desligada: " + ", ".join(removed) + "."
    if refused:
        text += " Mantidos: " + ", ".join(refused) + "."
    if not text:
        return "Nenhum item de inicialização deste usuário foi alterado."
    return text.strip()


def _discord(plan: dict, changelog: ChangeLog) -> str:
    mode = str(plan.get("discord") or "")
    if mode not in {"on", "off"}:
        return ""
    path = Path(os.environ.get("APPDATA", "")) / "discord" / "settings.json"
    try:
        resolved = path.resolve()
    except OSError as error:
        raise RuntimeError(f"Configuração do Discord inacessível: {error}") from error
    home = Path.home().resolve()
    try:
        resolved.relative_to(home)
    except ValueError as error:
        raise RuntimeError("A configuração do Discord não está na pasta deste usuário.") from error
    if not resolved.is_file():
        return "Configuração do Discord não encontrada. Nada alterado nesse item."
    data = json.loads(resolved.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise RuntimeError("O arquivo do Discord não é um objeto.")
    data["enableOverlay"] = mode == "on"
    changelog.replace_file(resolved, json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    running = ""
    if "discord.exe" in running_names():
        running = " Feche e abra o Discord para ele ler o arquivo."
    if mode == "off":
        return "Sobreposição do Discord pausada." + running
    return "Sobreposição do Discord devolvida." + running
