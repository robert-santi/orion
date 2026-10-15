"""Cria um ponto de restauração antes de qualquer escrita no sistema."""

from __future__ import annotations

import tempfile
from pathlib import Path

from orion.winutil import run_powershell_json

# A frequência padrão do Windows bloqueia um segundo ponto em 24 horas.
# Sem zerar essa chave, a proteção que o usuário pediu falha em silêncio.
SCRIPT = r"""
New-Item -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore' -Force | Out-Null
New-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore' -Name 'SystemRestorePointCreationFrequency' -Value 0 -PropertyType DWord -Force | Out-Null
try { Enable-ComputerRestore -Drive 'C:\' | Out-Null } catch { }
Checkpoint-Computer -Description '__DESC__' -RestorePointType 'MODIFY_SETTINGS'
@{ ok = $true; message = 'Ponto de restauração criado.' } | ConvertTo-Json -Compress | Out-File -FilePath '__OUT__' -Encoding utf8
"""


def create_restore_point(description: str) -> tuple[bool, str]:
    safe = "".join(ch for ch in description if ch.isalnum() or ch in " -_.:")[:64] or "ORION antes da otimizacao"
    out = Path(tempfile.gettempdir()) / "orion-restore.json"
    script = SCRIPT.replace("__DESC__", safe).replace("__OUT__", str(out))
    try:
        data = run_powershell_json(script, out, timeout=180)
    except Exception as error:
        return False, f"O ponto de restauração não foi criado. Nada foi alterado. {error}"
    if data.get("ok"):
        return True, str(data.get("message") or "Ponto de restauração criado.")
    return False, "O Windows não confirmou o ponto de restauração. Nada foi alterado."
