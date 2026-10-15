"""ORION — diagnóstico de FPS. Duplo clique no atalho ou: python main.py"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _arg(flag: str) -> Path | None:
    if flag not in sys.argv:
        return None
    index = sys.argv.index(flag)
    if index + 1 >= len(sys.argv):
        raise SystemExit(f"Faltou o caminho depois de {flag}.")
    return Path(sys.argv[index + 1])


def main() -> None:
    from orion.paths import setup_logging

    setup_logging()
    if "--selftest" in sys.argv:
        from orion.selftest import run_selftest

        raise SystemExit(run_selftest())
    if "--apply" in sys.argv:
        from orion.fixer.apply import apply_file

        plan = _arg("--apply")
        result = _arg("--result")
        if plan is None or result is None:
            raise SystemExit("Uso: --apply plano.json --result saida.json")
        apply_file(plan, result)
        return
    if "--revert" in sys.argv:
        from orion.fixer.apply import revert_last

        result = _arg("--revert")
        if result is None:
            raise SystemExit("Uso: --revert saida.json")
        result.write_text(json.dumps(revert_last(), ensure_ascii=False, indent=2), encoding="utf-8")
        return
    from orion.ui.app import run

    run()


if __name__ == "__main__":
    main()
