"""Leituras do dia a dia. Não altera o PC e não entra na pasta de outro usuário."""

from __future__ import annotations

import os
import re
import time
import winreg
from datetime import datetime, timedelta
from pathlib import Path

from orion.models import Snapshot
from orion.winutil import as_list, run_hidden, run_powershell_json

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
LOCKED_STARTUP = ("securityhealth", "windowsdefender", "msmpeng", "windowsupdate", "wuauserv", "defender")
QUIET_UNINSTALL = ("/quiet", "/qn", "/silent", "-silent", " /s", "/s ")
USE_MODES = {"jogos", "escritorio", "leve", "compartilhado"}
USE_LABELS = {
    "jogos": "Jogos",
    "escritorio": "Escritório",
    "leve": "Uso leve",
    "compartilhado": "PC compartilhado",
}

_STATUS_SCRIPT = r"""
$defender = @{ ok = $false; realtime = $false; antivirus = $false; message = 'Nao foi possivel ler o Defender.' }
try {
  $mp = Get-MpComputerStatus
  $defender = @{ ok = $true; realtime = [bool]$mp.RealTimeProtectionEnabled; antivirus = [bool]$mp.AntivirusEnabled; message = '' }
} catch {}
$wu = 'nao lido'
try { $wu = [string](Get-Service wuauserv -ErrorAction Stop).Status } catch {}
$points = @()
try {
  $points = @(Get-ComputerRestorePoint -ErrorAction Stop | Select-Object -Last 3 | ForEach-Object {
    @{ description = [string]$_.Description; when = $_.CreationTime.ToString('dd/MM/yyyy HH:mm') }
  })
} catch {}
$fast = $null
try {
  $fast = [int](Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -Name HiberbootEnabled -ErrorAction Stop).HiberbootEnabled
} catch {}
$drivers = @()
try {
  $drivers = @(Get-CimInstance Win32_PnPSignedDriver -ErrorAction Stop | Where-Object {
    $_.DeviceClass -in @('DISPLAY','NET','MEDIA') -and $_.DeviceName
  } | Select-Object -First 16 | ForEach-Object {
    $when = ''
    if ($_.DriverDate) { $when = $_.DriverDate.ToString('yyyy-MM-dd') }
    @{ name = [string]$_.DeviceName; version = [string]$_.DriverVersion; date = $when; klass = [string]$_.DeviceClass }
  })
} catch {}
$crashes = @()
try {
  $crashes = @(Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000; StartTime=(Get-Date).AddDays(-21)} -MaxEvents 8 -ErrorAction Stop | ForEach-Object {
    $line = ([string]$_.Message) -replace '\s+', ' '
    if ($line.Length -gt 180) { $line = $line.Substring(0, 180) }
    @{ when = $_.TimeCreated.ToString('dd/MM/yyyy HH:mm'); message = $line }
  })
} catch {}
$bright = $null
try {
  $bright = [int](Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop | Select-Object -First 1).CurrentBrightness
} catch {}
$adapter = ''
try {
  $adapter = [string](Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop | Sort-Object RouteMetric | Select-Object -First 1).InterfaceAlias
} catch {}
$sleep = $null
try {
  foreach ($line in @(powercfg /q SCHEME_CURRENT SUB_SLEEP STANDBYIDLE)) {
    if ($line -match 'Alternadas Atuais:\s*0x([0-9a-fA-F]+)' -or $line -match 'Current AC Power Setting Index:\s*0x([0-9a-fA-F]+)') {
      $sleep = [int]([convert]::ToInt32($Matches[1], 16) / 60)
    }
  }
} catch {}
$recycle = @{ ok = $false; count = 0; bytes = 0 }
try {
  $shell = New-Object -ComObject Shell.Application
  $bin = $shell.NameSpace(10)
  $count = 0
  $bytes = [int64]0
  foreach ($item in @($bin.Items())) {
    $count++
    $size = 0
    try { $size = [int64]$item.Size } catch {}
    $bytes += $size
  }
  $recycle = @{ ok = $true; count = $count; bytes = $bytes }
} catch {}
@{
  defender = $defender
  windows_update = $wu
  restore_points = @($points)
  fast_startup = $fast
  drivers = @($drivers)
  crashes = @($crashes)
  brightness = $bright
  default_adapter = $adapter
  sleep_minutes = $sleep
  recycle = $recycle
} | ConvertTo-Json -Depth 6 -Compress | Out-File -FilePath '__OUT__' -Encoding utf8
"""


