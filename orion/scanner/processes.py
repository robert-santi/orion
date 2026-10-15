"""Processos e programas de inicialização que competem com o jogo."""

from __future__ import annotations

import winreg

import psutil

from orion.models import ProcessInfo, StartupItem

NOTES = {
    "chrome.exe": "O Chrome divide o processador fraco com o jogo. Cada aba é um processo.",
    "msedge.exe": "O Edge aberto em segundo plano gasta núcleo e memória.",
    "firefox.exe": "O Firefox aberto compete por CPU com o jogo.",
    "opera.exe": "O Opera aberto compete por CPU com o jogo.",
    "brave.exe": "O Brave aberto compete por CPU com o jogo.",
    "discord.exe": "O Discord com sobreposição injeta código no jogo e pode microtravar.",
    "spotify.exe": "O Spotify em reprodução usa CPU e, às vezes, a GPU.",
    "onedrive.exe": "A sincronização grava no disco durante a partida. Em HD isso vira travada.",
    "steamwebhelper.exe": "A interface web da Steam pesa quando há muitas janelas abertas.",
    "epicgameslauncher.exe": "O launcher da Epic pode ficar pesado mesmo sem jogo aberto.",
    "gamebar.exe": "A Xbox Game Bar adiciona uma camada sobre o jogo.",
    "gamebarftserver.exe": "Serviço de captura da Game Bar.",
    "medal.exe": "O Medal grava a tela e tira FPS direto.",
    "outplayed.exe": "Gravador de clipes. Compete com o jogo o tempo todo.",
    "overwolf.exe": "Overlay de terceiros. Causa travada em vários jogos.",
    "wallpaper64.exe": "Wallpaper animado usa GPU o tempo todo.",
    "wallpaper32.exe": "Wallpaper animado usa GPU o tempo todo.",
    "amdow.exe": "Overlay da AMD por cima do jogo.",
    "amddvr.exe": "Gravação instantânea da AMD. É o equivalente ao Game DVR.",
    "radeonsoftware.exe": "Painel da AMD aberto. O custo alto é a gravação, não o ícone.",
    "msmpeng.exe": "O Defender está varrendo agora. Espere terminar antes de medir FPS.",
    "searchindexer.exe": "A indexação do Windows está usando o disco.",
    "sysmain.exe": "O SysMain está lendo o disco em segundo plano.",
    "teams.exe": "O Teams aberto segura CPU e memória.",
    "phoneexperiencehost.exe": "O Vincular ao Celular fica acordado em segundo plano.",
    "widgetboard.exe": "Widgets do Windows.",
    "adobe desktop service.exe": "Serviços da Adobe acordam no meio da partida.",
    "ccxprocess.exe": "Processo da Adobe em segundo plano.",
}

HEAVY_STARTUP = (
    "discord",
    "spotify",
    "chrome",
    "edge",
    "onedrive",
    "teams",
    "adobe",
    "epic games",
    "skype",
    "wallpaper",
    "medal",
    "overwolf",
)

IGNORE = {
    "system",
    "idle",
    "registry",
    "memcompression",
    "csrss.exe",
    "smss.exe",
    "wininit.exe",
    "services.exe",
    "lsass.exe",
    "svchost.exe",
    "fontdrvhost.exe",
    "sihost.exe",
    "ctfmon.exe",
    "dwm.exe",
    "explorer.exe",
    "securityhealthservice.exe",
    "securityhealthsystray.exe",
    "orion.exe",
    "python.exe",
    "pythonw.exe",
}

CLOSE_CANDIDATES = {
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "opera.exe",
    "brave.exe",
    "spotify.exe",
    "medal.exe",
    "outplayed.exe",
    "overwolf.exe",
    "wallpaper64.exe",
    "wallpaper32.exe",
    "amdow.exe",
    "amddvr.exe",
    "widgetboard.exe",
}


def sample_load() -> tuple[float, float, list[ProcessInfo]]:
    tracked: list[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            proc.cpu_percent(None)
            tracked.append(proc)
        except (psutil.Error, OSError):
            continue
    per_core = psutil.cpu_percent(interval=0.5, percpu=True)
    total = round(sum(per_core) / len(per_core), 1) if per_core else 0.0
    busiest = round(max(per_core), 1) if per_core else 0.0
    rows: list[ProcessInfo] = []
    for proc in tracked:
        try:
            name = proc.name() or ""
            cpu = proc.cpu_percent(None) or 0.0
            rss = proc.memory_info().rss / (1024**2)
        except (psutil.Error, OSError):
            continue
        if name.lower() in IGNORE:
            continue
        note = NOTES.get(name.lower(), "")
        if rss < 80 and cpu < 2 and not note:
            continue
        rows.append(ProcessInfo(name=name, pid=proc.pid, rss_mb=round(rss, 0), cpu=round(cpu, 1), note=note))
    rows.sort(key=lambda item: (item.rss_mb, item.cpu), reverse=True)
    return total, busiest, rows[:25]


def _startup_key(root, path: str, location: str) -> list[StartupItem]:
    items: list[StartupItem] = []
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            count = winreg.QueryInfoKey(key)[1]
            for index in range(count):
                name, value, _ = winreg.EnumValue(key, index)
                command = str(value)
                folded = f"{name} {command}".lower()
                heavy = any(token in folded for token in HEAVY_STARTUP)
                items.append(StartupItem(name=str(name), command=command, location=location, heavy=heavy))
    except OSError:
        return []
    return items


def read_startups() -> list[StartupItem]:
    items: list[StartupItem] = []
    items.extend(_startup_key(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKCU Run"))
    items.extend(_startup_key(winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKLM Run"))
    items.extend(
        _startup_key(
            winreg.HKEY_LOCAL_MACHINE,
            r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
            "HKLM Run 32",
        )
    )
    return items


def running_names() -> set[str]:
    names: set[str] = set()
    for proc in psutil.process_iter(["name"]):
        try:
            name = proc.info.get("name") or ""
        except (psutil.Error, OSError):
            continue
        if name:
            names.add(name.lower())
    return names
