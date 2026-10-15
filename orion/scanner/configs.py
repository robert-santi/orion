"""Configurações de CS2 e Rocket League que mudam FPS e latência de verdade."""

from __future__ import annotations

import os
from pathlib import Path

from orion.models import GameEntry
from orion.textcfg import ini_values, read_text, vdf_values

CS2_KEYS = {
    "setting.defaultres",
    "setting.defaultresheight",
    "setting.refreshrate_numerator",
    "setting.fullscreen",
    "setting.coop_fullscreen",
    "setting.nowindowborder",
    "setting.mat_vsync",
    "setting.cpu_level",
    "setting.gpu_level",
    "setting.gpu_mem_level",
    "setting.msaa_samples",
    "setting.videocfg_shadow_quality",
    "setting.videocfg_dynamic_shadows",
    "setting.videocfg_ao_detail",
    "setting.videocfg_particle_detail",
    "setting.videocfg_texture_detail",
    "setting.shaderquality",
    "setting.r_texturefilteringquality",
    "setting.r_low_latency",
}

CS2_PRESET = {
    "setting.cpu_level": "0",
    "setting.gpu_level": "1",
    "setting.gpu_mem_level": "2",
    "setting.msaa_samples": "2",
    "setting.videocfg_shadow_quality": "0",
    "setting.videocfg_dynamic_shadows": "0",
    "setting.videocfg_ao_detail": "0",
    "setting.videocfg_particle_detail": "1",
    "setting.videocfg_texture_detail": "1",
    "setting.shaderquality": "0",
    "setting.r_texturefilteringquality": "1",
    "setting.mat_vsync": "0",
    "setting.r_low_latency": "1",
}

RL_LATENCY_KEYS = {
    "UseVsync": "False",
    "OneFrameThreadLag": "False",
    "AllowPerFrameSleep": "False",
    "DynamicShadows": "False",
    "LightEnvironmentShadows": "False",
    "AllowImageReflections": "False",
    "AllowImageReflectionShadowing": "False",
    "Distortion": "False",
    "FilteredDistortion": "False",
    "LensFlares": "False",
    "Bloom": "False",
    "MotionBlur": "False",
    "AmbientOcclusion": "False",
    "DynamicLights": "False",
    "UpscaleScreenPercentage": "False",
}


def _int(value: str | None, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def find_cs2_video() -> Path | None:
    steam = Path(r"C:\Program Files (x86)\Steam\userdata")
    candidates = list(steam.glob("*/730/local/cfg/cs2_video.txt")) if steam.exists() else []
    extra = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam" / "userdata"
    if extra.exists() and extra != steam:
        candidates.extend(extra.glob("*/730/local/cfg/cs2_video.txt"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def find_rl_settings() -> Path | None:
    names = []
    home = Path.home()
    for documents in (home / "Documents", home / "OneDrive" / "Documents", home / "OneDrive" / "Documentos"):
        names.append(documents / "My Games" / "Rocket League" / "TAGame" / "Config" / "TASystemSettings.ini")
    local = Path(os.environ.get("USERPROFILE", str(home))) / "Documents" / "My Games" / "Rocket League" / "TAGame" / "Config" / "TASystemSettings.ini"
    names.append(local)
    for path in names:
        if path.is_file():
            return path
    return None


def cs2_preset_needed(values: dict[str, str], weak_cpu: bool) -> bool:
    if not values:
        return False
    if _int(values.get("setting.mat_vsync"), 0) != 0:
        return True
    cpu_limit = 1 if weak_cpu else 2
    if _int(values.get("setting.cpu_level"), 0) > cpu_limit:
        return True
    if _int(values.get("setting.gpu_level"), 0) > 1:
        return True
    if _int(values.get("setting.msaa_samples"), 0) > 2:
        return True
    if _int(values.get("setting.videocfg_shadow_quality"), 0) > 0:
        return True
    if _int(values.get("setting.videocfg_dynamic_shadows"), 0) > 0:
        return True
    if _int(values.get("setting.videocfg_ao_detail"), 0) > 0:
        return True
    return False


def cs2_changes(values: dict[str, str]) -> dict[str, str]:
    return {key: target for key, target in CS2_PRESET.items() if values.get(key) != target}


def rl_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes"}


def rl_preset_needed(values: dict[str, str]) -> bool:
    if not values:
        return False
    if rl_truthy(values.get("UseVsync")):
        return True
    if rl_truthy(values.get("OneFrameThreadLag")):
        return True
    if rl_truthy(values.get("AllowPerFrameSleep")):
        return True
    if rl_truthy(values.get("DynamicShadows")) or rl_truthy(values.get("LightEnvironmentShadows")):
        return True
    if rl_truthy(values.get("UpscaleScreenPercentage")):
        return True
    return False


def rl_changes(values: dict[str, str], display: tuple[int, int] | None) -> dict[str, str]:
    updates = {key: target for key, target in RL_LATENCY_KEYS.items() if str(values.get(key, "")).lower() != target.lower()}
    if display and values.get("ResX") and values.get("ResY"):
        width = _int(values.get("ResX"))
        height = _int(values.get("ResY"))
        if width > display[0] and height > display[1] and display[0] >= 800 and display[1] >= 600:
            updates["ResX"] = str(display[0])
            updates["ResY"] = str(display[1])
    return updates


def load_game_configs(games: list[GameEntry]) -> dict:
    configs: dict = {"cs2": None, "rocket_league": None}
    cs2 = next((game for game in games if game.profile == "cs2"), None)
    rl = next((game for game in games if game.profile == "rocket_league"), None)
    video = find_cs2_video()
    if video and video.is_file():
        text, encoding = read_text(video)
        values = vdf_values(text, CS2_KEYS)
        configs["cs2"] = {
            "video_path": str(video),
            "encoding": encoding,
            "values": values,
            "exe": cs2.executable if cs2 else "",
            "install_dir": cs2.install_dir if cs2 else "",
            "on_hdd": bool(cs2 and cs2.drive_media == "HDD"),
            "size_bytes": cs2.size_bytes if cs2 else None,
        }
    elif cs2:
        configs["cs2"] = {
            "video_path": "",
            "encoding": "",
            "values": {},
            "exe": cs2.executable,
            "install_dir": cs2.install_dir,
            "on_hdd": cs2.drive_media == "HDD",
            "size_bytes": cs2.size_bytes,
        }
    settings = find_rl_settings()
    if settings and settings.is_file():
        text, encoding = read_text(settings)
        values = ini_values(text)
        configs["rocket_league"] = {
            "ini_path": str(settings),
            "encoding": encoding,
            "values": values,
            "exe": rl.executable if rl else "",
            "install_dir": rl.install_dir if rl else "",
            "on_hdd": bool(rl and rl.drive_media == "HDD"),
            "size_bytes": rl.size_bytes if rl else None,
        }
    elif rl:
        configs["rocket_league"] = {
            "ini_path": "",
            "encoding": "",
            "values": {},
            "exe": rl.executable,
            "install_dir": rl.install_dir,
            "on_hdd": rl.drive_media == "HDD",
            "size_bytes": rl.size_bytes,
        }
    return configs


def discord_overlay_enabled() -> tuple[bool, str]:
    path = Path(os.environ.get("APPDATA", "")) / "discord" / "settings.json"
    if not path.is_file():
        return False, ""
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return False, ""
    enabled = data.get("enableOverlay")
    # O padrão do Discord é overlay ligado quando a chave não existe.
    if enabled is False:
        return False, str(path)
    return True, str(path)