def normalize_use_mode(value: str) -> str:
    text = (value or "").strip()
    return text if text in USE_MODES else "jogos"


def format_bytes(size: int) -> str:
    value = max(0, int(size))
    if value >= 1024**3:
        return f"{value / 1024**3:.1f} GB"
    if value >= 1024**2:
        return f"{value / 1024**2:.0f} MB"
    if value >= 1024:
        return f"{value / 1024:.0f} KB"
    return f"{value} B"


def user_home() -> Path:
    return Path.home().resolve()


def is_foreign_profile(path: Path) -> bool:
    parts = list(path.parts)
    lower = [part.lower() for part in parts]
    if "users" not in lower:
        return False
    index = lower.index("users")
    if index + 1 >= len(parts):
        return False
    name = parts[index + 1].lower()
    return name not in {user_home().name.lower(), "public", "default", "default user", "all users"}


def cleanup_root_kind(path: Path) -> str:
    """temp, user ou steam. Vazio significa que a limpeza deve recusar o caminho."""
    try:
        resolved = path.resolve()
    except OSError:
        return ""
    if is_foreign_profile(resolved):
        return ""
    try:
        resolved.relative_to(user_home())
        under = True
    except ValueError:
        under = False
    if under:
        if resolved.name.lower() == "temp" and resolved.parent.name.lower() == "local":
            return "temp"
        if resolved.name.lower() in {"d3dscache", "dxcache", "glcache"}:
            return "user"
        return ""
    lower = [part.lower() for part in resolved.parts]
    if "steamapps" in lower and "shadercache" in lower and resolved.name.isdigit():
        return "steam"
    return ""


def _walk_budget(root: Path, budget_s: float, max_files: int, large_min: int) -> tuple[int, bool, list[tuple[int, Path]]]:
    started = time.monotonic()
    total = 0
    seen = 0
    partial = False
    large: list[tuple[int, Path]] = []
    if not root.is_dir():
        return 0, False, []
    stack = [root]
    while stack:
        current = stack.pop()
        if time.monotonic() - started > budget_s or seen >= max_files:
            partial = True
            break
        try:
            iterator = os.scandir(current)
        except OSError:
            continue
        with iterator:
            for entry in iterator:
                seen += 1
                if seen % 40 == 0:
                    time.sleep(0)
                    if time.monotonic() - started > budget_s or seen >= max_files:
                        partial = True
                        break
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
                total += size
                if size >= large_min:
                    large.append((size, Path(entry.path)))
            if partial:
                break
    large.sort(key=lambda item: item[0], reverse=True)
    return total, partial, large[:12]


def _folder_row(label: str, path: Path, budget_s: float = 2.2) -> dict:
    if is_foreign_profile(path):
        return {"label": label, "path": "", "bytes": 0, "partial": False, "exists": False, "refused": True}
    size, partial, _large = _walk_budget(path, budget_s, 6000, 250 * 1024**2)
    return {
        "label": label,
        "path": str(path),
        "bytes": size,
        "partial": partial,
        "exists": path.is_dir(),
        "refused": False,
    }


def folder_map() -> tuple[list[dict], list[dict]]:
    home = user_home()
    temp = Path(os.environ.get("TEMP") or (home / "AppData" / "Local" / "Temp"))
    specs = (
        ("Downloads", home / "Downloads", 1.4, True),
        ("Vídeos", home / "Videos", 1.6, True),
        ("Imagens", home / "Pictures", 1.0, False),
        ("Área de trabalho", home / "Desktop", 0.8, True),
        ("Documentos", home / "Documents", 1.4, True),
        ("Temp deste usuário", temp, 0.8, False),
    )
    rows = []
    large: list[dict] = []
    for label, folder, budget, keep_large in specs:
        if is_foreign_profile(folder):
            rows.append({"label": label, "path": "", "bytes": 0, "partial": False, "exists": False, "refused": True})
            continue
        size, partial, found = _walk_budget(folder, budget, 2500, 250 * 1024**2)
        rows.append(
            {
                "label": label,
                "path": str(folder),
                "bytes": size,
                "partial": partial,
                "exists": folder.is_dir(),
                "refused": False,
            }
        )
        if not keep_large:
            continue
        for file_size, path in found:
            if is_foreign_profile(path):
                continue
            large.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "folder": str(path.parent),
                    "bytes": file_size,
                    "partial": partial,
                }
            )
    large.sort(key=lambda item: item["bytes"], reverse=True)
    return rows, large[:8]


