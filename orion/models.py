"""Dados que a varredura, a tela e a análise compartilham."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class DiskInfo:
    letter: str
    media: str
    name: str
    bus: str
    health: str
    total_gb: float
    free_gb: float

    @property
    def free_percent(self) -> float:
        if self.total_gb <= 0:
            return 0.0
        return self.free_gb / self.total_gb * 100.0


@dataclass
class DisplayInfo:
    name: str
    width: int
    height: int
    hz: int
    primary: bool


@dataclass
class GpuInfo:
    name: str
    driver_version: str
    driver_date: str
    vram_gb: float | None
    vendor: str


@dataclass
class ProcessInfo:
    name: str
    pid: int
    rss_mb: float
    cpu: float
    note: str = ""


@dataclass
class StartupItem:
    name: str
    command: str
    location: str
    heavy: bool


@dataclass
class GameEntry:
    name: str
    platform: str
    app_id: str
    install_dir: str
    executable: str
    size_bytes: int | None
    drive_letter: str
    drive_media: str
    drive_name: str
    profile: str


@dataclass
class Issue:
    id: str
    title: str
    severity: str
    category: str
    cause: str
    evidence: str
    impact: str
    fix_id: str | None = None
    games: list[str] = field(default_factory=list)


@dataclass
class Snapshot:
    scanned_at: str
    hostname: str
    os_name: str
    os_version: str
    uptime_hours: float
    cpu_name: str
    cpu_cores: int
    cpu_threads: int
    cpu_max_mhz: float
    cpu_current_mhz: float
    cpu_percent: float
    cpu_busiest_core: float
    ram_total_gb: float
    ram_used_gb: float
    ram_available_gb: float
    ram_speed_mhz: int | None
    ram_sticks: int
    gpus: list[GpuInfo]
    displays: list[DisplayInfo]
    disks: list[DiskInfo]
    board: str
    power_plan: str
    power_guid: str
    game_mode: bool | None
    game_dvr: bool | None
    game_bar: bool | None
    hags_mode: int | None
    mouse_accel: bool | None
    adapters: list[dict[str, str]]
    pagefiles: list[dict[str, Any]]
    processes: list[ProcessInfo]
    startups: list[StartupItem]
    games: list[GameEntry]
    configs: dict[str, Any]
    network: list[dict[str, Any]]
    pending_reboot: bool
    issues: list[Issue] = field(default_factory=list)
    healthy: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Analysis:
    score: int
    headline: str
    bottleneck: str
    paragraphs: list[str]
    per_game: list[tuple[str, str]]
    order: list[str]
    limits: str

    def as_text(self) -> str:
        lines = [
            f"Nota de prontidão para jogar: {self.score}/100",
            "",
            self.headline,
            "",
            "Gargalo principal",
            self.bottleneck,
            "",
        ]
        lines.extend(self.paragraphs)
        lines.append("")
        lines.append("Por jogo")
        for name, text in self.per_game:
            lines.append(f"- {name}: {text}")
        lines.append("")
        lines.append("Ordem que mais devolve fluidez")
        for index, step in enumerate(self.order, start=1):
            lines.append(f"{index}. {step}")
        lines.append("")
        lines.append("O que estas correções não mudam")
        lines.append(self.limits)
        return "\n".join(lines)
