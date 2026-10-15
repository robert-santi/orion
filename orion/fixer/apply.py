"""Aplica o plano só depois do ponto de restauração. Se o ponto falha, para."""

from __future__ import annotations

import json
from pathlib import Path

from orion.fixer.actions import HANDLERS, apply_fix
from orion.fixer.changelog import ChangeLog, latest_backup, restore_backup
from orion.fixer.restore import create_restore_point


def apply_plan(plan: dict) -> dict:
    if plan.get("kind") == "debloat":
        from orion.fixer.debloat import apply_debloat

        return apply_debloat(plan)
    steps = []
    ok, message = create_restore_point("ORION antes da otimizacao")
    steps.append({"id": "restore_point", "ok": ok, "message": message})
    if not ok:
        return {"ok": False, "aborted": True, "reboot": False, "steps": steps, "backup": ""}
    changelog = ChangeLog()
    reboot = False
    failed = False
    for fix_id in plan.get("fix_ids") or []:
        if fix_id not in HANDLERS:
            steps.append({"id": fix_id, "ok": False, "message": "Correção desconhecida."})
            failed = True
            continue
        try:
            text, needs_reboot = apply_fix(fix_id, plan, changelog)
            reboot = reboot or needs_reboot
            steps.append({"id": fix_id, "ok": True, "message": text})
        except Exception as error:
            failed = True
            steps.append({"id": fix_id, "ok": False, "message": str(error)})
    backup = changelog.save({"steps": steps})
    return {
        "ok": not failed,
        "aborted": False,
        "reboot": reboot,
        "steps": steps,
        "backup": str(backup),
        "note": (
            "O ponto de restauração cobre registro e sistema. "
            "Arquivos de jogo em Documentos foram copiados na pasta de backup do ORION."
        ),
    }


def apply_file(plan_path: Path, result_path: Path) -> None:
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        result = apply_plan(plan)
    except Exception as error:
        result = {
            "ok": False,
            "aborted": True,
            "reboot": False,
            "steps": [{"id": "erro", "ok": False, "message": str(error)}],
            "backup": "",
        }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def revert_last() -> dict:
    folder = latest_backup()
    if folder is None:
        return {"ok": False, "aborted": True, "steps": [{"id": "backup", "ok": False, "message": "Não há backup do ORION para desfazer."}]}
    ok, message = create_restore_point("ORION antes de desfazer")
    if not ok:
        return {"ok": False, "aborted": True, "steps": [{"id": "restore_point", "ok": False, "message": message}]}
    try:
        lines = restore_backup(folder)
    except Exception as error:
        return {"ok": False, "aborted": False, "steps": [{"id": "revert", "ok": False, "message": str(error)}]}
    return {"ok": True, "aborted": False, "reboot": False, "steps": [{"id": "revert", "ok": True, "message": line} for line in lines]}