def shader_targets(games: list) -> list[dict]:
    home = user_home()
    local = Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
    found: list[dict] = []
    candidates = [
        ("Cache DirectX deste usuário", local / "D3DSCache", "user"),
        ("Cache NVIDIA deste usuário", local / "NVIDIA" / "DXCache", "user"),
        ("Cache OpenGL da NVIDIA deste usuário", local / "NVIDIA" / "GLCache", "user"),
        ("Cache AMD deste usuário", local / "AMD" / "DxCache", "user"),
        ("Cache OpenGL da AMD deste usuário", local / "AMD" / "GLCache", "user"),
    ]
    seen: set[str] = set()
    for game in games or []:
        install = Path(getattr(game, "install_dir", "") or "")
        app_id = str(getattr(game, "app_id", "") or "")
        if not app_id.isdigit() or not install:
            continue
        lower = [part.lower() for part in install.parts]
        if "steamapps" not in lower:
            continue
        index = lower.index("steamapps")
        target = Path(*install.parts[: index + 1]) / "shadercache" / app_id
        key = str(target).lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append((f"Shader da Steam: {getattr(game, 'name', app_id)}", target, "steam"))
    for label, path, scope in candidates:
        if cleanup_root_kind(path) not in {"user", "steam"}:
            continue
        if not path.is_dir():
            continue
        size, partial, _large = _walk_budget(path, 1.2, 4000, 10**12)
        found.append({"label": label, "path": str(path), "bytes": size, "partial": partial, "scope": scope})
    return found


def _exe_size(command: str) -> int:
    match = re.search(r'"([^"]+\.exe)"', command, re.IGNORECASE) or re.search(r"([^\s]+\.exe)", command, re.IGNORECASE)
    if not match:
        return 0
    path = Path(match.group(1))
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def startup_locked(name: str, command: str) -> bool:
    folded = f"{name} {command}".lower()
    return any(token in folded for token in LOCKED_STARTUP)


def startup_rows(snapshot: Snapshot | None) -> list[dict]:
    items = list(snapshot.startups) if snapshot is not None else []
    if not items:
        from orion.scanner.processes import read_startups

        try:
            items = read_startups()
        except OSError:
            items = []
    rows = []
    for item in items:
        user_scope = item.location == "HKCU Run"
        locked = startup_locked(item.name, item.command)
        rows.append(
            {
                "name": item.name,
                "command": item.command,
                "location": item.location,
                "heavy": bool(item.heavy),
                "bytes": _exe_size(item.command),
                "user_scope": user_scope,
                "locked": locked,
                "can_disable": user_scope and not locked,
            }
        )
    return rows


def _uninstall_keys() -> list[tuple[int, str]]:
    return [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]


def installed_programs() -> list[dict]:
    rows: dict[str, dict] = {}
    for root, path in _uninstall_keys():
        try:
            key = winreg.OpenKey(root, path)
        except OSError:
            continue
        try:
            count = winreg.QueryInfoKey(key)[0]
            for index in range(count):
                try:
                    subname = winreg.EnumKey(key, index)
                    with winreg.OpenKey(key, subname) as sub:
                        name = _reg_str(sub, "DisplayName")
                        if not name or _reg_dword(sub, "SystemComponent") == 1:
                            continue
                        if _reg_str(sub, "ParentDisplayName") or _reg_str(sub, "ReleaseType"):
                            continue
                        size_kb = _reg_dword(sub, "EstimatedSize")
                        uninstall = _reg_str(sub, "UninstallString")
                        quiet = any(token in uninstall.lower() for token in QUIET_UNINSTALL)
                        stamp = _reg_str(sub, "InstallDate")
                        when = ""
                        if len(stamp) == 8 and stamp.isdigit():
                            when = f"{stamp[6:8]}/{stamp[4:6]}/{stamp[0:4]}"
                        current = rows.get(name.lower())
                        candidate = {
                            "name": name,
                            "version": _reg_str(sub, "DisplayVersion"),
                            "publisher": _reg_str(sub, "Publisher"),
                            "bytes": int(size_kb or 0) * 1024,
                            "when": when,
                            "uninstall": uninstall,
                            "quiet": quiet or not uninstall,
                        }
                        if current is None or candidate["bytes"] > current["bytes"]:
                            rows[name.lower()] = candidate
                except OSError:
                    continue
        finally:
            key.Close()
    ordered = sorted(rows.values(), key=lambda item: item["bytes"], reverse=True)
    return ordered[:40]


