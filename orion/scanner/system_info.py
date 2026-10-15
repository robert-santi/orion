"""Inventário do PC: processador, memória, placas, discos, energia e tela."""

from __future__ import annotations

import ctypes
import platform
import re
import socket
import tempfile
from datetime import datetime
from pathlib import Path

import psutil

from orion.models import DiskInfo, DisplayInfo, GpuInfo
from orion.scanner.profiles import gpu_vendor
from orion.winutil import as_list, read_value, run_hidden, run_powershell_json

INVENTORY_SCRIPT = r"""
$inv = [ordered]@{}
try {
  $os = Get-CimInstance Win32_OperatingSystem
  $boot = $os.LastBootUpTime
  $inv.os = @{
    Caption = [string]$os.Caption
    Version = [string]$os.Version
    LastBoot = $boot.ToString('o')
  }
} catch { $inv.os_error = $_.Exception.Message }
try {
  $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
  $inv.cpu = @{
    Name = [string]$cpu.Name
    Cores = [int]$cpu.NumberOfCores
    Threads = [int]$cpu.NumberOfLogicalProcessors
    MaxMHz = [int]$cpu.MaxClockSpeed
    CurrentMHz = [int]$cpu.CurrentClockSpeed
  }
} catch { $inv.cpu_error = $_.Exception.Message }
try {
  $inv.gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object {
    @{
      Name = [string]$_.Name
      DriverVersion = [string]$_.DriverVersion
      DriverDate = [string]$_.DriverDate
      PNPDeviceID = [string]$_.PNPDeviceID
    }
  })
} catch { $inv.gpus = @() }
try {
  $inv.memory = @(Get-CimInstance Win32_PhysicalMemory | ForEach-Object {
    @{ Speed = [int]$_.Speed; Capacity = [int64]$_.Capacity; Locator = [string]$_.DeviceLocator }
  })
} catch { $inv.memory = @() }
try {
  $board = Get-CimInstance Win32_BaseBoard | Select-Object -First 1
  $inv.board = (([string]$board.Manufacturer) + ' ' + ([string]$board.Product)).Trim()
} catch { $inv.board = '' }
try {
  # Get-Disk não preenche MediaType neste Windows. Get-PhysicalDisk preenche SSD/HDD.
  $inv.disks = @(Get-PhysicalDisk | ForEach-Object {
    @{
      Number = [int]$_.DeviceId
      Name = [string]$_.FriendlyName
      Bus = [string]$_.BusType
      Media = [string]$_.MediaType
      Health = [string]$_.HealthStatus
    }
  })
} catch { $inv.disks = @() }
try {
  $inv.parts = @(Get-Partition | Where-Object { $_.DriveLetter } | ForEach-Object {
    @{ Number = [int]$_.DiskNumber; Letter = [string]$_.DriveLetter }
  })
} catch { $inv.parts = @() }
try {
  $inv.adapters = @(Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | ForEach-Object {
    @{ Name = [string]$_.Name; Media = [string]$_.MediaType; Speed = [string]$_.LinkSpeed; Status = [string]$_.Status }
  })
} catch { $inv.adapters = @() }
try {
  $inv.pagefiles = @(Get-CimInstance Win32_PageFileUsage | ForEach-Object {
    @{ Name = [string]$_.Name; AllocatedMB = [int]$_.AllocatedBaseSize; UsedMB = [int]$_.CurrentUsage }
  })
} catch { $inv.pagefiles = @() }
try {
  $scheme = (powercfg /getactivescheme | Out-String).Trim()
  $inv.power = $scheme
} catch { $inv.power = '' }
$inv | ConvertTo-Json -Depth 5 -Compress | Out-File -FilePath '__OUT__' -Encoding utf8
"""


def load_inventory() -> dict:
    out = Path(tempfile.gettempdir()) / "orion-inventory.json"
    script = INVENTORY_SCRIPT.replace("__OUT__", str(out))
    return run_powershell_json(script, out, timeout=70)


def parse_cim_date(value: str) -> str:
    if not value:
        return ""
    match = re.search(r"Date\((\d+)", value)
    if match:
        try:
            return datetime.fromtimestamp(int(match.group(1)) / 1000).strftime("%d/%m/%Y")
        except (OSError, OverflowError, ValueError):
            return ""
    match = re.match(r"(\d{4})(\d{2})(\d{2})", value)
    if match:
        return f"{match.group(3)}/{match.group(2)}/{match.group(1)}"
    return value


def _vram_map() -> dict[str, float]:
    import winreg

    found: dict[str, float] = {}
    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    for index in range(12):
        path = f"{base}\\{index:04d}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                name, _ = winreg.QueryValueEx(key, "DriverDesc")
                size, _ = winreg.QueryValueEx(key, "HardwareInformation.qwMemorySize")
        except OSError:
            continue
        if name and size:
            found[str(name).strip().lower()] = round(int(size) / (1024**3), 1)
    return found


