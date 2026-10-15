"""Confere a leitura e as correções. A regra do programa vale mesmo sem arquivo extra."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

from orion.ai.analyst import analyze
from orion.fixer.actions import CATALOG
from orion.models import Snapshot
from orion.scanner.profiles import gpu_tier, weak_cpu
from orion.store import load_settings

log = logging.getLogger("orion")

LATENCY = (
    "rl_competitive",
    "disable_game_dvr",
    "mouse_accel_off",
    "power_high",
    "game_mode_on",
    "hags_off",
    "discord_overlay_off",
    "gpu_preference",
)
OPTIONAL = ("disable_fso", "clean_temp", "close_heavy", "disable_heavy_startup")
OPTIONAL_REASONS = {
    "disable_fso": "Fica desmarcado. Em janela sem borda o ganho é incerto e o alt-tab pode piorar.",
    "clean_temp": "A limpeza recupera pouco espaço e não entra marcada.",
    "close_heavy": "Fechar programas fica para você decidir. A verificação não marca isso sozinha.",
    "disable_heavy_startup": "Tirar programa da inicialização muda o dia a dia. Fica desmarcado.",
}
ISSUE_OF = {
    "rl_competitive": ("rl_preset",),
    "cs2_competitive": ("cs2_preset", "cs2_vsync"),
    "disable_game_dvr": ("game_dvr",),
    "mouse_accel_off": ("mouse_accel",),
    "power_high": ("power_plan",),
    "game_mode_on": ("game_mode_off",),
    "hags_off": ("hags_on",),
    "discord_overlay_off": ("discord_overlay",),
}
TITLES = {item["id"]: item["title"] for item in CATALOG}
PROFILE_LABEL = {"fraco": "PC fraco", "equilibrado": "equilibrado", "forte": "PC forte"}
_BANNED = (
    "inteligência artificial",
    "inteligencia artificial",
    "language model",
    "sou uma ia",
    "sou um modelo",
    "como ia",
    "chatgpt",
    "grok",
    "qwen",
    "gemini",
)


@dataclass
class Verdict:
    profile: str
    summary: str
    approved: list[str] = field(default_factory=list)
    held: dict[str, str] = field(default_factory=dict)


def classify_profile(cpu_name: str, max_mhz: float, gpu_name: str, override: str = "") -> str:
    if override in {"fraco", "equilibrado", "forte"}:
        return override
    cpu_weak = weak_cpu(cpu_name or "", max_mhz or 0)
    tier = gpu_tier(gpu_name) if gpu_name else "desconhecida"
    if cpu_weak or tier in {"fraca", "entrada"}:
        return "fraco"
    if tier == "forte" and not cpu_weak:
        return "forte"
    return "equilibrado"


def cs2_is_high(snapshot: Snapshot) -> bool:
    values = ((snapshot.configs or {}).get("cs2") or {}).get("values") or {}

    def number(key: str) -> float:
        try:
            return float(values.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0

    return (
        number("setting.gpu_level") >= 2
        or number("setting.msaa_samples") >= 4
        or number("setting.videocfg_shadow_quality") >= 2
    )


def decide(profile: str, tier: str, available: set[str], cs2_high: bool) -> tuple[list[str], dict[str, str]]:
    approved: list[str] = []
    held: dict[str, str] = {}
    for fix_id in LATENCY:
        if fix_id in available:
            approved.append(fix_id)
    if "cs2_competitive" in available:
        if profile == "forte":
            held["cs2_competitive"] = "A placa aguenta preset mais alto. O competitivo baixo não entra marcado."
        elif profile == "fraco" or tier in {"entrada", "fraca"} or cs2_high:
            approved.append("cs2_competitive")
        else:
            held["cs2_competitive"] = "O meio-termo não força o preset baixo enquanto a placa segura."
    for fix_id in OPTIONAL:
        if fix_id in available:
            held[fix_id] = OPTIONAL_REASONS[fix_id]
    approved = [fix_id for fix_id in approved if fix_id not in held]
    return approved, held


def _summary(profile: str, cpu_name: str, gpu_name: str) -> str:
    label = PROFILE_LABEL.get(profile, profile)
    cpu = (cpu_name or "processador não identificado").strip()
    gpu = gpu_name or "placa não identificada"
    if profile == "fraco":
        tail = "A prioridade é resposta, estabilidade e preset mais leve. O teto do hardware continua o mesmo."
    elif profile == "forte":
        tail = "A prioridade é latência. O preset baixo do CS2 fica de fora para não achatar uma placa que segura gráfico."
    else:
        tail = "A prioridade é latência, e o preset do CS2 só entra se a placa ou as opções atuais pedirem."
    return f"Perfil {label}. {cpu} com {gpu}. {tail}"


def policy(snapshot: Snapshot, available_ids: list[str]) -> Verdict:
    settings = load_settings()
    gpu_name = snapshot.gpus[0].name if snapshot.gpus else ""
    profile = classify_profile(
        snapshot.cpu_name,
        snapshot.cpu_max_mhz,
        gpu_name,
        settings.get("profile_override") or "",
    )
    tier = gpu_tier(gpu_name) if gpu_name else "desconhecida"
    approved, held = decide(profile, tier, set(available_ids), cs2_is_high(snapshot))
    return Verdict(profile, _summary(profile, snapshot.cpu_name, gpu_name), approved, held)


def _bad_summary(text: str) -> bool:
    if not text or len(text) > 400:
        return True
    folded = text.lower()
    return any(token in folded for token in _BANNED)


def interpret_model_text(raw: str, allowed: set[str]) -> dict | None:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    profile = str(data.get("profile") or "")
    if profile not in {"fraco", "equilibrado", "forte"}:
        profile = ""
    raw_approve = data.get("approve")
    if isinstance(raw_approve, str):
        raw_approve = [part.strip() for part in raw_approve.replace(";", ",").split(",") if part.strip()]
    approve = []
    for item in raw_approve or []:
        fix_id = str(item)
        if fix_id in allowed and fix_id not in approve:
            approve.append(fix_id)
    hold: dict[str, str] = {}
    raw_hold = data.get("hold") or {}
    if isinstance(raw_hold, dict):
        for key, value in raw_hold.items():
            fix_id = str(key)
            if fix_id in allowed and fix_id not in approve:
                reason = str(value or "").strip()
                if reason and not _bad_summary(reason) and len(reason) <= 180:
                    hold[fix_id] = reason
    summary = str(data.get("summary") or "").strip()
    if _bad_summary(summary) or len(summary) < 40:
        summary = ""
    if not approve and not hold and not summary:
        return None
    return {"profile": profile, "approve": approve, "hold": hold, "summary": summary}


def _merge(base: Verdict, parsed: dict, available: set[str]) -> Verdict:
    """O texto externo explica a leitura. Ele não liga limpeza, fechar programa nem a inicialização."""
    approved = list(base.approved)
    held = dict(base.held)
    if "cs2_competitive" in available:
        if "cs2_competitive" in parsed["hold"]:
            approved = [item for item in approved if item != "cs2_competitive"]
            held["cs2_competitive"] = parsed["hold"]["cs2_competitive"]
        elif "cs2_competitive" in parsed["approve"] and "cs2_competitive" not in approved:
            approved.append("cs2_competitive")
            held.pop("cs2_competitive", None)
    for fix_id, reason in parsed["hold"].items():
        if fix_id in OPTIONAL and fix_id in available and reason:
            held[fix_id] = reason
    summary = parsed["summary"] or base.summary
    return Verdict(base.profile, summary, approved, held)


def review(snapshot: Snapshot, available_ids: list[str] | None = None) -> Verdict:
    if available_ids is None:
        from orion.fixer.actions import available_fixes

        available_ids = [item["id"] for item in available_fixes(snapshot)]
    base = policy(snapshot, available_ids)
    raw = ""
    try:
        from orion.ai.remote_check import complete as remote_complete

        raw = remote_complete(_prompt(snapshot, available_ids), timeout=25)
    except Exception:
        log.exception("verificacao remota")
    if not raw:
        try:
            from orion.ai.local_model import complete, ready

            if ready() and os.environ.get("ORION_SKIP_MODEL") != "1":
                raw = complete(_prompt(snapshot, available_ids), timeout=45)
        except Exception:
            log.exception("verificacao interna")
    parsed = interpret_model_text(raw or "", set(available_ids))
    if not parsed:
        log.info("complemento interno ignorado")
        return base
    return _merge(base, parsed, set(available_ids))


def _prompt(snapshot: Snapshot, available_ids: list[str]) -> str:
    gpu_name = snapshot.gpus[0].name if snapshot.gpus else ""
    issues = [
        {"id": issue.id, "severity": issue.severity, "fix": issue.fix_id}
        for issue in snapshot.issues
        if issue.severity in {"critico", "alto", "medio"}
    ][:12]
    payload = {
        "cpu": snapshot.cpu_name.strip(),
        "mhz": round(snapshot.cpu_max_mhz or 0),
        "gpu": gpu_name,
        "fixes": available_ids,
        "issues": issues,
    }
    return (
        "Responda só JSON com profile (fraco, equilibrado ou forte), "
        "approve (lista de ids), hold (objeto id para motivo curto) e summary "
        "(uma frase em português, sem falar de si). "
        "Não invente id.\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def verify_corrections(
    before: Snapshot,
    after: Snapshot,
    applied_ids: list[str],
    steps: list[dict],
    reboot: bool = False,
) -> list[str]:
    before_ids = {issue.id for issue in before.issues}
    after_ids = {issue.id for issue in after.issues}
    by_step = {str(step.get("id")): step for step in steps or []}
    lines: list[str] = []
    for fix_id in applied_ids:
        title = TITLES.get(fix_id, fix_id)
        step = by_step.get(fix_id)
        if step is not None and not step.get("ok"):
            lines.append(f"{title}: a etapa falhou. {step.get('message') or ''}".strip())
            continue
        related = ISSUE_OF.get(fix_id)
        if not related:
            lines.append(f"{title}: registrada. A leitura seguinte não tem um item único para conferir.")
            continue
        still = [item for item in related if item in after_ids]
        was = [item for item in related if item in before_ids]
        if still:
            lines.append(f"{title}: o item continua na leitura.")
        elif was or step is not None:
            lines.append(f"{title}: conferida. O item saiu da leitura.")
        else:
            lines.append(f"{title}: registrada.")
    before_score = analyze(before).score
    after_score = analyze(after).score
    lines.append(f"A nota foi de {before_score} para {after_score}.")
    if reboot or any(step.get("ok") and step.get("id") == "hags_off" for step in steps or []):
        lines.append("Parte da mudança espera o reinício do Windows.")
    return lines
