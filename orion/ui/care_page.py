"""Seção Cuidados: disco, Windows, rede e relatório. A escrita pede confirmação."""

from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog

from orion.paths import data_dir
from orion.scanner.care import USE_LABELS, compare_history, format_bytes, normalize_use_mode, ping_line, render_report
from orion.store import list_history, load_settings
from orion.ui.app import messagebox_info, messagebox_yesno

BG = "#09090b"
CARD = "#16161c"
TEXT = "#f4f1ea"
MUTED = "#9c978c"
GOLD = "#d4b483"
GOLD_TEXT = "#1a1408"
OK = "#7dcea0"
WARN = "#e0b15a"
GHOST = "#221e18"

SECTIONS = (
    ("disco", "Disco"),
    ("sistema", "Sistema"),
    ("rede", "Rede"),
    ("jogos", "Jogos"),
    ("relatorio", "Relatório"),
)


def build_care(app) -> None:
    if app.care is None:
        _loading(app)
        if not app.care_loading:
            app.care_loading = True
            app.care_token += 1
            token = app.care_token
            app._progress_begin()
            threading.Thread(target=lambda: _load(app, token), daemon=True).start()
        return
    frame = ctk.CTkScrollableFrame(app.content, fg_color=BG)
    frame.grid(row=0, column=0, sticky="nsew")
    ctk.CTkLabel(frame, text="Cuidados", font=ctk.CTkFont(size=28, weight="bold"), text_color=TEXT).pack(anchor="w")
    mode = normalize_use_mode(load_settings().get("use_mode") or "")
    shared = (
        "Este PC está marcado como compartilhado. Pastas e inicialização de outras contas ficam de fora."
        if mode == "compartilhado"
        else "Pastas de outros usuários deste computador ficam de fora."
    )
    ctk.CTkLabel(frame, text=shared, text_color=MUTED, wraplength=880, justify="left").pack(anchor="w", pady=(2, 8))
    row = ctk.CTkFrame(frame, fg_color=BG)
    row.pack(fill="x", pady=(0, 10))
    for key, label in SECTIONS:
        active = app.care_section == key
        ctk.CTkButton(
            row,
            text=label,
            width=120,
            height=36,
            corner_radius=18,
            fg_color=GOLD if active else GHOST,
            hover_color="#e2c79a" if active else "#3a3226",
            text_color=GOLD_TEXT if active else TEXT,
            command=lambda section=key: _switch(app, section),
        ).pack(side="left", padx=(0, 8))
    body = {
        "disco": _disco,
        "sistema": _sistema,
        "rede": _rede,
        "jogos": _jogos,
        "relatorio": _relatorio,
    }[app.care_section]
    body(app, frame)
    ctk.CTkLabel(frame, text="Registro desta sessão", text_color=GOLD, font=ctk.CTkFont(size=14, weight="bold")).pack(
        anchor="w", pady=(12, 4)
    )
    box = ctk.CTkTextbox(frame, height=120, fg_color="#101014", text_color=TEXT, corner_radius=14)
    box.pack(fill="x")
    box.insert("end", app.care_lines or "Nenhuma mudança desta seção nesta sessão.\n")
    app.care_log = box


def _loading(app) -> None:
    frame = ctk.CTkFrame(app.content, fg_color=BG)
    frame.grid(row=0, column=0, sticky="nsew")
    frame.grid_rowconfigure(0, weight=1)
    frame.grid_columnconfigure(0, weight=1)
    box = ctk.CTkFrame(frame, fg_color=BG)
    box.grid(row=0, column=0)
    ctk.CTkLabel(box, text="Lendo o computador", font=ctk.CTkFont(size=28, weight="bold"), text_color=TEXT).pack()
    ctk.CTkLabel(
        box,
        text="Disco, programas, inicialização e rede. Nada está sendo alterado.",
        text_color=MUTED,
    ).pack(pady=(8, 16))
    bar = ctk.CTkProgressBar(box, width=360, height=10, corner_radius=8, progress_color=GOLD, fg_color="#1c1a17")
    bar.pack()
    bar.set(0.2)
    app.care_local_bar = bar