def _dword(root: str, path: str, name: str) -> int | None:
    exists, reg_type, value = read_value(root, path, name)
    if not exists or reg_type != 4:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def read_power_toggles() -> dict[str, bool | int | None]:
    game_mode = _dword("HKCU", r"Software\Microsoft\GameBar", "AutoGameModeEnabled")
    dvr_policy = _dword("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\GameDVR", "AllowGameDVR")
    dvr_user = _dword("HKCU", r"System\GameConfigStore", "GameDVR_Enabled")
    capture = _dword("HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled")
    game_bar = _dword("HKCU", r"Software\Microsoft\GameBar", "UseNexusForGameBarEnabled")
    hags = _dword("HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode")
    mouse_speed, _, _ = _mouse()
    if dvr_policy == 0:
        dvr_on = False
    elif dvr_user == 1 or capture == 1:
        dvr_on = True
    elif dvr_user == 0 or capture == 0:
        dvr_on = False
    else:
        dvr_on = None
    return {
        "game_mode": None if game_mode is None else bool(game_mode),
        "game_dvr": dvr_on,
        "game_bar": None if game_bar is None else bool(game_bar),
        "hags_mode": hags,
        "mouse_accel": mouse_speed,
    }


def _mouse() -> tuple[bool | None, str, str]:
    exists, _, speed = read_value("HKCU", r"Control Panel\Mouse", "MouseSpeed")
    _, _, threshold = read_value("HKCU", r"Control Panel\Mouse", "MouseThreshold1")
    if not exists:
        return None, "", ""
    try:
        accel = int(str(speed)) != 0 or int(str(threshold or "0")) != 0
    except ValueError:
        return None, str(speed), str(threshold)
    return accel, str(speed), str(threshold or "0")


def pending_reboot() -> bool:
    import winreg

    paths = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
    )
    for path in paths:
        try:
            winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY).Close()
            return True
        except OSError:
            continue
    return False


def read_displays() -> list[DisplayInfo]:
    user32 = ctypes.windll.user32

    class DEVMODE(ctypes.Structure):
        _fields_ = [
            ("dmDeviceName", ctypes.c_wchar * 32),
            ("dmSpecVersion", ctypes.c_ushort),
            ("dmDriverVersion", ctypes.c_ushort),
            ("dmSize", ctypes.c_ushort),
            ("dmDriverExtra", ctypes.c_ushort),
            ("dmFields", ctypes.c_ulong),
            ("dmPositionX", ctypes.c_long),
            ("dmPositionY", ctypes.c_long),
            ("dmDisplayOrientation", ctypes.c_ulong),
            ("dmDisplayFixedOutput", ctypes.c_ulong),
            ("dmColor", ctypes.c_short),
            ("dmDuplex", ctypes.c_short),
            ("dmYResolution", ctypes.c_short),
            ("dmTTOption", ctypes.c_short),
            ("dmCollate", ctypes.c_short),
            ("dmFormName", ctypes.c_wchar * 32),
            ("dmLogPixels", ctypes.c_ushort),
            ("dmBitsPerPel", ctypes.c_ulong),
            ("dmPelsWidth", ctypes.c_ulong),
            ("dmPelsHeight", ctypes.c_ulong),
            ("dmDisplayFlags", ctypes.c_ulong),
            ("dmDisplayFrequency", ctypes.c_ulong),
            ("dmICMMethod", ctypes.c_ulong),
            ("dmICMIntent", ctypes.c_ulong),
            ("dmMediaType", ctypes.c_ulong),
            ("dmDitherType", ctypes.c_ulong),
            ("dmReserved1", ctypes.c_ulong),
            ("dmReserved2", ctypes.c_ulong),
            ("dmPanningWidth", ctypes.c_ulong),
            ("dmPanningHeight", ctypes.c_ulong),
        ]

    class DISPLAY_DEVICE(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_uint),
            ("DeviceName", ctypes.c_wchar * 32),
            ("DeviceString", ctypes.c_wchar * 128),
            ("StateFlags", ctypes.c_uint),
            ("DeviceID", ctypes.c_wchar * 128),
            ("DeviceKey", ctypes.c_wchar * 128),
        ]

    displays: list[DisplayInfo] = []
    for index in range(8):
        device = DISPLAY_DEVICE()
        device.cb = ctypes.sizeof(DISPLAY_DEVICE)
        if not user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
            break
        if not (device.StateFlags & 0x1):
            continue
        mode = DEVMODE()
        mode.dmSize = ctypes.sizeof(DEVMODE)
        if not user32.EnumDisplaySettingsW(device.DeviceName, -1, ctypes.byref(mode)):
            continue
        if mode.dmPelsWidth <= 0:
            continue
        displays.append(
            DisplayInfo(
                name=device.DeviceString or device.DeviceName,
                width=int(mode.dmPelsWidth),
                height=int(mode.dmPelsHeight),
                hz=int(mode.dmDisplayFrequency),
                primary=bool(device.StateFlags & 0x4),
            )
        )
    if displays:
        return displays
    mode = DEVMODE()
    mode.dmSize = ctypes.sizeof(DEVMODE)
    if user32.EnumDisplaySettingsW(None, -1, ctypes.byref(mode)) and mode.dmPelsWidth:
        return [
            DisplayInfo(
                name="Monitor principal",
                width=int(mode.dmPelsWidth),
                height=int(mode.dmPelsHeight),
                hz=int(mode.dmDisplayFrequency),
                primary=True,
            )
        ]
    return []


