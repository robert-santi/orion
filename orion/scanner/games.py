"""Lê Steam, Epic, GOG, Riot, Xbox, EA e Battle.net e aponta o executável de cada jogo."""

from __future__ import annotations

import json
import re
import winreg
from pathlib import Path

from orion.models import DiskInfo, GameEntry
from orion.scanner.profiles import is_steam_tool, profile_for

EXE_HINTS = {
    "cs2": ["game/bin/win64/cs2.exe"],
    "rocket_league": ["Binaries/Win64/RocketLeague.exe", "Binaries/Win64/RocketLeague.exe".replace("/", "\\")],
}


def _drive(path: str, disks: list[DiskInfo]) -> tuple[str, str, str]:
    if len(path) < 2 or path[1] != ":":
        return "", "desconhecido", ""
    letter = path[0].upper()
    for disk in disks:
        if disk.letter.upper() == letter:
            return letter, disk.media, disk.name
    return letter, "desconhecido", ""


def _entry(
    name: str,
    platform: str,
    app_id: str,
    install_dir: str,
    executable: str,
    size_bytes: int | None,
    disks: list[DiskInfo],
) -> GameEntry:
    letter, media, disk_name = _drive(install_dir or executable, disks)
    return GameEntry(
        name=name.strip(),
        platform=platform,
        app_id=str(app_id),
        install_dir=install_dir,
        executable=executable,
        size_bytes=size_bytes,
        drive_letter=letter,
        drive_media=media,
        drive_name=disk_name,
        profile=profile_for(name, str(app_id)),
    )


def steam_root() -> Path | None:
    for root in (winreg.HKEY_CURRENT_USER,):
        try:
            with winreg.OpenKey(root, r"Software\Valve\Steam") as key:
                value, _ = winreg.QueryValueEx(key, "SteamPath")
                path = Path(str(value))
                if path.exists():
                    return path
        except OSError:
            continue
    candidate = Path(r"C:\Program Files (x86)\Steam")
    if candidate.exists():
        return candidate
    return None


def _library_paths(root: Path) -> list[Path]:
    libraries = [root]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if not vdf.exists():
        vdf = root / "config" / "libraryfolders.vdf"
    if vdf.exists():
        text = vdf.read_text(encoding="utf-8", errors="replace")
        for raw in re.findall(r'"path"\s+"([^"]+)"', text):
            path = Path(raw.replace("\\\\", "\\"))
            if path not in libraries:
                libraries.append(path)
    return libraries


def _acf(text: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s+"([^"]*)"', text)
    return match.group(1) if match else ""


def _shallow_exe(root: Path, hints: list[str], name: str) -> str:
    """Procura o executável sem varrer a árvore inteira de jogos grandes."""
    for hint in hints:
        candidate = root / hint
        if candidate.is_file():
            return str(candidate)
    if not root.exists():
        return ""
    found: list[Path] = []
    found.extend(path for path in root.glob("*.exe") if path.is_file())
    for folder in list(root.iterdir())[:30]:
        if folder.is_dir():
            found.extend(path for path in folder.glob("*.exe") if path.is_file())
    for pattern in ("Binaries/Win64/*.exe", "game/bin/win64/*.exe", "bin/win64/*.exe"):
        found.extend(path for path in root.glob(pattern) if path.is_file())
    if not found:
        return ""
    preferred = name.lower().replace(" ", "").replace(":", "")

    def rank(path: Path) -> tuple[int, int, int]:
        stem = path.stem.lower()
        bad = int(any(token in stem for token in ("unins", "crash", "setup", "redist")))
        good = int(preferred in stem or stem in preferred)
        launcher = int("launcher" in stem)
        return (bad, launcher, -good, len(stem))

    found.sort(key=rank)
    best = found[0]
    if any(token in best.stem.lower() for token in ("unins", "crashreport")):
        return ""
    return str(best)


def scan_steam(disks: list[DiskInfo]) -> list[GameEntry]:
    root = steam_root()
    if root is None:
        return []
    games: list[GameEntry] = []
    for library in _library_paths(root):
        steamapps = library / "steamapps"
        if not steamapps.exists():
            continue
        for manifest in steamapps.glob("appmanifest_*.acf"):
            text = manifest.read_text(encoding="utf-8", errors="replace")
            app_id = _acf(text, "appid")
            name = _acf(text, "name")
            if not name or is_steam_tool(app_id, name):
                continue
            size_raw = _acf(text, "SizeOnDisk")
            try:
                size = int(size_raw) if size_raw else None
            except ValueError:
                size = None
            if size == 0:
                continue
            install_dir = steamapps / "common" / _acf(text, "installdir")
            profile = profile_for(name, app_id)
            executable = _shallow_exe(install_dir, EXE_HINTS.get(profile, []), name) if install_dir.exists() else ""
            games.append(
                _entry(name, "Steam", app_id, str(install_dir), executable, size, disks)
            )
    return games