def _load(app, token: int) -> None:
    try:
        from orion.scanner.care import collect_care

        payload = collect_care(app.snapshot)
        error = ""
    except Exception as error_value:
        payload = None
        error = str(error_value)
    app.after(0, lambda: _loaded(app, token, payload, error))


def _loaded(app, token: int, payload, error: str) -> None:
    if token != app.care_token:
        return
    app.care_loading = False
    app._progress_end()
    if error or payload is None:
        app.care = {"status_error": error or "A leitura não terminou."}
    else:
        app.care = payload
    if app.page == "cuidados":
        app.show_page("cuidados")


def _switch(app, section: str) -> None:
    app.care_section = section
    app.show_page("cuidados")


def _card(parent, title: str, body: str, tone: str = TEXT) -> None:
    card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=16)
    card.pack(fill="x", pady=4)
    ctk.CTkLabel(card, text=title, text_color=GOLD, font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=16, pady=(12, 0))
    ctk.CTkLabel(card, text=body, text_color=tone, wraplength=840, justify="left").pack(anchor="w", padx=16, pady=(4, 12))


def _check(app, parent, key: str, text: str) -> None:
    var = tk.BooleanVar(value=key in app.care_checks)

    def remember(*_args, item=key, variable=var) -> None:
        if variable.get():
            app.care_checks.add(item)
        else:
            app.care_checks.discard(item)

    var.trace_add("write", remember)
    ctk.CTkCheckBox(
        parent,
        text=text,
        variable=var,
        text_color=TEXT,
        fg_color=GOLD,
        hover_color="#e2c79a",
        checkmark_color=GOLD_TEXT,
        corner_radius=8,
    ).pack(anchor="w", padx=16, pady=2)