def _media_label(raw: str, name: str, bus: str) -> str:
    folded = f"{raw} {name} {bus}".lower()
    if "ssd" in folded or "nvme" in folded:
        return "SSD"
    if raw.upper() == "HDD" or "hard" in folded:
        return "HDD"
    if bus.upper() == "NVME":
        return "SSD"
    return raw or "desconhecido"


def build_disks(inventory: dict) -> list[DiskInfo]:
    by_number = {int(item.get("Number", -1)): item for item in as_list(inventory.get("disks"))}
    disks: list[DiskInfo] = []
    seen: set[str] = set()
    for part in as_list(inventory.get("parts")):
        letter = str(part.get("Letter") or "").upper()
        if not letter:
            continue
        seen.add(letter)
        physical = by_number.get(int(part.get("Number", -1)), {})
        root = f"{letter}:\\"
        try:
            usage = psutil.disk_usage(root)
            total = usage.total / (1024**3)
            free = usage.free / (1024**3)
        except OSError:
            total = 0.0
            free = 0.0
        name = str(physical.get("Name") or "")
        bus = str(physical.get("Bus") or "")
        disks.append(
            DiskInfo(
                letter=letter,
                media=_media_label(str(physical.get("Media") or ""), name, bus),
                name=name.strip() or "Disco",
                bus=bus,
                health=str(physical.get("Health") or ""),
                total_gb=round(total, 1),
                free_gb=round(free, 1),
            )
        )
    if disks:
        return disks
    for part in psutil.disk_partitions(all=False):
        letter = part.mountpoint[:1].upper()
        if part.mountpoint[1:3] != ":\\" or letter in seen:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        disks.append(
            DiskInfo(
                letter=letter,
                media="desconhecido",
                name=part.device,
                bus="",
                health="",
                total_gb=round(usage.total / (1024**3), 1),
                free_gb=round(usage.free / (1024**3), 1),
            )
        )
    return disks


def build_gpus(inventory: dict) -> list[GpuInfo]:
    vrams = _vram_map()
    gpus: list[GpuInfo] = []
    for item in as_list(inventory.get("gpus")):
        name = str(item.get("Name") or "").strip()
        if not name:
            continue
        folded = name.lower()
        if "microsoft basic" in folded:
            continue
        vram = vrams.get(folded)
        if vram is None:
            for key, value in vrams.items():
                if key in folded or folded in key:
                    vram = value
                    break
        gpus.append(
            GpuInfo(
                name=name,
                driver_version=str(item.get("DriverVersion") or ""),
                driver_date=parse_cim_date(str(item.get("DriverDate") or "")),
                vram_gb=vram,
                vendor=gpu_vendor(name),
            )
        )
    gpus.sort(key=lambda item: 0 if item.vendor in {"nvidia", "amd"} else 1)
    return gpus


def parse_power(text: str) -> tuple[str, str]:
    guid = ""
    match = re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", text or "")
    if match:
        guid = match.group(0).lower()
    name = ""
    named = re.search(r"\((.+)\)", text or "")
    if named:
        name = named.group(1).strip()
    return name, guid


def uptime_hours(last_boot: str) -> float:
    if not last_boot:
        return 0.0
    try:
        boot = datetime.fromisoformat(last_boot)
    except ValueError:
        return 0.0
    if boot.tzinfo is None:
        delta = datetime.now() - boot
    else:
        delta = datetime.now(boot.tzinfo) - boot
    return round(max(delta.total_seconds(), 0) / 3600, 1)


def hostname() -> str:
    return socket.gethostname()


def platform_fallback() -> dict:
    return {
        "os": {"Caption": platform.platform(), "Version": platform.version(), "LastBoot": ""},
        "cpu": {
            "Name": platform.processor(),
            "Cores": psutil.cpu_count(logical=False) or 0,
            "Threads": psutil.cpu_count(logical=True) or 0,
            "MaxMHz": int((psutil.cpu_freq().max if psutil.cpu_freq() else 0) or 0),
            "CurrentMHz": int((psutil.cpu_freq().current if psutil.cpu_freq() else 0) or 0),
        },
    }


def sample_cpu() -> tuple[float, float]:
    """Retorna uso total e o núcleo mais ocupado. O intervalo curto evita uma segunda espera."""
    per_core = psutil.cpu_percent(interval=0.6, percpu=True)
    if not per_core:
        return 0.0, 0.0
    return round(sum(per_core) / len(per_core), 1), round(max(per_core), 1)


def active_power_fallback() -> tuple[str, str]:
    completed = run_hidden(["powercfg", "/getactivescheme"], timeout=15)
    return parse_power(completed.stdout)