def _reg_str(key, name: str) -> str:
    try:
        value, _kind = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return str(value or "").strip()


def _reg_dword(key, name: str) -> int:
    try:
        value, kind = winreg.QueryValueEx(key, name)
    except OSError:
        return 0
    if kind == winreg.REG_DWORD:
        return int(value)
    return 0


def uninstall_is_visible(command: str) -> bool:
    text = (command or "").lower()
    return bool(text) and not any(token in text for token in QUIET_UNINSTALL)


def _windows_status() -> dict:
    import tempfile

    out = Path(tempfile.gettempdir()) / "orion-care.json"
    script = _STATUS_SCRIPT.replace("__OUT__", str(out))
    return run_powershell_json(script, out, timeout=55)


def _dpi() -> int | None:
    try:
        value = int(ctypes_dpi())
    except (OSError, ValueError):
        return None
    return value if value > 0 else None


def ctypes_dpi() -> int:
    import ctypes

    return int(ctypes.windll.user32.GetDpiForSystem())


def _battery() -> dict | None:
    try:
        import psutil

        battery = psutil.sensors_battery()
    except (OSError, ImportError):
        return None
    if battery is None:
        return None
    return {"percent": int(battery.percent), "plugged": bool(battery.power_plugged)}


def _vpn_names(adapters: list[dict]) -> list[str]:
    tokens = ("vpn", "radmin", "tap", "wintun", "wireguard", "openvpn", "tailscale", "zerotier")
    names = []
    for adapter in adapters:
        name = str(adapter.get("name") or "")
        if any(token in name.lower() for token in tokens):
            names.append(name)
    return names


def _driver_rows(raw: list) -> list[dict]:
    limit = datetime.now() - timedelta(days=540)
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        when = str(item.get("date") or "")
        parsed = None
        try:
            parsed = datetime.strptime(when, "%Y-%m-%d") if when else None
        except ValueError:
            parsed = None
        old = bool(parsed and parsed < limit)
        rows.append(
            {
                "name": str(item.get("name") or ""),
                "version": str(item.get("version") or ""),
                "date": when,
                "klass": str(item.get("klass") or ""),
                "old": old,
            }
        )
    return rows


def collect_care(snapshot: Snapshot | None = None) -> dict:
    folders, large = folder_map()
    games = list(snapshot.games) if snapshot is not None else []
    status: dict = {}
    status_error = ""
    try:
        status = _windows_status()
    except Exception as error:
        status_error = str(error)
    adapters = list(snapshot.adapters) if snapshot is not None else []
    disks = []
    if snapshot is not None:
        for disk in snapshot.disks:
            disks.append(
                {
                    "letter": disk.letter,
                    "media": disk.media,
                    "name": disk.name,
                    "free_gb": disk.free_gb,
                    "total_gb": disk.total_gb,
                    "free_percent": round(disk.free_percent, 1),
                }
            )
    dpi = _dpi()
    return {
        "folders": folders,
        "large": large,
        "shaders": shader_targets(games),
        "startups": startup_rows(snapshot),
        "programs": installed_programs(),
        "status_error": status_error,
        "defender": status.get("defender") if isinstance(status.get("defender"), dict) else {},
        "windows_update": str(status.get("windows_update") or ""),
        "restore_points": [item for item in as_list(status.get("restore_points")) if isinstance(item, dict)],
        "fast_startup": status.get("fast_startup"),
        "drivers": _driver_rows(as_list(status.get("drivers"))),
        "crashes": [item for item in as_list(status.get("crashes")) if isinstance(item, dict)],
        "brightness": status.get("brightness"),
        "default_adapter": str(status.get("default_adapter") or ""),
        "sleep_minutes": status.get("sleep_minutes"),
        "recycle": status.get("recycle") if isinstance(status.get("recycle"), dict) else {},
        "dpi": dpi,
        "scale": round(dpi / 96, 2) if dpi else None,
        "battery": _battery(),
        "vpn": _vpn_names(adapters),
        "adapters": adapters,
        "disks": disks,
        "network": list(snapshot.network) if snapshot is not None else [],
        "pending_reboot": bool(snapshot.pending_reboot) if snapshot is not None else False,
        "power_plan": snapshot.power_plan if snapshot is not None else "",
    }