def scan_epic(disks: list[DiskInfo]) -> list[GameEntry]:
    folder = Path(r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests")
    if not folder.exists():
        return []
    games: list[GameEntry] = []
    for manifest in folder.glob("*.item"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8-sig", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("bIsIncompleteInstall"):
            continue
        name = str(data.get("DisplayName") or "").strip()
        install = str(data.get("InstallLocation") or "")
        if not name or not install:
            continue
        executable = ""
        launch = str(data.get("LaunchExecutable") or "")
        if launch:
            candidate = Path(install) / launch
            if candidate.is_file():
                executable = str(candidate)
        profile = profile_for(name, str(data.get("CatalogItemId") or data.get("AppName") or ""))
        if not executable and Path(install).exists():
            executable = _shallow_exe(Path(install), EXE_HINTS.get(profile, []), name)
        size = data.get("InstallSize")
        try:
            size_bytes = int(size) if size is not None else None
        except (TypeError, ValueError):
            size_bytes = None
        games.append(
            _entry(
                name,
                "Epic",
                str(data.get("CatalogItemId") or data.get("AppName") or ""),
                install,
                executable,
                size_bytes,
                disks,
            )
        )
    return games


def scan_gog(disks: list[DiskInfo]) -> list[GameEntry]:
    games: list[GameEntry] = []
    base = r"SOFTWARE\WOW6432Node\GOG.com\Games"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as root:
            count = winreg.QueryInfoKey(root)[0]
            for index in range(count):
                sub = winreg.EnumKey(root, index)
                with winreg.OpenKey(root, sub) as key:
                    try:
                        name, _ = winreg.QueryValueEx(key, "gameName")
                        path, _ = winreg.QueryValueEx(key, "path")
                    except OSError:
                        continue
                    executable = ""
                    try:
                        exe, _ = winreg.QueryValueEx(key, "exe")
                        executable = str(exe)
                    except OSError:
                        pass
                    games.append(_entry(str(name), "GOG", sub, str(path), executable, None, disks))
    except OSError:
        return []
    return games


def scan_riot(disks: list[DiskInfo]) -> list[GameEntry]:
    path = Path(r"C:\ProgramData") / "Riot Games" / "RiotClientInstalls.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return []
    games: list[GameEntry] = []
    associated = data.get("associated_client") or data.get("associated_clients") or {}
    if isinstance(associated, dict):
        for name, location in associated.items():
            if not location:
                continue
            root = Path(str(location))
            games.append(_entry(str(name), "Riot", "", str(root), "", None, disks))
    return games


def scan_xbox(disks: list[DiskInfo]) -> list[GameEntry]:
    root = Path(r"C:\XboxGames")
    if not root.exists():
        return []
    games: list[GameEntry] = []
    for folder in root.iterdir():
        if not folder.is_dir() or folder.name.lower() in {"gamesave", "game save"}:
            continue
        executable = _shallow_exe(folder, ["Content/gamelaunchhelper.exe"], folder.name)
        games.append(_entry(folder.name, "Xbox", "", str(folder), executable, None, disks))
    return games


def scan_ea(disks: list[DiskInfo]) -> list[GameEntry]:
    games: list[GameEntry] = []
    for folder in (Path(r"C:\Program Files\EA Games"), Path(r"C:\Program Files (x86)\EA Games")):
        if not folder.exists():
            continue
        for child in folder.iterdir():
            if child.is_dir():
                games.append(_entry(child.name, "EA", "", str(child), "", None, disks))
    return games


def scan_battlenet(disks: list[DiskInfo]) -> list[GameEntry]:
    games: list[GameEntry] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Blizzard Entertainment") as root:
            count = winreg.QueryInfoKey(root)[0]
            for index in range(count):
                name = winreg.EnumKey(root, index)
                if name.lower() in {"battle.net", "blizzard error"}:
                    continue
                games.append(_entry(name, "Battle.net", "", "", "", None, disks))
    except OSError:
        return []
    return games


def scan_games(disks: list[DiskInfo]) -> tuple[list[GameEntry], list[str]]:
    notes: list[str] = []
    found: list[GameEntry] = []
    scanners = (
        ("Steam", scan_steam),
        ("Epic", scan_epic),
        ("GOG", scan_gog),
        ("Riot", scan_riot),
        ("Xbox", scan_xbox),
        ("EA", scan_ea),
        ("Battle.net", scan_battlenet),
    )
    for label, scanner in scanners:
        try:
            found.extend(scanner(disks))
        except Exception as error:  # um launcher quebrado não pode derrubar a varredura
            notes.append(f"Não consegui ler a biblioteca {label}: {error}")
    unique: list[GameEntry] = []
    seen: set[tuple[str, str]] = set()
    for game in found:
        key = (game.name.lower(), game.platform.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(game)
    unique.sort(key=lambda item: (item.profile not in {"cs2", "rocket_league"}, item.name.lower()))
    return unique, notes
