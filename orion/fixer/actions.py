"""Correções com backup. Nenhuma delas roda sem um ponto de restauração criado antes."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import psutil

from orion.fixer.changelog import ChangeLog
from orion.models import Snapshot
from orion.scanner.configs import cs2_changes, rl_changes
from orion.scanner.processes import CLOSE_CANDIDATES
from orion.textcfg import read_text, set_ini_values, set_vdf_values
from orion.winutil import delete_value, read_value, run_hidden

HIGH_POWER = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"

REFUSE_KILL = {
    "csrss.exe",
    "lsass.exe",
    "wininit.exe",
    "services.exe",
    "smss.exe",
    "winlogon.exe",
    "explorer.exe",
    "dwm.exe",
    "system",
    "orion.exe",
    "cs2.exe",
    "rocketleague.exe",
}

STARTUP_LOCATIONS = {
    "HKCU Run": ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    "HKLM Run": ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    "HKLM Run 32": ("HKLM", r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"),
}

CATALOG = [
    {
        "id": "rl_competitive",
        "title": "Rocket League: tirar VSync, atraso de quadro e sombra pesada",
        "detail": "Grava uma cópia do TASystemSettings.ini e só então troca as chaves de latência e efeitos. A resolução só muda se estiver maior que a do monitor.",
        "impact": "Menos atraso no controle e FPS solto da taxa do monitor. Pode aparecer tearing.",
        "risk": "O arquivo de Documentos não entra no ponto de restauração do Windows. A cópia na pasta de backup do ORION é o que desfaz esta parte.",
        "default_on": True,
        "needs_reboot": False,
    },
    {
        "id": "cs2_competitive",
        "title": "CS2: preset competitivo sem trocar a sua resolução",
        "detail": "Baixa sombra, oclusão, MSAA e o nível de CPU do jogo. Mantém a resolução e o modo de tela que você já usa. Desliga VSync se estiver ligado.",
        "impact": "Menos carga no núcleo fraco e na RX 580. A imagem fica mais simples. A taxa tende a subir e a estabilizar.",
        "risk": "O cs2_video.txt também é copiado antes da escrita. Feche o CS2 antes de aplicar, senão o jogo regrava o arquivo por cima.",
        "default_on": True,
        "needs_reboot": False,
    },
    {
        "id": "disable_game_dvr",
        "title": "Desligar a gravação do Xbox Game DVR",
        "detail": "Desativa captura em segundo plano e o gancho do Game DVR na tela cheia.",
        "impact": "Menos uma camada usando GPU e menos latência. Não muda o gráfico do jogo.",
        "risk": "Win+G deixa de gravar clipes até você ligar de novo.",
        "default_on": True,
        "needs_reboot": False,
    },
    {
        "id": "mouse_accel_off",
        "title": "Desligar aceleração do mouse",
        "detail": "Zera MouseSpeed e os limiares, e aplica na sessão atual.",
        "impact": "A mira percorre sempre a mesma distância. Não mexe em FPS.",
        "risk": "O ponteiro do Windows inteiro fica sem aceleração, não só o jogo.",
        "default_on": True,
        "needs_reboot": False,
    },
    {
        "id": "power_high",
        "title": "Plano de energia em alto desempenho",
        "detail": "Ativa o plano Alto desempenho do Windows.",
        "impact": "O processador para de dormir entre um quadro e outro.",
        "risk": "O PC gasta um pouco mais de energia parado na área de trabalho.",
        "default_on": True,
        "needs_reboot": False,
    },
    {
        "id": "game_mode_on",
        "title": "Ligar o Modo de Jogo do Windows",
        "detail": "Ativa AutoGameModeEnabled para o seu usuário.",
        "impact": "O Windows prioriza o jogo diante de tarefas de fundo. Ganho pequeno, nas quedas.",
        "risk": "Baixo. Dá para desligar de novo pelo backup.",
        "default_on": True,
        "needs_reboot": False,
    },
    {
        "id": "hags_off",
        "title": "Desligar agendamento de GPU por hardware",
        "detail": "HwSchMode volta para 1. Em RX 580 isso evita um engasgo conhecido.",
        "impact": "Menos microtravada depois do reinício. Não sobe o teto da placa.",
        "risk": "Só passa a valer depois de reiniciar.",
        "default_on": True,
        "needs_reboot": True,
    },
    {
        "id": "discord_overlay_off",
        "title": "Desligar a sobreposição do Discord",
        "detail": "Marca enableOverlay como falso nas configurações do Discord. O voz continua.",
        "impact": "Menos microtravada dentro do jogo.",
        "risk": "Se o Discord estiver aberto, feche e abra de novo para ele aceitar a mudança.",
        "default_on": True,
        "needs_reboot": False,
    },
    {
        "id": "gpu_preference",
        "title": "Preferir a placa de alto desempenho nos jogos encontrados",
        "detail": "Grava GpuPreference=2 no DirectX para cada executável com caminho confirmado.",
        "impact": "Evita o Windows abrir o jogo em modo de economia. Num PC com uma placa só, o efeito é pequeno.",
        "risk": "Vale na próxima abertura do jogo.",
        "default_on": True,
        "needs_reboot": False,
    },
    {
        "id": "disable_fso",
        "title": "Desligar otimizações de tela cheia no CS2 e no Rocket League",
        "detail": "Adiciona DISABLEDXMAXIMIZEDWINDOWEDMODE só nesses executáveis.",
        "impact": "Pode reduzir atraso no modo exclusivo. Em janela sem borda a diferença é menor.",
        "risk": "Se a tela piscar ou o alt-tab piorar, desfaça pelo backup.",
        "default_on": False,
        "needs_reboot": False,
    },
    {
        "id": "clean_temp",
        "title": "Limpar arquivos temporários do usuário",
        "detail": "Apaga o conteúdo da pasta Temp do usuário. Arquivo em uso é ignorado.",
        "impact": "Recupera espaço. Só muda FPS se o SSD estava cheio.",
        "risk": "Não dá para desfazer a limpeza. O ponto de restauração não traz arquivo temporário de volta.",
        "default_on": False,
        "needs_reboot": False,
    },
    {
        "id": "close_heavy",
        "title": "Fechar programas pesados que não são o jogo",
        "detail": "Encerra navegador, gravador e overlay que estavam grandes na última verificação. Não fecha Steam, Epic, CS2 nem Rocket League.",
        "impact": "Libera o núcleo e a RAM na hora.",
        "risk": "Você perde o que estiver aberto nesses programas, como uma aba não salva.",
        "default_on": False,
        "needs_reboot": False,
    },
    {
        "id": "disable_heavy_startup",
        "title": "Tirar programas pesados da inicialização do Windows",
        "detail": "Remove do Run os itens classificados como pesados e guarda o comando no backup.",
        "impact": "Eles deixam de voltar sozinhos a cada boot.",
        "risk": "Um programa que você queira todo dia passa a precisar de abertura manual.",
        "default_on": False,
        "needs_reboot": False,
    },
]


def available_fixes(snapshot: Snapshot) -> list[dict]:
    wanted = {issue.fix_id for issue in snapshot.issues if issue.fix_id}
    return [dict(item) for item in CATALOG if item["id"] in wanted]


def build_plan(snapshot: Snapshot, fix_ids: list[str]) -> dict:
    allowed = {item["id"] for item in available_fixes(snapshot)}
    chosen = [fix_id for fix_id in fix_ids if fix_id in allowed]
    gpu_exes = []
    fso_exes = []
    for game in snapshot.games:
        if not game.executable:
            continue
        if game.profile in {"cs2", "rocket_league", "heavy", "medium"}:
            gpu_exes.append(game.executable)
        if game.profile in {"cs2", "rocket_league"}:
            fso_exes.append(game.executable)
    startups = []
    for item in snapshot.startups:
        if not item.heavy or item.location not in STARTUP_LOCATIONS:
            continue
        root, path = STARTUP_LOCATIONS[item.location]
        startups.append({"root": root, "path": path, "name": item.name})
    display = None
    for item in snapshot.displays:
        if item.primary or display is None:
            display = [item.width, item.height]
            if item.primary:
                break
    cs2 = snapshot.configs.get("cs2") or {}
    rl = snapshot.configs.get("rocket_league") or {}
    close_names = sorted(
        {
            proc.name.lower()
            for proc in snapshot.processes
            if proc.name.lower() in CLOSE_CANDIDATES and proc.rss_mb >= 250
        }
    )
    from orion.scanner.configs import discord_overlay_enabled

    _, discord_path = discord_overlay_enabled()
    return {
        "fix_ids": chosen,
        "temp": str(Path.home() / "AppData" / "Local" / "Temp"),
        "close_names": close_names,
        "gpu_exes": gpu_exes,
        "fso_exes": fso_exes,
        "cs2_video": cs2.get("video_path") or "",
        "rl_ini": rl.get("ini_path") or "",
        "display": display,
        "startups": startups,
        "discord_settings": discord_path,
    }


def _running(names: set[str]) -> list[str]:
    found = []
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info.get("name") or "").lower()
        except (psutil.Error, OSError):
            continue
        if name in names:
            found.append(name)
    return found


def _safe_exe(path: str) -> Path | None:
    candidate = Path(path)
    try:
        if candidate.is_file() and candidate.suffix.lower() == ".exe":
            return candidate
    except OSError:
        return None
    return None


def _layers_value(current: str | None) -> str:
    text = current or "~"
    if "DISABLEDXMAXIMIZEDWINDOWEDMODE" in text.upper():
        return text
    return (text + " DISABLEDXMAXIMIZEDWINDOWEDMODE").strip()


def _gpu_value(current: str | None) -> str:
    text = current or ""
    if "gpupreference=" in text.lower():
        import re

        return re.sub(r"GpuPreference=\d+;?", "GpuPreference=2;", text, flags=re.IGNORECASE)
    if text and not text.endswith(";"):
        text += ";"
    return text + "GpuPreference=2;"


def apply_fix(fix_id: str, plan: dict, changelog: ChangeLog) -> tuple[str, bool]:
    handler = HANDLERS[fix_id]
    return handler(plan, changelog)


def _power_high(plan: dict, changelog: ChangeLog) -> tuple[str, bool]:
    completed = run_hidden(["powercfg", "/setactive", HIGH_POWER], timeout=20)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "powercfg recusou o plano.")
    return "Plano Alto desempenho ativado.", False


def _game_mode(plan: dict, changelog: ChangeLog) -> tuple[str, bool]:
    path = r"Software\Microsoft\GameBar"
    changelog.set_value("HKCU", path, "AutoGameModeEnabled", "dword", 1)
    changelog.set_value("HKCU", path, "AllowAutoGameMode", "dword", 1)
    return "Modo de Jogo ligado para este usuário.", False


def _game_dvr(plan: dict, changelog: ChangeLog) -> tuple[str, bool]:
    user = r"Software\Microsoft\Windows\CurrentVersion\GameDVR"
    store = r"System\GameConfigStore"
    changelog.set_value("HKCU", user, "AppCaptureEnabled", "dword", 0)
    changelog.set_value("HKCU", user, "HistoricalCaptureEnabled", "dword", 0)
    changelog.set_value("HKCU", store, "GameDVR_Enabled", "dword", 0)
    changelog.set_value("HKCU", store, "GameDVR_FSEBehaviorMode", "dword", 2)
    changelog.set_value("HKCU", store, "GameDVR_HonorUserFSEBehaviorMode", "dword", 0)
    changelog.set_value("HKCU", store, "GameDVR_DXGIHonorFSEWindowsCompatible", "dword", 1)
    changelog.set_value("HKCU", store, "GameDVR_EFSEFeatureFlags", "dword", 0)
    changelog.set_value("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\GameDVR", "AllowGameDVR", "dword", 0)
    return "Gravação em segundo plano do Game DVR desligada.", False


def _mouse(plan: dict, changelog: ChangeLog) -> tuple[str, bool]:
    import ctypes

    path = r"Control Panel\Mouse"
    for name in ("MouseSpeed", "MouseThreshold1", "MouseThreshold2"):
        changelog.set_value("HKCU", path, name, "sz", "0")
    values = (ctypes.c_int * 3)(0, 0, 0)
    user32 = ctypes.windll.user32
    user32.SystemParametersInfoW.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
    user32.SystemParametersInfoW.restype = ctypes.c_bool
    if not user32.SystemParametersInfoW(0x0004, 0, values, 0x03):
        return "Aceleração gravada no registro. Saia e entre de novo se o ponteiro ainda acelerar.", False
    return "Aceleração do mouse desligada.", False


def _hags(plan: dict, changelog: ChangeLog) -> tuple[str, bool]:
    changelog.set_value("HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", "dword", 1)
    return "Agendamento de GPU desligado. Reinicie para valer.", True


def _discord(plan: dict, changelog: ChangeLog) -> tuple[str, bool]:
    raw = plan.get("discord_settings") or ""
    path = Path(raw) if raw else None
    if path is None or not path.is_file():
        return "Configuração do Discord não encontrada. Nada alterado neste item.", False
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise RuntimeError("settings.json do Discord não é um objeto.")
    data["enableOverlay"] = False
    changelog.replace_file(path, json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    running = " Feche e abra o Discord para ele ler o arquivo." if _running({"discord.exe"}) else ""
    return "Sobreposição do Discord desligada." + running, False


def _gpu_preference(plan: dict, changelog: ChangeLog) -> tuple[str, bool]:
    path = r"Software\Microsoft\DirectX\UserGpuPreferences"
    changed = 0
    for raw in plan.get("gpu_exes") or []:
        exe = _safe_exe(raw)
        if exe is None:
            continue
        existed, _, current = read_value("HKCU", path, str(exe))
        new_value = _gpu_value(str(current) if existed and current is not None else "")
        changelog.set_value("HKCU", path, str(exe), "sz", new_value)
        changed += 1
    if not changed:
        return "Nenhum executável confirmado para fixar a placa.", False
    return f"Alto desempenho gravado para {changed} jogo(s). Vale na próxima abertura.", False


def _fso(plan: dict, changelog: ChangeLog) -> tuple[str, bool]:
    path = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
    changed = 0
    for raw in plan.get("fso_exes") or []:
        exe = _safe_exe(raw)
        if exe is None:
            continue
        existed, _, current = read_value("HKCU", path, str(exe))
        new_value = _layers_value(str(current) if existed and current is not None else "")
        changelog.set_value("HKCU", path, str(exe), "sz", new_value)
        changed += 1
    if not changed:
        return "Executáveis do CS2 e do Rocket League não encontrados.", False
    return f"Otimizações de tela cheia desligadas em {changed} executável(is).", False


def _clean_temp(plan: dict, changelog: ChangeLog) -> tuple[str, bool]:
    folder = Path(plan.get("temp") or "")
    try:
        folder = folder.resolve()
    except OSError as error:
        raise RuntimeError(f"Pasta Temp inválida: {error}") from error
    if folder.name.lower() != "temp":
        raise RuntimeError("A limpeza só aceita a pasta Temp do usuário.")
    removed = 0
    skipped = 0
    for child in folder.iterdir():
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            elif child.is_file():
                child.unlink()
            removed += 1
        except OSError:
            skipped += 1
    return f"Temporários removidos: {removed}. Em uso, mantidos: {skipped}.", False


def _close_heavy(plan: dict, changelog: ChangeLog) -> tuple[str, bool]:
    wanted = {name.lower() for name in plan.get("close_names") or []} & set(CLOSE_CANDIDATES)
    wanted -= REFUSE_KILL
    closed = []
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info.get("name") or "").lower()
        except (psutil.Error, OSError):
            continue
        if name not in wanted:
            continue
        try:
            proc.terminate()
            closed.append(name)
        except (psutil.Error, OSError):
            continue
    if not closed:
        return "Nenhum dos programas pesados ainda estava aberto.", False
    return "Encerrados: " + ", ".join(sorted(set(closed))) + ".", False


def _startup(plan: dict, changelog: ChangeLog) -> tuple[str, bool]:
    removed = []
    for item in plan.get("startups") or []:
        root = item["root"]
        path = item["path"]
        name = item["name"]
        existed, reg_type, value = read_value(root, path, name)
        if not existed or reg_type is None:
            continue
        changelog.remember_startup(root, path, name, reg_type, value)
        delete_value(root, path, name)
        removed.append(name)
    if not removed:
        return "Nenhum item pesado de inicialização ainda estava no registro.", False
    return "Removidos da inicialização: " + ", ".join(removed) + ".", False


def _cs2(plan: dict, changelog: ChangeLog) -> tuple[str, bool]:
    if _running({"cs2.exe"}):
        return "CS2 está aberto. Feche o jogo e aplique de novo. O arquivo não foi modificado.", False
    raw = plan.get("cs2_video") or ""
    path = Path(raw) if raw else None
    if path is None or not path.is_file():
        return "cs2_video.txt não encontrado. Nada alterado neste item.", False
    text, encoding = read_text(path)
    from orion.textcfg import vdf_values
    from orion.scanner.configs import CS2_KEYS

    values = vdf_values(text, CS2_KEYS)
    updates = cs2_changes(values)
    if not updates:
        return "O vídeo do CS2 já estava no preset. Arquivo intocado.", False
    changelog.replace_file(path, set_vdf_values(text, updates), encoding)
    return "Preset competitivo gravado no CS2: " + ", ".join(sorted(updates)) + ".", False


def _rl(plan: dict, changelog: ChangeLog) -> tuple[str, bool]:
    if _running({"rocketleague.exe"}):
        return "Rocket League está aberto. Feche o jogo e aplique de novo. O arquivo não foi modificado.", False
    raw = plan.get("rl_ini") or ""
    path = Path(raw) if raw else None
    if path is None or not path.is_file():
        return "TASystemSettings.ini não encontrado. Nada alterado neste item.", False
    text, encoding = read_text(path)
    from orion.textcfg import ini_values

    values = ini_values(text)
    display = None
    if isinstance(plan.get("display"), list) and len(plan["display"]) == 2:
        display = (int(plan["display"][0]), int(plan["display"][1]))
    updates = rl_changes(values, display)
    if not updates:
        return "O Rocket League já estava no preset. Arquivo intocado.", False
    changelog.replace_file(path, set_ini_values(text, updates), encoding)
    return "Preset competitivo gravado no Rocket League: " + ", ".join(sorted(updates)) + ".", False


HANDLERS = {
    "power_high": _power_high,
    "game_mode_on": _game_mode,
    "disable_game_dvr": _game_dvr,
    "mouse_accel_off": _mouse,
    "hags_off": _hags,
    "discord_overlay_off": _discord,
    "gpu_preference": _gpu_preference,
    "disable_fso": _fso,
    "clean_temp": _clean_temp,
    "close_heavy": _close_heavy,
    "disable_heavy_startup": _startup,
    "cs2_competitive": _cs2,
    "rl_competitive": _rl,
}