def compare_history(rows: list[dict]) -> dict:
    if len(rows) < 2:
        return {"ok": False, "message": "Faça mais uma verificação para comparar com a anterior."}
    current, previous = rows[0], rows[1]
    now = {str(item.get("title") or "") for item in current.get("issues") or [] if isinstance(item, dict)}
    before = {str(item.get("title") or "") for item in previous.get("issues") or [] if isinstance(item, dict)}
    now.discard("")
    before.discard("")
    return {
        "ok": True,
        "score_now": current.get("score"),
        "score_prev": previous.get("score"),
        "when_now": current.get("scanned_at") or "",
        "when_prev": previous.get("scanned_at") or "",
        "added": sorted(now - before),
        "gone": sorted(before - now),
    }


def render_report(snapshot: Snapshot, analysis, verdict, use_mode: str) -> str:
    lines = [
        "ORION — leitura deste computador",
        snapshot.scanned_at,
        "",
        f"Nota: {analysis.score}/100",
        analysis.headline,
        verdict.summary,
        "",
        f"Uso escolhido: {USE_LABELS.get(normalize_use_mode(use_mode), 'Jogos')}",
        f"Processador: {snapshot.cpu_name.strip()}",
        f"Memória livre: {snapshot.ram_available_gb:.1f} GB de {snapshot.ram_total_gb:.1f} GB",
        f"Energia: {snapshot.power_plan or 'não lida'}",
    ]
    if snapshot.gpus:
        lines.append(f"Placa: {snapshot.gpus[0].name}")
    if snapshot.displays:
        screen = next((item for item in snapshot.displays if item.primary), snapshot.displays[0])
        lines.append(f"Tela: {screen.width}x{screen.height} @{screen.hz} Hz")
    lines.append("")
    lines.append("Discos")
    for disk in snapshot.disks:
        lines.append(f"- {disk.letter}: {disk.media} {disk.free_gb:.0f} GB livres de {disk.total_gb:.0f} GB ({disk.name})")
    lines.append("")
    lines.append("Pontos de atenção")
    issues = [issue for issue in snapshot.issues if issue.severity != "info"]
    if not issues:
        lines.append("- Nenhum ponto de atenção nesta leitura.")
    for issue in issues:
        lines.append(f"- [{issue.severity}] {issue.title}")
        lines.append(f"  {issue.impact}")
    lines.append("")
    lines.append("O que já está bem")
    if not snapshot.healthy:
        lines.append("- Sem itens saudáveis registrados.")
    for line in snapshot.healthy:
        lines.append(f"- {line}")
    lines.append("")
    lines.append("Rede (ping, não é FPS)")
    if not snapshot.network:
        lines.append("- A rede não foi medida nesta leitura.")
    for item in snapshot.network:
        label = item.get("label") or item.get("host")
        if item.get("ok"):
            lines.append(f"- {label}: {item.get('avg_ms')} ms")
        elif item.get("blocked"):
            lines.append(f"- {label}: não respondeu ao ping. Isso não descreve o FPS.")
        else:
            lines.append(f"- {label}: sem resposta")
    lines.append("")
    lines.append(f"Jogos encontrados: {len(snapshot.games)}")
    lines.append("Outras contas deste computador não entram nas pastas lidas pelo ORION.")
    return "\n".join(lines) + "\n"


def ping_line(result: dict) -> str:
    label = result.get("label") or result.get("host") or "Rede"
    if result.get("ok"):
        return f"{label}: {result.get('avg_ms')} ms"
    if result.get("blocked"):
        return f"{label}: não respondeu ao ping. Isso não descreve o FPS."
    return f"{label}: sem resposta"
