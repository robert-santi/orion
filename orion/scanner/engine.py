"""Junta as leituras numa fotografia só. Uma falha parcial não cancela o resto."""

from __future__ import annotations

import logging
from datetime import datetime

import psutil

from orion.models import Snapshot
from orion.scanner.configs import load_game_configs
from orion.scanner.diagnostics import evaluate
from orion.scanner.games import scan_games
from orion.scanner.network import probe
from orion.scanner.processes import read_startups, sample_load
from orion.scanner.system_info import (
    active_power_fallback,
    build_disks,
    build_gpus,
    hostname,
    load_inventory,
    parse_power,
    pending_reboot,
    platform_fallback,
    read_displays,
    read_power_toggles,
    uptime_hours,
)
from orion.winutil import as_list

log = logging.getLogger("orion")


def _progress(callback, message: str) -> None:
    if callback:
        callback(message)


def run_scan(progress=None) -> Snapshot:
    notes: list[str] = []
    _progress(progress, "Lendo processador, memória, placa e discos")
    try:
        inventory = load_inventory()
    except Exception as error:
        log.exception("inventário")
        notes.append(f"Inventário do Windows incompleto: {error}")
        inventory = platform_fallback()

    os_info = inventory.get("os") or {}
    cpu_info = inventory.get("cpu") or {}
    memory = as_list(inventory.get("memory"))
    ram_total = psutil.virtual_memory().total / (1024**3)
    ram_available = psutil.virtual_memory().available / (1024**3)
    speeds = [int(item.get("Speed") or 0) for item in memory if item.get("Speed")]
    ram_speed = speeds[0] if speeds else None

    disks = build_disks(inventory)
    gpus = build_gpus(inventory)
    power_name, power_guid = parse_power(str(inventory.get("power") or ""))
    if not power_guid:
        try:
            power_name, power_guid = active_power_fallback()
        except Exception as error:
            notes.append(f"Plano de energia não lido: {error}")

    toggles = read_power_toggles()
    _progress(progress, "Medindo uso de CPU e programas abertos")
    try:
        cpu_percent, busiest, processes = sample_load()
    except Exception as error:
        log.exception("processos")
        notes.append(f"Processos não lidos: {error}")
        cpu_percent, busiest, processes = 0.0, 0.0, []

    try:
        startups = read_startups()
    except Exception as error:
        notes.append(f"Inicialização não lida: {error}")
        startups = []

    _progress(progress, "Lendo Steam, Epic, Xbox e as outras bibliotecas")
    try:
        games, game_notes = scan_games(disks)
        notes.extend(game_notes)
    except Exception as error:
        log.exception("jogos")
        notes.append(f"Bibliotecas não lidas: {error}")
        games = []

    _progress(progress, "Lendo configurações do CS2 e do Rocket League")
    try:
        configs = load_game_configs(games)
    except Exception as error:
        log.exception("configs")
        notes.append(f"Configurações de jogo não lidas: {error}")
        configs = {"cs2": None, "rocket_league": None}

    _progress(progress, "Medindo latência da rede")
    try:
        network = probe()
    except Exception as error:
        notes.append(f"Rede não medida: {error}")
        network = []

    freq = psutil.cpu_freq()
    current = float(cpu_info.get("CurrentMHz") or 0)
    if freq and freq.current:
        current = float(freq.current)
    maximum = float(cpu_info.get("MaxMHz") or 0)
    if freq and freq.max:
        maximum = max(maximum, float(freq.max))

    snapshot = Snapshot(
        scanned_at=datetime.now().strftime("%d/%m/%Y %H:%M"),
        hostname=hostname(),
        os_name=str(os_info.get("Caption") or ""),
        os_version=str(os_info.get("Version") or ""),
        uptime_hours=uptime_hours(str(os_info.get("LastBoot") or "")),
        cpu_name=str(cpu_info.get("Name") or "Processador não identificado"),
        cpu_cores=int(cpu_info.get("Cores") or 0),
        cpu_threads=int(cpu_info.get("Threads") or 0),
        cpu_max_mhz=maximum,
        cpu_current_mhz=current,
        cpu_percent=cpu_percent,
        cpu_busiest_core=busiest,
        ram_total_gb=round(ram_total, 1),
        ram_used_gb=round(ram_total - ram_available, 1),
        ram_available_gb=round(ram_available, 1),
        ram_speed_mhz=ram_speed,
        ram_sticks=len(memory),
        gpus=gpus,
        displays=read_displays(),
        disks=disks,
        board=str(inventory.get("board") or ""),
        power_plan=power_name,
        power_guid=power_guid,
        game_mode=toggles["game_mode"],
        game_dvr=toggles["game_dvr"],
        game_bar=toggles["game_bar"],
        hags_mode=toggles["hags_mode"],
        mouse_accel=toggles["mouse_accel"],
        adapters=[{"name": str(a.get("Name") or ""), "media": str(a.get("Media") or ""), "speed": str(a.get("Speed") or "")} for a in as_list(inventory.get("adapters"))],
        pagefiles=as_list(inventory.get("pagefiles")),
        processes=processes,
        startups=startups,
        games=games,
        configs=configs,
        network=network,
        pending_reboot=pending_reboot(),
        notes=notes,
    )
    _progress(progress, "Montando o diagnóstico")
    issues, healthy = evaluate(snapshot)
    snapshot.issues = issues
    snapshot.healthy = healthy
    return snapshot