def _disco(app, frame) -> None:
    data = app.care
    for disk in data.get("disks") or []:
        if str(disk.get("media") or "").upper() == "SSD" and float(disk.get("free_percent") or 100) < 20:
            _card(
                frame,
                f"SSD {disk.get('letter')} com pouco espaço",
                f"{disk.get('free_gb'):.0f} GB livres de {disk.get('total_gb'):.0f} GB. "
                "Quando o SSD enche, o jogo e o Windows podem engasgar ao carregar.",
                WARN,
            )
    lines = []
    for row in data.get("folders") or []:
        if row.get("refused"):
            continue
        if not row.get("exists"):
            lines.append(f"{row.get('label')}: pasta ausente")
            continue
        suffix = " (leitura parcial)" if row.get("partial") else ""
        lines.append(f"{row.get('label')}: {format_bytes(int(row.get('bytes') or 0))}{suffix}")
    recycle = data.get("recycle") or {}
    if recycle.get("ok"):
        lines.append(f"Lixeira deste usuário: {format_bytes(int(recycle.get('bytes') or 0))} em {int(recycle.get('count') or 0)} item(ns)")
    elif data.get("status_error"):
        lines.append("Lixeira, Defender e drivers não foram lidos nesta passagem.")
    _card(frame, "O que ocupa espaço neste usuário", "\n".join(lines) or "Nenhuma pasta lida.")
    large = data.get("large") or []
    ctk.CTkLabel(frame, text="Arquivos grandes", text_color=TEXT, font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", pady=(10, 4))
    if not large:
        ctk.CTkLabel(frame, text="Nenhum arquivo acima de 250 MB nessas pastas, nesta leitura.", text_color=MUTED).pack(anchor="w")
    for item in large:
        card = ctk.CTkFrame(frame, fg_color=CARD, corner_radius=16)
        card.pack(fill="x", pady=3)
        ctk.CTkLabel(
            card,
            text=f"{item.get('name')}  ·  {format_bytes(int(item.get('bytes') or 0))}",
            text_color=TEXT,
        ).pack(side="left", padx=14, pady=10)
        app._ghost(card, "Abrir pasta", lambda folder=item.get("folder"): _open_folder(folder)).pack(side="right", padx=12, pady=8)
    ctk.CTkLabel(frame, text="Limpeza", text_color=TEXT, font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", pady=(12, 4))
    ctk.CTkLabel(
        frame,
        text=(
            "Tudo começa desmarcado. O ORION cria um ponto de restauração antes de apagar. "
            "Esse ponto não devolve arquivo temporário nem cache de shader."
        ),
        text_color=MUTED,
        wraplength=860,
        justify="left",
    ).pack(anchor="w", pady=(0, 6))
    box = ctk.CTkFrame(frame, fg_color=CARD, corner_radius=16)
    box.pack(fill="x", pady=4)
    _check(app, box, "temp", "Temp deste usuário")
    _check(app, box, "recycle", "Lixeira deste usuário")
    ctk.CTkLabel(box, text="", height=8).pack()
    app._gold_button(frame, "Limpar o que está marcado", app._care_cleanup, width=260).pack(anchor="w", pady=8)


def _sistema(app, frame) -> None:
    data = app.care
    defender = data.get("defender") or {}
    if defender.get("ok"):
        realtime = "ligada" if defender.get("realtime") else "desligada"
        antivirus = "ligado" if defender.get("antivirus") else "desligado"
        text = f"Proteção em tempo real {realtime}. Antivírus {antivirus}. O ORION não muda isso."
    else:
        text = "Não foi possível ler o estado do Defender. Ele continua intocado."
    _card(frame, "Defender", text)
    update = data.get("windows_update") or "não lido"
    _card(frame, "Windows Update", f"Serviço: {update}. O ORION não desliga o Windows Update.")
    points = data.get("restore_points") or []
    if points:
        listed = "\n".join(f"{item.get('when') or ''}  {item.get('description') or ''}".strip() for item in points)
    else:
        listed = "Nenhum ponto apareceu nesta leitura, ou a lista pediu permissão que ainda não foi dada."
    pending = " Há uma reinicialização pendente." if data.get("pending_reboot") else ""
    _card(frame, "Restauração do Windows", listed + pending)
    app._gold_button(frame, "Criar ponto de restauração agora", app._care_restore_only, width=280).pack(anchor="w", pady=6)
    fast = data.get("fast_startup")
    fast_text = {1: "A inicialização rápida está ligada.", 0: "A inicialização rápida está desligada."}.get(fast, "A inicialização rápida não foi lida.")
    sleep = data.get("sleep_minutes")
    if sleep is None:
        sleep_text = "O tempo de suspensão não foi lido."
    elif int(sleep) == 0:
        sleep_text = "Na tomada, o Windows não suspende sozinho."
    else:
        sleep_text = f"Na tomada, o Windows suspende depois de {int(sleep)} min."
    _card(frame, "Energia", f"Plano: {data.get('power_plan') or 'não lido'}. {fast_text} {sleep_text}")
    crashes = data.get("crashes") or []
    if crashes:
        crash_text = "\n".join(f"{item.get('when')}: {item.get('message')}" for item in crashes)
    else:
        crash_text = "Nenhum travamento de aplicativo (evento 1000) nos últimos 21 dias, ou o registro não pôde ser lido."
    _card(frame, "Travamentos recentes", crash_text)
    old = [item for item in data.get("drivers") or [] if item.get("old")]
    driver_lines = []
    for item in (data.get("drivers") or [])[:8]:
        mark = " · antigo" if item.get("old") else ""
        driver_lines.append(f"{item.get('name')} · {item.get('date') or 'sem data'}{mark}")
    if not driver_lines:
        driver_lines.append("A data dos drivers não foi lida. Nada foi baixado.")
    elif old:
        driver_lines.append("Driver antigo é só um aviso. O ORION não baixa driver.")
    _card(frame, "Drivers de vídeo, rede e áudio", "\n".join(driver_lines))
    ctk.CTkLabel(frame, text="Abre com o Windows", text_color=TEXT, font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", pady=(10, 4))
    ctk.CTkLabel(
        frame,
        text="Dá para desligar só o que é deste usuário. Defender e Windows Update ficam de fora. Itens de todos os usuários aparecem só para leitura.",
        text_color=MUTED,
        wraplength=860,
        justify="left",
    ).pack(anchor="w", pady=(0, 6))
    for item in data.get("startups") or []:
        card = ctk.CTkFrame(frame, fg_color=CARD, corner_radius=16)
        card.pack(fill="x", pady=3)
        weight = format_bytes(int(item.get("bytes") or 0))
        weight_text = f" · {weight}" if item.get("bytes") else ""
        heavy = " · pesado" if item.get("heavy") else ""
        title = f"{item.get('name')}{heavy}{weight_text}"
        if item.get("can_disable"):
            _check(app, card, f"startup:{item.get('name')}", title)
            ctk.CTkLabel(card, text=item.get("location") or "", text_color=MUTED).pack(anchor="w", padx=40, pady=(0, 8))
        else:
            reason = "protegido" if item.get("locked") else "vale para todos os usuários"
            ctk.CTkLabel(card, text=f"{title} · {reason}", text_color=TEXT).pack(anchor="w", padx=16, pady=(10, 0))
            ctk.CTkLabel(card, text=item.get("location") or "", text_color=MUTED).pack(anchor="w", padx=16, pady=(0, 10))
    app._gold_button(frame, "Desligar a inicialização marcada", app._care_startup, width=280).pack(anchor="w", pady=8)
    ctk.CTkLabel(frame, text="Programas instalados", text_color=TEXT, font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", pady=(8, 4))
    app._ghost(frame, "Abrir a lista do Windows", _open_apps).pack(anchor="w", pady=(0, 6))
    for item in (data.get("programs") or [])[:18]:
        card = ctk.CTkFrame(frame, fg_color=CARD, corner_radius=16)
        card.pack(fill="x", pady=3)
        size = format_bytes(int(item.get("bytes") or 0)) if item.get("bytes") else "tamanho não informado"
        when = f" · {item.get('when')}" if item.get("when") else ""
        ctk.CTkLabel(card, text=f"{item.get('name')}  ·  {size}{when}", text_color=TEXT).pack(side="left", padx=14, pady=10)
        command = str(item.get("uninstall") or "")
        if not item.get("quiet"):
            app._ghost(card, "Desinstalar", lambda cmd=command: _open_uninstall(cmd)).pack(side="right", padx=12, pady=8)


def _rede(app, frame) -> None:
    data = app.care
    adapter = data.get("default_adapter") or "não identificada"
    vpn = ", ".join(data.get("vpn") or []) or "nenhuma VPN reconhecida pelo nome"
    names = ", ".join(str(item.get("name") or "") for item in data.get("adapters") or []) or "nenhum adaptador lido"
    _card(frame, "Conexão em uso", f"Saída padrão: {adapter}.\nAdaptadores: {names}.\nVPN pelo nome: {vpn}.")
    lines = [ping_line(item) for item in data.get("network") or []]
    _card(frame, "Ping medido na verificação", "\n".join(lines) or "A verificação ainda não mediu a rede.")
    app._gold_button(frame, "Medir o ping de novo", app._care_ping, width=220).pack(anchor="w", pady=6)
    dpi = data.get("dpi")
    scale = data.get("scale")
    scale_text = f"Escala aproximada {int(scale * 100)}% ({dpi} DPI)." if dpi and scale else "A escala da tela não foi lida."
    bright = data.get("brightness")
    bright_text = f"Brilho informado pelo monitor: {bright}%." if isinstance(bright, int) else "Este monitor não informa brilho pelo Windows."
    screen = ""
    if app.snapshot and app.snapshot.displays:
        item = next((row for row in app.snapshot.displays if row.primary), app.snapshot.displays[0])
        screen = f"Área: {item.width}×{item.height} a {item.hz} Hz. "
    battery = data.get("battery")
    if battery:
        plug = "na tomada" if battery.get("plugged") else "na bateria"
        power_text = f"Bateria em {battery.get('percent')}%, {plug}."
    else:
        power_text = "Nenhuma bateria detectada. Este PC está como desktop."
    _card(frame, "Tela e energia", screen + scale_text + " " + bright_text + " " + power_text)


def _jogos(app, frame) -> None:
    mode = normalize_use_mode(load_settings().get("use_mode") or "")
    shaders = app.care.get("shaders") or []
    if mode == "compartilhado":
        shaders = [item for item in shaders if item.get("scope") == "user"]
    ctk.CTkLabel(
        frame,
        text="Limpar o cache de shader deixa a primeira partida mais instável enquanto ele é refeito. Começa desmarcado.",
        text_color=WARN,
        wraplength=860,
        justify="left",
    ).pack(anchor="w", pady=(0, 6))
    if not shaders:
        ctk.CTkLabel(frame, text="Nenhuma pasta de shader encontrada para este usuário.", text_color=MUTED).pack(anchor="w")
    else:
        box = ctk.CTkFrame(frame, fg_color=CARD, corner_radius=16)
        box.pack(fill="x", pady=4)
        user_seen = False
        steam_seen = False
        for item in shaders:
            scope = item.get("scope")
            if scope == "user" and not user_seen:
                _check(app, box, "shader_user", "Caches da placa, só deste usuário")
                user_seen = True
            if scope == "steam" and not steam_seen and mode != "compartilhado":
                _check(app, box, "shader_steam", "Shaders da Steam dos jogos encontrados")
                steam_seen = True
            suffix = " (leitura parcial)" if item.get("partial") else ""
            ctk.CTkLabel(
                box,
                text=f"{item.get('label')}: {format_bytes(int(item.get('bytes') or 0))}{suffix}",
                text_color=MUTED,
            ).pack(anchor="w", padx=40, pady=1)
        ctk.CTkLabel(box, text="", height=8).pack()
        app._gold_button(frame, "Limpar os shaders marcados", app._care_cleanup, width=260).pack(anchor="w", pady=8)
    _card(
        frame,
        "Sobreposição do Discord",
        "Pausar vale na próxima abertura do Discord. A voz continua. O ORION guarda o arquivo anterior e cria um ponto de restauração antes de gravar.",
    )
    row = ctk.CTkFrame(frame, fg_color=BG)
    row.pack(fill="x", pady=4)
    app._gold_button(row, "Pausar overlay", lambda: app._care_discord("off"), width=180).pack(side="left", padx=(0, 8))
    app._ghost(row, "Devolver overlay", lambda: app._care_discord("on")).pack(side="left")


def _relatorio(app, frame) -> None:
    mode = normalize_use_mode(load_settings().get("use_mode") or "")
    _card(
        frame,
        "Uso deste PC",
        f"Perfil de uso: {USE_LABELS.get(mode, 'Jogos')}. "
        "Escritório e uso leve não desmarcam correções de jogo; elas continuam na aba Correções. "
        "PC compartilhado deixa as outras contas fora das pastas e dos shaders da Steam.",
    )
    compared = compare_history(list_history())
    if not compared.get("ok"):
        text = compared.get("message") or ""
    else:
        text = (
            f"Nota {compared.get('score_prev')} em {compared.get('when_prev')} "
            f"e nota {compared.get('score_now')} em {compared.get('when_now')}."
        )
        added = compared.get("added") or []
        gone = compared.get("gone") or []
        if added:
            text += "\nNovos: " + "; ".join(added)
        if gone:
            text += "\nNão apareceram de novo: " + "; ".join(gone)
        if not added and not gone:
            text += "\nA lista de pontos de atenção está igual."
    _card(frame, "Desde a verificação anterior", text)
    row = ctk.CTkFrame(frame, fg_color=BG)
    row.pack(fill="x", pady=8)
    app._gold_button(row, "Salvar relatório em texto", app._care_export_report, width=240).pack(side="left", padx=(0, 8))
    app._ghost(row, "Salvar cópia das configs", app._care_export_configs).pack(side="left")


def _open_folder(folder: str) -> None:
    path = Path(folder or "")
    if not path.exists():
        messagebox_info("A pasta não está neste computador.")
        return
    os.startfile(path if path.is_dir() else path.parent)


def _open_apps() -> None:
    os.startfile("ms-settings:appsfeatures")


def _open_uninstall(command: str) -> None:
    import ctypes

    from orion.scanner.care import uninstall_is_visible

    if not uninstall_is_visible(command):
        _open_apps()
        return
    if not messagebox_yesno("Abrir o desinstalador deste programa? O ORION não remove nada por conta própria."):
        return
    ctypes.windll.shell32.ShellExecuteW(None, "open", "cmd.exe", f'/c start "" {command}', None, 0)
