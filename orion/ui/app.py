"""Janela do ORION. A primeira ação é Verificar Agora. Escrever no sistema continua na aba Correções."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
from PIL import Image

from orion import __version__
from orion.ai.analyst import Analysis, analyze
from orion.ai.monitor import PROFILE_LABEL, Verdict, review, verify_corrections
from orion.fixer.actions import available_fixes, build_plan
from orion.fixer.apply import apply_file, revert_last
from orion.fixer.debloat import CATALOG as DEBLOAT_CATALOG
from orion.fixer.debloat import build_debloat_plan, inspect as inspect_debloat, pending as debloat_pending
from orion.fixer.elevate import launch_elevated
from orion.models import GameEntry, Issue, Snapshot
from orion.paths import data_dir, resource_path
from orion.scanner.engine import run_scan
from orion.store import list_history, load_settings, save_history, save_settings
from orion.updater import install, look_up, remember_sha, worktree_dirty
from orion.winutil import is_admin

ctk.set_appearance_mode("dark")
log = logging.getLogger("orion")

BG = "#09090b"
RAIL = "#101014"
CARD = "#16161c"
TEXT = "#f4f1ea"
MUTED = "#9c978c"
GOLD = "#d4b483"
GOLD_TEXT = "#1a1408"
OK = "#7dcea0"
WARN = "#e0b15a"
BAD = "#e07a7a"
NAV_ON = "#2a241c"
GHOST = "#221e18"
LINE = "#2c2924"

SEVERITY_COLOR = {
    "critico": BAD,
    "alto": WARN,
    "medio": GOLD,
    "baixo": "#a8b4c4",
    "info": MUTED,
}

NAV = (
    ("Início", "inicio"),
    ("Computador", "computador"),
    ("Jogos", "jogos"),
    ("Resultados", "resultados"),
    ("Correções", "correcoes"),
    ("Debloat", "debloat"),
    ("Configurações", "configuracoes"),
    ("Histórico", "historico"),
)

PROFILE_MENU = (
    ("Automático", ""),
    ("PC fraco", "fraco"),
    ("Equilibrado", "equilibrado"),
    ("PC forte", "forte"),
)


class OrionApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ORION")
        self.geometry("1280x820")
        self.minsize(1100, 700)
        self.configure(fg_color=BG)
        self.snapshot: Snapshot | None = None
        self.analysis: Analysis | None = None
        self.verdict: Verdict | None = None
        self.page = "entrada"
        self.unlocked = False
        self.scanning = False
        self.applying = False
        self.scan_id = 0
        self.fix_vars: dict[str, tk.BooleanVar] = {}
        self.debloat_vars: dict[str, tk.BooleanVar] = {}
        self.fix_lines = "Nenhuma correção foi aplicada nesta sessão.\n"
        self.debloat_lines = "Nenhuma remoção foi aplicada nesta sessão.\n"
        self.debloat_state: dict | None = None
        self.debloat_error = ""
        self.debloat_loading = False
        self.debloat_token = 0
        self.verification_lines: list[str] = []
        self._awaiting_apply: dict | None = None
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        self._logo = None
        self._prepare_brand()
        self._build()
        self.show_page("entrada")
        self.after(1800, self._kick_model)
        self.after(2200, self._maybe_auto_update)

    def _prepare_brand(self) -> None:
        png = resource_path("orion", "ui", "assets", "orion.png")
        ico = resource_path("orion", "ui", "assets", "orion.ico")
        if png.is_file():
            try:
                image = Image.open(png)
                self._logo_image = image
                self._logo = ctk.CTkImage(light_image=image, dark_image=image, size=(36, 36))
            except Exception:
                log.exception("icone")
                self._logo = None
        if ico.is_file():
            try:
                self.iconbitmap(default=str(ico))
            except tk.TclError:
                try:
                    self.iconbitmap(str(ico))
                except tk.TclError:
                    log.exception("icone da janela")

    def _build(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        side = ctk.CTkFrame(self, width=232, fg_color=RAIL, corner_radius=0)
        side.grid(row=0, column=0, sticky="nsew")
        side.grid_propagate(False)
        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(anchor="w", fill="x", padx=18, pady=(22, 0))
        if self._logo is not None:
            ctk.CTkLabel(brand, image=self._logo, text="").pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            brand,
            text="ORION",
            font=ctk.CTkFont(family="Segoe UI", size=28, weight="bold"),
            text_color=GOLD,
        ).pack(side="left")
        ctk.CTkFrame(side, height=2, fg_color=GOLD).pack(fill="x", padx=22, pady=(10, 8))
        ctk.CTkLabel(side, text="Desempenho dos jogos", text_color=MUTED, font=ctk.CTkFont(size=12)).pack(
            anchor="w", padx=22, pady=(0, 18)
        )
        for label, page_id in NAV:
            button = ctk.CTkButton(
                side,
                text=label,
                anchor="w",
                fg_color="transparent",
                hover_color="#1c1a17",
                text_color=MUTED,
                height=40,
                command=lambda page=page_id: self.show_page(page),
            )
            button.pack(fill="x", padx=12, pady=2)
            self.nav_buttons[page_id] = button
        self.admin_label = ctk.CTkLabel(
            side, text="", text_color=MUTED, font=ctk.CTkFont(size=11), wraplength=190, justify="left"
        )
        self.admin_label.pack(side="bottom", anchor="w", padx=18, pady=(0, 8))
        ctk.CTkLabel(side, text=f"v{__version__}", text_color=MUTED, font=ctk.CTkFont(size=11)).pack(
            side="bottom", anchor="w", padx=22, pady=14
        )
        self._refresh_admin()
        self._paint_nav()
        self.content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=12)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.status = ctk.CTkLabel(self, text="Pronto. A verificação só lê o computador.", text_color=MUTED, anchor="w")
        self.status.grid(row=1, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 10))

    def _refresh_admin(self) -> None:
        if is_admin():
            self.admin_label.configure(text="Executando como administrador.")
        else:
            self.admin_label.configure(text="A verificação não precisa de admin.\nCorreção e Debloat pedem permissão na hora.")

    def _paint_nav(self) -> None:
        for page_id, button in self.nav_buttons.items():
            if not self.unlocked:
                button.configure(state="disabled", fg_color="transparent", text_color=MUTED)
                continue
            active = page_id == self.page
            button.configure(
                state="normal",
                fg_color=NAV_ON if active else "transparent",
                text_color=GOLD if active else TEXT,
            )

    def show_page(self, name: str) -> None:
        if not self.unlocked and name != "entrada":
            return
        self.page = name
        self._paint_nav()
        for child in self.content.winfo_children():
            child.destroy()
        pages = {
            "entrada": self._page_entry,
            "inicio": self._page_home,
            "computador": self._page_pc,
            "jogos": self._page_games,
            "resultados": self._page_issues,
            "correcoes": self._page_fixes,
            "debloat": self._page_debloat,
            "configuracoes": self._page_settings,
            "historico": self._page_history,
        }
        pages[name]()

    def _set_status(self, text: str) -> None:
        self.status.configure(text=text)
        label = getattr(self, "entry_status", None)
        if label is not None:
            try:
                if label.winfo_exists():
                    label.configure(text=text)
            except tk.TclError:
                pass

    def _kick_model(self) -> None:
        if os.environ.get("ORION_SKIP_MODEL") == "1":
            return
        from orion.ai.remote_check import configured

        if configured():
            return
        threading.Thread(target=self._model_worker, daemon=True).start()

    def _model_worker(self) -> None:
        try:
            from orion.ai.local_model import ensure

            if not ensure():
                return
        except Exception:
            log.exception("componente interno")
            return
        token = self.scan_id
        snapshot = self.snapshot
        if snapshot is None or self.scanning or self.applying:
            return
        verdict = review(snapshot)
        self.after(0, lambda item=verdict, mark=token: self._apply_quiet(item, mark))

    def _apply_quiet(self, verdict: Verdict, token: int) -> None:
        if token != self.scan_id or self.scanning or not self.unlocked:
            return
        self.verdict = verdict
        self._set_status("A verificação interna atualizou as marcações.")
        if self.page == "inicio":
            self.show_page("inicio")

    def _maybe_auto_update(self) -> None:
        if os.environ.get("ORION_SKIP_UPDATE") == "1":
            return
        settings = load_settings()
        if not settings.get("auto_update"):
            return
        threading.Thread(target=self._auto_update_worker, daemon=True).start()

    def _auto_update_worker(self) -> None:
        remote = look_up()
        if not remote.ok:
            self.after(0, lambda message=remote.message: self._set_status(message))
            return
        if remote.kind == "first":
            remember_sha(remote.sha)
            self.after(0, lambda: self._set_status("Referência de atualização anotada. Nada foi substituído."))
            return
        if remote.kind != "new":
            return
        if worktree_dirty():
            self.after(
                0,
                lambda: self._set_status("Atualização automática adiada: a pasta do programa tem alterações locais."),
            )
            return
        report = install(remote.sha)
        self.after(0, lambda item=report: self._update_finished(item))

    def start_scan(self) -> None:
        if self.scanning or self.applying:
            return
        self.scanning = True
        self.scan_id += 1
        token = self.scan_id
        button = getattr(self, "verify_button", None)
        if button is not None:
            try:
                if button.winfo_exists():
                    button.configure(state="disabled")
            except tk.TclError:
                pass
        self._set_status("Lendo bibliotecas e o hardware. Nada está sendo alterado.")
        threading.Thread(target=lambda: self._scan_worker(token), daemon=True).start()

    def _scan_worker(self, token: int) -> None:
        try:
            snapshot = run_scan(lambda message: self.after(0, lambda text=message: self._set_status(text)))
            self.after(0, lambda: self._set_status("Conferindo a leitura deste computador."))
            report = analyze(snapshot)
            verdict = review(snapshot)
            try:
                save_history(snapshot, report.score, report.headline, verdict.profile)
            except OSError:
                pass
        except Exception as error:
            self.after(0, lambda message=str(error): self._scan_failed(message))
            return
        self.after(0, lambda: self._scan_done(snapshot, report, verdict, token))

    def _scan_failed(self, message: str) -> None:
        self.scanning = False
        self._set_status("A verificação não terminou.")
        button = getattr(self, "verify_button", None)
        if button is not None:
            try:
                if button.winfo_exists():
                    button.configure(state="normal")
            except tk.TclError:
                pass
        messagebox_error(message)

    def _scan_done(self, snapshot: Snapshot, report: Analysis, verdict: Verdict, token: int) -> None:
        if token != self.scan_id:
            self.scanning = False
            return
        pending = self._awaiting_apply
        self.snapshot = snapshot
        self.analysis = report
        self.verdict = verdict
        self.scanning = False
        if pending is not None:
            self.verification_lines = verify_corrections(
                pending["before"],
                snapshot,
                pending["ids"],
                pending.get("steps") or [],
                reboot=bool(pending.get("reboot")),
            )
            self._awaiting_apply = None
        problems = len([issue for issue in snapshot.issues if issue.severity in {"critico", "alto", "medio"}])
        self._set_status(
            f"Leitura de {snapshot.scanned_at}. {len(snapshot.games)} jogos, {problems} pontos de atenção. Nota {report.score}/100."
        )
        if not self.unlocked:
            self.unlocked = True
            self.show_page("inicio")
            return
        self.show_page(self.page if self.page != "entrada" else "inicio")

    def _page_entry(self) -> None:
        frame = ctk.CTkFrame(self.content, fg_color=BG)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        box = ctk.CTkFrame(frame, fg_color=BG)
        box.grid(row=0, column=0)
        ctk.CTkLabel(box, text="ORION", font=ctk.CTkFont(family="Segoe UI", size=54, weight="bold"), text_color=GOLD).pack()
        ctk.CTkLabel(
            box,
            text="Desempenho dos jogos neste computador.",
            text_color=TEXT,
            font=ctk.CTkFont(size=18),
        ).pack(pady=(8, 22))
        self.verify_button = ctk.CTkButton(
            box,
            text="Verificar Agora",
            width=280,
            height=54,
            fg_color=GOLD,
            hover_color="#e2c79a",
            text_color=GOLD_TEXT,
            font=ctk.CTkFont(size=18, weight="bold"),
            command=self.start_scan,
        )
        self.verify_button.pack()
        self.entry_status = ctk.CTkLabel(box, text="", text_color=MUTED, wraplength=520, justify="center")
        self.entry_status.pack(pady=(16, 0))
        ctk.CTkLabel(
            box,
            text="As outras seções abrem depois desta verificação. Nesta etapa nada é alterado.",
            text_color=MUTED,
            wraplength=520,
            justify="center",
        ).pack(pady=(18, 0))

    def _page_home(self) -> None:
        frame = ctk.CTkScrollableFrame(self.content, fg_color=BG)
        frame.grid(row=0, column=0, sticky="nsew")
        header = ctk.CTkFrame(frame, fg_color=BG)
        header.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(header, text="Início", font=ctk.CTkFont(size=28, weight="bold"), text_color=TEXT).pack(side="left")
        self._gold_button(header, "Verificar de novo", self.start_scan, width=160).pack(side="right")
        if not self.snapshot or not self.analysis or not self.verdict:
            ctk.CTkLabel(frame, text="A verificação ainda não terminou.", text_color=TEXT).pack(anchor="w", pady=12)
            return
        snap = self.snapshot
        report = self.analysis
        verdict = self.verdict
        top = ctk.CTkFrame(frame, fg_color=BG)
        top.pack(fill="x", pady=8)
        score = tk.Canvas(top, width=150, height=150, bg=BG, highlightthickness=0)
        score.pack(side="left", padx=(0, 18))
        self._draw_score(score, report.score)
        text = ctk.CTkFrame(top, fg_color=BG)
        text.pack(side="left", fill="both", expand=True)
        chip = PROFILE_LABEL.get(verdict.profile, verdict.profile)
        ctk.CTkLabel(text, text=chip.upper(), text_color=GOLD, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(
            text, text=report.headline, text_color=TEXT, font=ctk.CTkFont(size=18, weight="bold"), wraplength=760, justify="left"
        ).pack(anchor="w", pady=(6, 0))
        ctk.CTkLabel(text, text=verdict.summary, text_color=MUTED, wraplength=760, justify="left").pack(anchor="w", pady=(8, 0))
        ctk.CTkLabel(text, text=report.bottleneck, text_color=TEXT, wraplength=760, justify="left").pack(anchor="w", pady=(8, 0))
        if self.verification_lines:
            card = ctk.CTkFrame(frame, fg_color=CARD, corner_radius=14)
            card.pack(fill="x", pady=(14, 4))
            ctk.CTkLabel(
                card, text="Conferência das correções", text_color=GOLD, font=ctk.CTkFont(size=16, weight="bold")
            ).pack(anchor="w", padx=16, pady=(12, 4))
            for line in self.verification_lines:
                ctk.CTkLabel(card, text=line, text_color=TEXT, wraplength=860, justify="left").pack(anchor="w", padx=16, pady=1)
            ctk.CTkLabel(card, text="", height=8).pack()
        stats = ctk.CTkFrame(frame, fg_color=BG)
        stats.pack(fill="x", pady=12)
        gpu = snap.gpus[0].name if snap.gpus else "Placa não lida"
        vram = f" · {snap.gpus[0].vram_gb:.0f} GB" if snap.gpus and snap.gpus[0].vram_gb else ""
        hz = ""
        if snap.displays:
            screen = next((item for item in snap.displays if item.primary), snap.displays[0])
            hz = f"{screen.width}×{screen.height} @{screen.hz} Hz"
        cards = [
            ("Processador", snap.cpu_name.strip(), f"{snap.cpu_max_mhz:.0f} MHz · {snap.cpu_percent:.0f}% agora"),
            ("Placa", gpu, (snap.gpus[0].driver_version if snap.gpus else "") + vram),
            ("Memória", f"{snap.ram_available_gb:.1f} GB livres", f"de {snap.ram_total_gb:.1f} GB"),
            ("Tela", hz or "não lida", snap.power_plan or "plano de energia não lido"),
        ]
        for title, value, detail in cards:
            self._stat(stats, title, value, detail)
        ctk.CTkLabel(frame, text="Principais causas", text_color=TEXT, font=ctk.CTkFont(size=18, weight="bold")).pack(
            anchor="w", pady=(8, 4)
        )
        shown = [issue for issue in snap.issues if issue.severity in {"critico", "alto"}][:4]
        if not shown:
            ctk.CTkLabel(frame, text="Nenhum problema crítico ou alto nesta leitura.", text_color=OK).pack(anchor="w")
        for issue in shown:
            self._issue_card(frame, issue, compact=True)
        if snap.healthy:
            ctk.CTkLabel(frame, text="O que já está bem", text_color=OK, font=ctk.CTkFont(size=16, weight="bold")).pack(
                anchor="w", pady=(12, 4)
            )
            for line in snap.healthy[:4]:
                ctk.CTkLabel(frame, text="• " + line, text_color=TEXT, wraplength=860, justify="left").pack(anchor="w")
        if snap.notes:
            ctk.CTkLabel(
                frame, text="Avisos da leitura: " + " | ".join(snap.notes), text_color=WARN, wraplength=860, justify="left"
            ).pack(anchor="w", pady=8)

    def _draw_score(self, canvas: tk.Canvas, score: int) -> None:
        color = BAD if score < 45 else WARN if score < 75 else OK
        canvas.create_oval(12, 12, 138, 138, outline=LINE, width=10)
        canvas.create_arc(12, 12, 138, 138, start=90, extent=-360 * score / 100, style="arc", outline=color, width=10)
        canvas.create_text(75, 68, text=str(score), fill=TEXT, font=("Segoe UI", 32, "bold"))
        canvas.create_text(75, 100, text="de 100", fill=MUTED, font=("Segoe UI", 10))

    def _stat(self, parent, title: str, value: str, detail: str) -> None:
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14)
        card.pack(side="left", fill="both", expand=True, padx=4)
        ctk.CTkLabel(card, text=title.upper(), text_color=GOLD, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=14, pady=(12, 0))
        ctk.CTkLabel(
            card, text=value, text_color=TEXT, font=ctk.CTkFont(size=14, weight="bold"), wraplength=210, justify="left"
        ).pack(anchor="w", padx=14, pady=(4, 0))
        ctk.CTkLabel(card, text=detail, text_color=MUTED, font=ctk.CTkFont(size=12), wraplength=210, justify="left").pack(
            anchor="w", padx=14, pady=(2, 14)
        )

    def _page_pc(self) -> None:
        frame = ctk.CTkScrollableFrame(self.content, fg_color=BG)
        frame.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(frame, text="Computador", font=ctk.CTkFont(size=28, weight="bold"), text_color=TEXT).pack(anchor="w")
        if not self.snapshot:
            return
        snap = self.snapshot
        rows = [
            ("Sistema", f"{snap.os_name} {snap.os_version}".strip()),
            ("Nome", snap.hostname),
            ("Ligado há", f"{snap.uptime_hours:.0f} horas"),
            ("Placa-mãe", snap.board or "não lida"),
            ("Processador", snap.cpu_name.strip()),
            ("Núcleos", f"{snap.cpu_cores} físicos, {snap.cpu_threads} lógicos"),
            ("Clock", f"máximo {snap.cpu_max_mhz:.0f} MHz, agora {snap.cpu_current_mhz:.0f} MHz"),
            ("Uso da CPU", f"{snap.cpu_percent:.0f}% no total, núcleo mais ocupado {snap.cpu_busiest_core:.0f}%"),
            ("Memória", f"{snap.ram_used_gb:.1f} GB em uso, {snap.ram_available_gb:.1f} GB livres, {snap.ram_total_gb:.1f} GB no total"),
            ("Pentes", f"{snap.ram_sticks} · {snap.ram_speed_mhz or 'velocidade não lida'} MHz"),
            ("Energia", f"{snap.power_plan or 'sem nome'} ({snap.power_guid or 'sem GUID'})"),
            ("Modo de Jogo", self._yesno(snap.game_mode)),
            ("Game DVR", self._yesno(snap.game_dvr)),
            ("Game Bar", self._yesno(snap.game_bar)),
            ("HAGS", {1: "desligado", 2: "ligado"}.get(snap.hags_mode or 0, "não definido")),
            ("Aceleração do mouse", self._yesno(snap.mouse_accel)),
            ("Reinício pendente", "sim" if snap.pending_reboot else "não"),
        ]
        for title, value in rows:
            self._kv(frame, title, value)
        self._block_title(frame, "Placas de vídeo")
        if not snap.gpus:
            ctk.CTkLabel(frame, text="Nenhuma placa dedicada foi listada.", text_color=MUTED).pack(anchor="w")
        for gpu in snap.gpus:
            vram = f"{gpu.vram_gb:.0f} GB" if gpu.vram_gb else "VRAM não confiável nesta leitura"
            self._kv(frame, gpu.vendor.upper(), f"{gpu.name} · driver {gpu.driver_version or '?'} · {gpu.driver_date or 'data não lida'} · {vram}")
        self._block_title(frame, "Monitores")
        for display in snap.displays:
            flag = "principal" if display.primary else "secundário"
            self._kv(frame, display.name or "Monitor", f"{display.width}×{display.height} @{display.hz} Hz · {flag}")
        self._block_title(frame, "Discos")
        for disk in snap.disks:
            self._kv(
                frame,
                f"{disk.letter}: {disk.media}",
                f"{disk.name} · {disk.bus} · {disk.free_gb:.0f} GB livres de {disk.total_gb:.0f} GB · {disk.health or 'saúde não lida'}",
            )
        self._block_title(frame, "Rede ativa")
        if not snap.adapters:
            ctk.CTkLabel(frame, text="Nenhum adaptador ativo foi listado.", text_color=MUTED).pack(anchor="w")
        for adapter in snap.adapters:
            self._kv(frame, adapter.get("name") or "Adaptador", f"{adapter.get('media') or ''} · {adapter.get('speed') or ''}")
        for probe in snap.network:
            self._kv(frame, f"Ping {probe.get('label')}", f"{probe.get('host')} · {probe.get('avg_ms')} ms · perda {probe.get('loss_percent')}%")
        self._block_title(frame, "Programas que mais ocupam memória")
        for proc in snap.processes[:12]:
            note = f" — {proc.note}" if proc.note else ""
            self._kv(frame, proc.name, f"{proc.rss_mb:.0f} MB · {proc.cpu:.0f}% CPU{note}")
        self._block_title(frame, "Inicialização")
        if not snap.startups:
            ctk.CTkLabel(frame, text="Nenhum programa na inicialização do Windows.", text_color=MUTED).pack(anchor="w")
        for item in snap.startups:
            mark = "pesado" if item.heavy else "leve"
            self._kv(frame, item.name, f"{mark} · {item.location}")

    def _block_title(self, parent, title: str) -> None:
        ctk.CTkLabel(parent, text=title, font=ctk.CTkFont(size=18, weight="bold"), text_color=TEXT).pack(anchor="w", pady=(16, 4))

    def _yesno(self, value: bool | None) -> str:
        if value is True:
            return "ligado"
        if value is False:
            return "desligado"
        return "não confirmado"

    def _kv(self, parent, title: str, value: str) -> None:
        row = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10)
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text=title, width=180, anchor="w", text_color=MUTED).pack(side="left", padx=12, pady=8)
        ctk.CTkLabel(row, text=value, anchor="w", text_color=TEXT, wraplength=700, justify="left").pack(side="left", padx=8, pady=8)

    def _page_games(self) -> None:
        frame = ctk.CTkScrollableFrame(self.content, fg_color=BG)
        frame.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(frame, text="Jogos", font=ctk.CTkFont(size=28, weight="bold"), text_color=TEXT).pack(anchor="w")
        profile = self.verdict.profile if self.verdict else ""
        if profile == "fraco":
            intro = "Perfil PC fraco: prioridade em latência, preset mais leve e disco. Serve para máquina modesta e para quem joga competitivo."
        elif profile == "forte":
            intro = "Perfil PC forte: prioridade em latência. O preset baixo do CS2 não entra marcado, para não achatar uma placa que segura gráfico."
        else:
            intro = "Perfil equilibrado: latência primeiro. O preset do CS2 só entra se a placa ou as opções atuais pedirem."
        ctk.CTkLabel(frame, text=intro, text_color=MUTED, wraplength=880, justify="left").pack(anchor="w", pady=(4, 10))
        if not self.snapshot:
            return
        if not self.snapshot.games:
            ctk.CTkLabel(frame, text="Nenhum jogo encontrado nas bibliotecas.", text_color=WARN).pack(anchor="w")
            return
        advice = {name: text for name, text in (self.analysis.per_game if self.analysis else [])}
        for game in self.snapshot.games:
            self._game_card(frame, game, advice.get(game.name, ""))

    def _game_card(self, frame, game: GameEntry, advice: str) -> None:
        card = ctk.CTkFrame(frame, fg_color=CARD, corner_radius=14)
        card.pack(fill="x", pady=6)
        ctk.CTkLabel(
            card, text=f"{game.name}   ·   {game.platform}", text_color=TEXT, font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", padx=16, pady=(12, 0))
        size = f"{game.size_bytes / (1024 ** 3):.0f} GB" if game.size_bytes else "tamanho não lido"
        media = f"{game.drive_media} {game.drive_letter}:" if game.drive_letter else "disco não identificado"
        ctk.CTkLabel(card, text=f"{media} · {game.drive_name} · {size} · perfil {game.profile}", text_color=MUTED).pack(
            anchor="w", padx=16
        )
        note = self._game_note(game)
        if note:
            ctk.CTkLabel(card, text=note, text_color=GOLD, wraplength=860, justify="left").pack(anchor="w", padx=16, pady=(4, 0))
        if advice:
            ctk.CTkLabel(card, text=advice, text_color=TEXT, wraplength=860, justify="left").pack(anchor="w", padx=16, pady=(4, 0))
        if game.install_dir:
            ctk.CTkLabel(card, text=game.install_dir, text_color=MUTED, wraplength=860, justify="left").pack(anchor="w", padx=16, pady=(2, 0))
        row = ctk.CTkFrame(card, fg_color=CARD)
        row.pack(fill="x", padx=12, pady=(8, 12))
        can_open = (game.platform.lower() == "steam" and str(game.app_id).isdigit()) or bool(game.executable)
        self._ghost(row, "Abrir jogo", lambda item=game: self._open_game(item), enabled=can_open).pack(side="left", padx=4)
        self._ghost(row, "Abrir pasta", lambda item=game: self._open_folder(item.install_dir), enabled=bool(game.install_dir)).pack(
            side="left", padx=4
        )
        self._ghost(row, "Configurações", lambda item=game: self._game_settings(item)).pack(side="left", padx=4)
        path = game.install_dir or game.executable
        self._ghost(row, "Copiar caminho", lambda item=path: self._copy(item), enabled=bool(path)).pack(side="left", padx=4)

    def _game_note(self, game: GameEntry) -> str:
        profile = self.verdict.profile if self.verdict else ""
        if profile == "fraco" and game.drive_media == "HDD":
            return "Neste perfil o disco mecânico pesa mais do que subir o gráfico."
        if profile == "forte" and game.profile == "cs2":
            return "Neste perfil o preset baixo do CS2 fica desmarcado."
        if profile == "fraco" and game.drive_media == "SSD" and game.profile in {"cs2", "rocket_league", "heavy"}:
            return "Já está em SSD. Neste perfil o que resta é latência e, se couber, um preset mais leve."
        return ""

    def _open_game(self, game: GameEntry) -> None:
        try:
            if game.platform.lower() == "steam" and str(game.app_id).isdigit():
                os.startfile(f"steam://rungameid/{game.app_id}")
                self._set_status(f"Abrindo {game.name} pela Steam.")
                return
            exe = Path(game.executable)
            if exe.is_file():
                subprocess.Popen([str(exe)], cwd=str(exe.parent))
                self._set_status(f"Abrindo {game.name}.")
                return
        except OSError as error:
            messagebox_error(str(error))
            return
        messagebox_info("O executável deste jogo não foi encontrado.")

    def _open_folder(self, path: str) -> None:
        folder = Path(path) if path else Path()
        if not path or not folder.exists():
            messagebox_info("A pasta não está neste computador.")
            return
        target = folder if folder.is_dir() else folder.parent
        try:
            os.startfile(str(target))
        except OSError as error:
            messagebox_error(str(error))
            return
        self._set_status("Pasta aberta.")

    def _copy(self, text: str) -> None:
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self._set_status("Caminho copiado.")

    def _open_target(self, path: str, missing: str) -> None:
        if path.startswith("ms-settings:"):
            try:
                os.startfile(path)
            except OSError as error:
                messagebox_error(str(error))
            return
        if not path or not Path(path).exists():
            messagebox_info(missing)
            return
        try:
            os.startfile(path)
        except OSError as error:
            messagebox_error(str(error))

    def _game_settings(self, game: GameEntry) -> None:
        window = ctk.CTkToplevel(self)
        window.title(game.name)
        window.geometry("760x620")
        window.configure(fg_color=BG)
        window.transient(self)
        body = ctk.CTkScrollableFrame(window, fg_color=BG)
        body.pack(fill="both", expand=True, padx=16, pady=16)
        ctk.CTkLabel(body, text=game.name, text_color=TEXT, font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(
            body,
            text=f"{game.platform} · perfil {game.profile} · {game.drive_media or 'disco não identificado'} {game.drive_letter}",
            text_color=MUTED,
        ).pack(anchor="w", pady=(2, 8))
        self._kv(body, "Pasta", game.install_dir or "não encontrada")
        self._kv(body, "Executável", game.executable or "não encontrado")
        config_path, config_values = self._game_config(game)
        if config_path:
            self._kv(body, "Arquivo", config_path)
        for key, value in config_values:
            self._kv(body, key, value)
        row = ctk.CTkFrame(body, fg_color=BG)
        row.pack(fill="x", pady=(12, 4))
        self._ghost(row, "Abrir jogo", lambda item=game: self._open_game(item)).pack(side="left", padx=(0, 6))
        self._ghost(row, "Abrir pasta", lambda item=game: self._open_folder(item.install_dir)).pack(side="left", padx=6)
        if config_path:
            self._ghost(row, "Abrir arquivo", lambda item=config_path: self._open_target(item, "Arquivo não encontrado.")).pack(
                side="left", padx=6
            )
            self._ghost(row, "Pasta da configuração", lambda item=config_path: self._open_folder(str(Path(item).parent))).pack(
                side="left", padx=6
            )
        row2 = ctk.CTkFrame(body, fg_color=BG)
        row2.pack(fill="x", pady=(4, 8))
        self._ghost(row2, "Gráficos do Windows", lambda: self._open_target("ms-settings:display", "Não foi possível abrir.")).pack(
            side="left", padx=(0, 6)
        )
        self._ghost(
            row2, "Modo de Jogo", lambda: self._open_target("ms-settings:gaming-gamemode", "Não foi possível abrir.")
        ).pack(side="left", padx=6)
        self._ghost(row2, "Ir para correções", lambda: self._jump_fixes(window)).pack(side="left", padx=6)
        ctk.CTkLabel(
            body,
            text="PC fraco ganha mais com preset leve, VSync desligado e jogo em SSD. PC forte ganha mais com latência, sem ser forçado ao preset baixo.",
            text_color=MUTED,
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))
        window.after(80, window.lift)

    def _jump_fixes(self, window) -> None:
        window.destroy()
        self.show_page("correcoes")

    def _game_config(self, game: GameEntry) -> tuple[str, list[tuple[str, str]]]:
        configs = (self.snapshot.configs if self.snapshot else {}) or {}
        if game.profile == "cs2":
            block = configs.get("cs2") or {}
            values = block.get("values") or {}
            keys = [
                "setting.defaultres",
                "setting.defaultresheight",
                "setting.mat_vsync",
                "setting.cpu_level",
                "setting.gpu_level",
                "setting.msaa_samples",
                "setting.videocfg_shadow_quality",
                "setting.fullscreen",
                "setting.coop_fullscreen",
                "setting.r_low_latency",
            ]
            shown = [(key.replace("setting.", ""), str(values[key])) for key in keys if key in values]
            return str(block.get("video_path") or ""), shown
        if game.profile == "rocket_league":
            block = configs.get("rocket_league") or {}
            values = block.get("values") or {}
            keys = (
                "UseVsync",
                "OneFrameThreadLag",
                "AllowPerFrameSleep",
                "DynamicShadows",
                "ResX",
                "ResY",
                "Borderless",
                "Fullscreen",
                "UpscaleScreenPercentage",
            )
            shown = [(key, str(values[key])) for key in keys if key in values]
            return str(block.get("ini_path") or ""), shown
        return "", []

    def _page_issues(self) -> None:
        frame = ctk.CTkScrollableFrame(self.content, fg_color=BG)
        frame.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(frame, text="Resultados", font=ctk.CTkFont(size=28, weight="bold"), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(
            frame,
            text="Cada item diz a causa, a evidência medida neste PC e o que muda se for corrigido. Melhora é estimativa, não FPS prometido.",
            text_color=MUTED,
            wraplength=880,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        if not self.snapshot:
            return
        for issue in self.snapshot.issues:
            self._issue_card(frame, issue, compact=False)
        if self.snapshot.healthy:
            ctk.CTkLabel(frame, text="O que já está bem", font=ctk.CTkFont(size=18, weight="bold"), text_color=OK).pack(
                anchor="w", pady=(12, 4)
            )
            for line in self.snapshot.healthy:
                ctk.CTkLabel(frame, text="• " + line, text_color=TEXT, wraplength=880, justify="left").pack(anchor="w", pady=1)

    def _issue_card(self, parent, issue: Issue, compact: bool) -> None:
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14)
        card.pack(fill="x", pady=5)
        top = ctk.CTkFrame(card, fg_color=CARD)
        top.pack(fill="x", padx=14, pady=(12, 0))
        ctk.CTkLabel(
            top,
            text=issue.severity.upper(),
            text_color=SEVERITY_COLOR.get(issue.severity, TEXT),
            font=ctk.CTkFont(size=11, weight="bold"),
            width=70,
        ).pack(side="left")
        ctk.CTkLabel(top, text=issue.category, text_color=MUTED, font=ctk.CTkFont(size=11)).pack(side="left", padx=8)
        if issue.fix_id:
            ctk.CTkLabel(top, text="corrigível", text_color=OK, font=ctk.CTkFont(size=11)).pack(side="right")
        ctk.CTkLabel(
            card, text=issue.title, text_color=TEXT, font=ctk.CTkFont(size=15, weight="bold"), wraplength=860, justify="left"
        ).pack(anchor="w", padx=14, pady=(4, 0))
        if compact:
            ctk.CTkLabel(card, text=issue.impact, text_color=MUTED, wraplength=860, justify="left").pack(anchor="w", padx=14, pady=(2, 12))
            return
        ctk.CTkLabel(card, text="Causa", text_color=GOLD, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=14, pady=(8, 0))
        ctk.CTkLabel(card, text=issue.cause, text_color=TEXT, wraplength=860, justify="left").pack(anchor="w", padx=14)
        ctk.CTkLabel(card, text="Evidência", text_color=GOLD, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=14, pady=(6, 0))
        ctk.CTkLabel(card, text=issue.evidence, text_color=MUTED, wraplength=860, justify="left").pack(anchor="w", padx=14)
        ctk.CTkLabel(card, text="Melhora esperada", text_color=OK, font=ctk.CTkFont(size=12, weight="bold")).pack(
            anchor="w", padx=14, pady=(6, 0)
        )
        ctk.CTkLabel(card, text=issue.impact, text_color=TEXT, wraplength=860, justify="left").pack(anchor="w", padx=14, pady=(0, 14))

    def _page_fixes(self) -> None:
        frame = ctk.CTkScrollableFrame(self.content, fg_color=BG)
        frame.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(frame, text="Correções", font=ctk.CTkFont(size=28, weight="bold"), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(
            frame,
            text=(
                "As marcações já vieram da verificação deste computador. "
                "Antes de qualquer escrita o ORION cria um ponto de restauração. "
                "Se o ponto falhar, nada é modificado. Arquivos do CS2 e do Rocket League ganham uma cópia em data\\backups, "
                "porque a Restauração do Windows não cobre a pasta Documentos."
            ),
            text_color=MUTED,
            wraplength=880,
            justify="left",
        ).pack(anchor="w", pady=(4, 8))
        if not self.snapshot:
            return
        fixes = available_fixes(self.snapshot)
        approved = set(self.verdict.approved) if self.verdict else None
        held = self.verdict.held if self.verdict else {}
        self.fix_vars = {}
        if not fixes:
            ctk.CTkLabel(frame, text="Nenhuma correção automática se aplica a esta leitura.", text_color=OK).pack(anchor="w")
        for item in fixes:
            box = ctk.CTkFrame(frame, fg_color=CARD, corner_radius=14)
            box.pack(fill="x", pady=4)
            checked = item["id"] in approved if approved is not None else bool(item["default_on"])
            if item["id"] in held:
                checked = False
            var = tk.BooleanVar(value=checked)
            self.fix_vars[item["id"]] = var
            ctk.CTkCheckBox(
                box, text=item["title"], variable=var, text_color=TEXT, fg_color=GOLD, hover_color="#e2c79a", checkmark_color=GOLD_TEXT
            ).pack(anchor="w", padx=14, pady=(12, 0))
            ctk.CTkLabel(box, text=item["detail"], text_color=MUTED, wraplength=840, justify="left").pack(anchor="w", padx=38)
            ctk.CTkLabel(box, text="Melhora esperada: " + item["impact"], text_color=TEXT, wraplength=840, justify="left").pack(
                anchor="w", padx=38, pady=(4, 0)
            )
            extra = ""
            if item["id"] in held:
                extra = " " + held[item["id"]]
            reboot = " Pede reinício." if item["needs_reboot"] else ""
            ctk.CTkLabel(box, text="Risco: " + item["risk"] + reboot + extra, text_color=WARN, wraplength=840, justify="left").pack(
                anchor="w", padx=38, pady=(2, 12)
            )
        actions = ctk.CTkFrame(frame, fg_color=BG)
        actions.pack(fill="x", pady=12)
        self._gold_button(actions, "Criar ponto de restauração e aplicar o que está marcado", self.apply_clicked, width=420).pack(
            side="left", padx=(0, 8)
        )
        self._ghost(actions, "Desfazer último backup", self.revert_clicked).pack(side="left")
        self.fix_log = ctk.CTkTextbox(frame, height=160, fg_color=RAIL, text_color=TEXT)
        self.fix_log.pack(fill="x", pady=(4, 8))
        self.fix_log.insert("end", self.fix_lines)

    def apply_clicked(self) -> None:
        if not self.snapshot or self.applying:
            return
        chosen = [fix_id for fix_id, var in self.fix_vars.items() if var.get()]
        if not chosen:
            messagebox_info("Marque ao menos uma correção.")
            return
        agreed = messagebox_yesno(
            "Vou criar um ponto de restauração do Windows e, só se ele for criado, aplicar "
            f"{len(chosen)} correção(ões).\n\nSe o ponto falhar, nada muda.\n\nContinuar?"
        )
        if not agreed:
            return
        plan = build_plan(self.snapshot, chosen)
        folder = data_dir() / "plans"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        plan_path = folder / f"{stamp}.json"
        result_path = folder / f"{stamp}-result.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        self.applying = True
        self._set_status("Criando ponto de restauração. Isso pode levar um minuto.")
        self._append_log("Pedido enviado. O Windows vai pedir permissão de administrador se ainda não estiver elevada.\n")
        if is_admin():
            threading.Thread(target=lambda: apply_file(plan_path, result_path), daemon=True).start()
        else:
            ok, message = launch_elevated(f'--apply "{plan_path}" --result "{result_path}"')
            if not ok:
                self.applying = False
                self._append_log(message + "\n")
                self._set_status(message)
                return
        self._awaiting_apply = {"before": self.snapshot, "ids": list(chosen), "steps": [], "reboot": False}
        self._poll_deadline = time.time() + 240
        self.after(600, lambda: self._poll_result(result_path, rescan=True))

    def revert_clicked(self, rescan: bool = True, sink: str = "fixes") -> None:
        if self.applying:
            return
        agreed = messagebox_yesno(
            "Vou criar outro ponto de restauração e desfazer o último backup de registro e de arquivos do ORION."
        )
        if not agreed:
            return
        folder = data_dir() / "plans"
        folder.mkdir(parents=True, exist_ok=True)
        result_path = folder / f"revert-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        self.applying = True
        self._set_status("Desfazendo com um ponto de restauração antes.")
        if is_admin():

            def work() -> None:
                result_path.write_text(json.dumps(revert_last(), ensure_ascii=False, indent=2), encoding="utf-8")

            threading.Thread(target=work, daemon=True).start()
        else:
            ok, message = launch_elevated(f'--revert "{result_path}"')
            if not ok:
                self.applying = False
                self._set_status(message)
                return
        self._poll_deadline = time.time() + (900 if sink == "debloat" else 240)
        self.after(600, lambda path=result_path, again=rescan, target=sink: self._poll_result(path, again, target))

    def _poll_result(self, path: Path, rescan: bool, sink: str = "fixes") -> None:
        if path.exists():
            self.applying = False
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                self._awaiting_apply = None
                self._set_status(f"Resultado ilegível: {error}")
                return
            lines = []
            for step in payload.get("steps") or []:
                mark = "ok" if step.get("ok") else "falhou"
                lines.append(f"[{mark}] {step.get('id')}: {step.get('message')}")
            if payload.get("note"):
                lines.append(payload["note"])
            if payload.get("reboot"):
                lines.append("Uma das mudanças só vale depois de reiniciar o Windows. O ORION não reinicia sozinho.")
            text = "\n".join(lines) or "Sem detalhes."
            if sink == "debloat":
                self._append_debloat(text + "\n")
                if payload.get("aborted"):
                    self._set_status("O ponto de restauração não foi criado. Nada foi alterado.")
                elif payload.get("ok"):
                    self._set_status("Debloat terminado.")
                else:
                    self._set_status("O Debloat parou ou teve falha. Veja o registro.")
            else:
                self._append_log(text + "\n")
                self._set_status("Correção terminada." if payload.get("ok") else "A correção parou ou teve falha. Veja o registro.")
            if rescan and payload.get("ok") and not payload.get("aborted"):
                if self._awaiting_apply is not None:
                    self._awaiting_apply["steps"] = payload.get("steps") or []
                    self._awaiting_apply["reboot"] = bool(payload.get("reboot"))
                self.after(600, self.start_scan)
                return
            self._awaiting_apply = None
            return
        if time.time() > getattr(self, "_poll_deadline", 0):
            self.applying = False
            self._awaiting_apply = None
            self._set_status("Sem resposta do processo elevado. Se a permissão foi cancelada, nada foi alterado.")
            return
        self.after(600, lambda path=path, again=rescan, target=sink: self._poll_result(path, again, target))

    def _append_debloat(self, text: str) -> None:
        self.debloat_lines += text
        box = getattr(self, "debloat_log", None)
        if box is not None:
            try:
                if box.winfo_exists():
                    box.insert("end", text)
                    box.see("end")
            except tk.TclError:
                pass

    def _append_log(self, text: str) -> None:
        self.fix_lines += text
        box = getattr(self, "fix_log", None)
        if box is not None:
            try:
                if box.winfo_exists():
                    box.insert("end", text)
                    box.see("end")
            except tk.TclError:
                pass

    def _page_debloat(self) -> None:
        frame = ctk.CTkScrollableFrame(self.content, fg_color=BG)
        frame.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(frame, text="Debloat", font=ctk.CTkFont(size=28, weight="bold"), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(
            frame,
            text=(
                "Tira anúncio, aplicativo e serviço que o Windows não precisa para iniciar, "
                "jogar e atualizar. Defender, Windows Update, rede, áudio, Edge e a área de trabalho ficam. "
                "A lista é fechada: um item não pode pedir um nome fora dela. "
                "Nada é removido ao abrir esta aba. O que estiver marcado só sai depois de um ponto de restauração. "
                "Se o ponto falhar, nada muda."
            ),
            text_color=MUTED,
            wraplength=880,
            justify="left",
        ).pack(anchor="w", pady=(4, 8))
        if self.debloat_state is None:
            ctk.CTkLabel(
                frame,
                text="Lendo aplicativos e serviços. Nada está sendo removido.",
                text_color=GOLD,
            ).pack(anchor="w", pady=(8, 4))
            if not self.debloat_loading:
                self.debloat_loading = True
                token = self.debloat_token
                threading.Thread(target=lambda mark=token: self._load_debloat(mark), daemon=True).start()
            return
        if self.debloat_error:
            ctk.CTkLabel(frame, text=self.debloat_error, text_color=BAD, wraplength=880, justify="left").pack(anchor="w", pady=(0, 8))
        self.debloat_vars = {}
        group = ""
        for item in DEBLOAT_CATALOG:
            if item["group"] != group:
                group = item["group"]
                ctk.CTkLabel(frame, text=group, text_color=GOLD, font=ctk.CTkFont(size=16, weight="bold")).pack(
                    anchor="w", pady=(14, 4)
                )
            if self.debloat_error:
                checked = bool(item["default_on"])
                status_line = "A leitura falhou. Se deixar marcado, o item é conferido de novo na hora de aplicar."
            else:
                needed, status_line = debloat_pending(item["id"], self.debloat_state)
                checked = bool(item["default_on"] and needed)
            box = ctk.CTkFrame(frame, fg_color=CARD, corner_radius=14)
            box.pack(fill="x", pady=4)
            var = tk.BooleanVar(value=checked)
            self.debloat_vars[item["id"]] = var
            ctk.CTkCheckBox(
                box,
                text=item["title"],
                variable=var,
                text_color=TEXT,
                fg_color=GOLD,
                hover_color="#e2c79a",
                checkmark_color=GOLD_TEXT,
            ).pack(anchor="w", padx=14, pady=(12, 0))
            ctk.CTkLabel(box, text=item["detail"], text_color=MUTED, wraplength=840, justify="left").pack(anchor="w", padx=38)
            ctk.CTkLabel(box, text=status_line, text_color=TEXT, wraplength=840, justify="left").pack(anchor="w", padx=38, pady=(4, 0))
            ctk.CTkLabel(box, text="Efeito: " + item["impact"], text_color=TEXT, wraplength=840, justify="left").pack(
                anchor="w", padx=38, pady=(2, 0)
            )
            reboot = " Pede reinício." if item["needs_reboot"] else ""
            ctk.CTkLabel(box, text="Risco: " + item["risk"] + reboot, text_color=WARN, wraplength=840, justify="left").pack(
                anchor="w", padx=38, pady=(2, 12)
            )
        actions = ctk.CTkFrame(frame, fg_color=BG)
        actions.pack(fill="x", pady=12)
        self._gold_button(actions, "Criar ponto de restauração e aplicar o que está marcado", self._debloat_apply, width=460).pack(
            side="left", padx=(0, 8)
        )
        self._ghost(actions, "Desfazer último backup", lambda: self.revert_clicked(rescan=False, sink="debloat")).pack(
            side="left", padx=(0, 8)
        )
        self._ghost(actions, "Ler de novo", self._reload_debloat).pack(side="left")
        self.debloat_log = ctk.CTkTextbox(frame, height=160, fg_color=RAIL, text_color=TEXT)
        self.debloat_log.pack(fill="x", pady=(4, 8))
        self.debloat_log.insert("end", self.debloat_lines)

    def _load_debloat(self, token: int) -> None:
        try:
            state = inspect_debloat()
            error = ""
        except Exception as error_value:
            state = {}
            error = f"Não deu para ler o inventário. {error_value}"
        self.after(0, lambda item=state, message=error, mark=token: self._debloat_ready(item, message, mark))

    def _debloat_ready(self, state: dict, error: str, token: int) -> None:
        self.debloat_loading = False
        if token != self.debloat_token:
            return
        self.debloat_state = state
        self.debloat_error = error
        if self.page == "debloat":
            self.show_page("debloat")

    def _reload_debloat(self) -> None:
        if self.applying:
            return
        self.debloat_token += 1
        self.debloat_state = None
        self.debloat_error = ""
        self.debloat_loading = False
        self.show_page("debloat")

    def _debloat_apply(self) -> None:
        if self.applying:
            return
        chosen = [item_id for item_id, var in self.debloat_vars.items() if var.get()]
        if not chosen:
            messagebox_info("Marque ao menos um item.")
            return
        titles = [item["title"] for item in DEBLOAT_CATALOG if item["id"] in set(chosen)]
        listed = "\n".join(f"• {title}" for title in titles)
        agreed = messagebox_yesno(
            "Vou criar um ponto de restauração do Windows e, só se ele for criado, aplicar "
            f"{len(chosen)} item(ns):\n\n{listed}\n\n"
            "Defender e Windows Update não entram nessa lista. "
            "Se o ponto falhar, nada muda.\n\nContinuar?"
        )
        if not agreed:
            return
        plan = build_debloat_plan(chosen)
        folder = data_dir() / "plans"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        plan_path = folder / f"debloat-{stamp}.json"
        result_path = folder / f"debloat-{stamp}-result.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        self.applying = True
        self._set_status("Criando ponto de restauração antes do Debloat. Pode levar vários minutos.")
        self._append_debloat("Pedido enviado. O Windows vai pedir permissão de administrador se ainda não estiver elevada.\n")
        if is_admin():
            threading.Thread(target=lambda: apply_file(plan_path, result_path), daemon=True).start()
        else:
            ok, message = launch_elevated(f'--apply "{plan_path}" --result "{result_path}"')
            if not ok:
                self.applying = False
                self._append_debloat(message + "\n")
                self._set_status(message)
                return
        self._poll_deadline = time.time() + 1200
        self.after(600, lambda path=result_path: self._poll_result(path, False, "debloat"))

    def _page_settings(self) -> None:
        frame = ctk.CTkScrollableFrame(self.content, fg_color=BG)
        frame.grid(row=0, column=0, sticky="nsew")
        settings = load_settings()
        ctk.CTkLabel(frame, text="Configurações", font=ctk.CTkFont(size=28, weight="bold"), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(frame, text=f"ORION {__version__}", text_color=GOLD).pack(anchor="w", pady=(2, 8))
        ctk.CTkLabel(
            frame,
            text=(
                "Ao abrir, o ORION compara esta instalação com a versão publicada e mantém "
                "a pasta de dados deste computador. A troca automática vem ligada e pode ser desligada aqui."
            ),
            text_color=MUTED,
            wraplength=880,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))
        self.auto_update = tk.BooleanVar(value=bool(settings["auto_update"]))
        ctk.CTkSwitch(
            frame,
            text="Atualizar ao abrir",
            variable=self.auto_update,
            progress_color=GOLD,
            button_color=GOLD,
            text_color=TEXT,
        ).pack(anchor="w", pady=(10, 4))
        ctk.CTkLabel(
            frame,
            text="O perfil escolhido vale na próxima verificação. Automático lê o processador e a placa.",
            text_color=MUTED,
            wraplength=880,
            justify="left",
        ).pack(anchor="w", pady=(12, 4))
        current = next((label for label, value in PROFILE_MENU if value == settings["profile_override"]), "Automático")
        self.profile_choice = tk.StringVar(value=current)
        ctk.CTkOptionMenu(
            frame,
            values=[label for label, _value in PROFILE_MENU],
            variable=self.profile_choice,
            fg_color=CARD,
            button_color=GOLD,
            button_hover_color="#e2c79a",
            text_color=TEXT,
            dropdown_fg_color=CARD,
            dropdown_text_color=TEXT,
        ).pack(anchor="w", pady=4)
        row = ctk.CTkFrame(frame, fg_color=BG)
        row.pack(fill="x", pady=16)
        self._gold_button(row, "Salvar", self._save_settings_form, width=120).pack(side="left", padx=(0, 8))
        self._ghost(row, "Buscar atualização", self._check_update_clicked).pack(side="left")

    def _save_settings_form(self) -> None:
        label = self.profile_choice.get()
        override = next((value for name, value in PROFILE_MENU if name == label), "")
        save_settings(
            {
                "auto_update": bool(self.auto_update.get()),
                "profile_override": override,
            }
        )
        self._set_status("Configurações salvas neste computador.")

    def _check_update_clicked(self) -> None:
        self._save_settings_form()
        self._set_status("Consultando a versão publicada.")
        threading.Thread(target=self._check_update_worker, daemon=True).start()

    def _check_update_worker(self) -> None:
        remote = look_up()
        self.after(0, lambda item=remote: self._offer_update(item))

    def _offer_update(self, remote) -> None:
        if not remote.ok:
            self._set_status(remote.message)
            messagebox_info(remote.message)
            return
        if remote.kind in {"same", "none"}:
            self._set_status(remote.message)
            messagebox_info(remote.message)
            return
        dirty = worktree_dirty()
        if remote.kind == "first":
            question = (
                "Esta é a primeira leitura da versão publicada. "
                "Substituir os arquivos do programa por esta versão? A pasta de dados deste computador é preservada."
            )
        else:
            question = "Há uma versão nova. Substituir os arquivos do programa e preservar a pasta de dados deste computador?"
        if dirty:
            question += "\n\nA pasta tem alterações locais do Git."
        if not messagebox_yesno(question):
            if remote.kind == "first":
                remember_sha(remote.sha)
                self._set_status("Referência anotada. Nenhum arquivo foi substituído.")
            else:
                self._set_status("Atualização não instalada.")
            return
        self._set_status("Baixando a atualização.")
        threading.Thread(target=lambda: self._install_worker(remote.sha), daemon=True).start()

    def _install_worker(self, sha: str) -> None:
        report = install(sha)
        self.after(0, lambda item=report: self._update_finished(item))

    def _update_finished(self, report) -> None:
        self._set_status(report.message)
        if report.needs_exit and report.ok:
            self.after(400, self.destroy)
            return
        messagebox_info(report.message)

    def _page_history(self) -> None:
        frame = ctk.CTkScrollableFrame(self.content, fg_color=BG)
        frame.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(frame, text="Histórico", font=ctk.CTkFont(size=28, weight="bold"), text_color=TEXT).pack(anchor="w", pady=(0, 8))
        rows = list_history()
        if not rows:
            ctk.CTkLabel(frame, text="Ainda não há verificação salva.", text_color=MUTED).pack(anchor="w")
            return
        for row in rows:
            card = ctk.CTkFrame(frame, fg_color=CARD, corner_radius=12)
            card.pack(fill="x", pady=4)
            profile = PROFILE_LABEL.get(row.get("profile") or "", "")
            suffix = f"   ·   {profile}" if profile else ""
            ctk.CTkLabel(
                card,
                text=f"{row.get('scanned_at', '')}   ·   nota {row.get('score', '?')}/100{suffix}",
                text_color=TEXT,
                font=ctk.CTkFont(size=15, weight="bold"),
            ).pack(anchor="w", padx=14, pady=(10, 0))
            ctk.CTkLabel(card, text=row.get("headline", ""), text_color=MUTED, wraplength=860, justify="left").pack(anchor="w", padx=14)
            games = ", ".join(row.get("games") or [])
            ctk.CTkLabel(card, text=games, text_color=TEXT, wraplength=860, justify="left").pack(anchor="w", padx=14, pady=(0, 10))

    def _gold_button(self, parent, text: str, command, width: int = 160) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            width=width,
            height=36,
            fg_color=GOLD,
            hover_color="#e2c79a",
            text_color=GOLD_TEXT,
            command=command,
        )

    def _ghost(self, parent, text: str, command, enabled: bool = True) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            height=32,
            fg_color=GHOST,
            hover_color="#3a3226",
            text_color=GOLD if enabled else MUTED,
            state="normal" if enabled else "disabled",
            command=command,
        )


def messagebox_error(message: str) -> None:
    from tkinter import messagebox

    messagebox.showerror("ORION", message)


def messagebox_info(message: str) -> None:
    from tkinter import messagebox

    messagebox.showinfo("ORION", message)


def messagebox_yesno(message: str) -> bool:
    from tkinter import messagebox

    return bool(messagebox.askyesno("ORION", message))


def run() -> None:
    app = OrionApp()
    app.mainloop()
