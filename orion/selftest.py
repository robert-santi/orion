"""Confere a leitura deste PC e os editores de arquivo, sem aplicar correção."""

from __future__ import annotations

from orion.scanner.configs import cs2_changes, rl_changes
from orion.scanner.engine import run_scan
from orion.textcfg import ini_values, set_ini_values, set_vdf_values, vdf_values
from orion.ai.analyst import analyze


def _check_editors() -> list[str]:
    errors = []
    vdf = '"video.cfg"\n{\n\t"setting.gpu_level"\t\t"3"\n\t"setting.mat_vsync"\t\t"1"\n}\n'
    updated = set_vdf_values(vdf, {"setting.gpu_level": "1", "setting.mat_vsync": "0"})
    values = vdf_values(updated, {"setting.gpu_level", "setting.mat_vsync"})
    if values.get("setting.gpu_level") != "1" or values.get("setting.mat_vsync") != "0":
        errors.append(f"editor do CS2 falhou: {values}")
    ini = "[SystemSettings]\r\nUseVsync=True\r\nOneFrameThreadLag=True\r\nResX=1920\r\n"
    changed = set_ini_values(ini, {"UseVsync": "False", "AllowPerFrameSleep": "False"})
    read = ini_values(changed)
    if read.get("UseVsync") != "False" or read.get("OneFrameThreadLag") != "True":
        errors.append(f"editor do Rocket League falhou: {read}")
    if "AllowPerFrameSleep=False" not in changed:
        errors.append("chave nova do Rocket League não foi acrescentada")
    if cs2_changes({"setting.gpu_level": "1", "setting.mat_vsync": "0", "setting.cpu_level": "0", "setting.gpu_mem_level": "2", "setting.msaa_samples": "2", "setting.videocfg_shadow_quality": "0", "setting.videocfg_dynamic_shadows": "0", "setting.videocfg_ao_detail": "0", "setting.videocfg_particle_detail": "1", "setting.videocfg_texture_detail": "1", "setting.shaderquality": "0", "setting.r_texturefilteringquality": "1", "setting.r_low_latency": "1"}):
        errors.append("preset do CS2 alteraria um arquivo que já está no alvo")
    if "UseVsync" not in rl_changes({"UseVsync": "True", "ResX": "1280", "ResY": "720"}, (1920, 1080)):
        errors.append("preset do Rocket League não desliga VSync")
    return errors


def _check_product() -> list[str]:
    from orion.ai.monitor import classify_profile, decide, interpret_model_text
    from orion.updater import OFFICIAL_REPO, channel, github_repo, version_status

    errors = []
    if github_repo(OFFICIAL_REPO) != ("robert-santi", "orion"):
        errors.append("canal oficial")
    url, branch, _token = channel({"git_url": "  ", "git_branch": "", "git_token": ""})
    if url != OFFICIAL_REPO or branch != "main" or _token:
        errors.append("canal vazio não cai no oficial")
    if version_status("0.2.2", "v0.2.2") != "same":
        errors.append("mesma versão")
    if version_status("0.2.1", "v0.2.2") != "new":
        errors.append("versão nova")
    if version_status("0.2.2", "v0.2.1") != "same":
        errors.append("não deve voltar versão")
    if github_repo("https://github.com/foo/bar.git") != ("foo", "bar"):
        errors.append("endereço GitHub com .git")
    if github_repo("git@github.com:foo/bar.git") != ("foo", "bar"):
        errors.append("endereço SSH do GitHub")
    if github_repo("https://github.com/foo/bar/") != ("foo", "bar"):
        errors.append("endereço GitHub com barra")
    if github_repo("https://gitlab.com/foo/bar") is not None:
        errors.append("gitlab não é o canal do GitHub")
    if classify_profile("Intel Xeon E5-2660 @ 2.20GHz", 2200, "AMD Radeon RX 580 2048SP", "") != "fraco":
        errors.append("Xeon com RX 580 deveria ser perfil fraco")
    if classify_profile("AMD Ryzen 7 7800X3D", 5000, "NVIDIA GeForce RTX 4070", "") != "forte":
        errors.append("RTX 4070 deveria ser perfil forte")
    if classify_profile("Intel Xeon E5-2660", 2200, "AMD Radeon RX 580", "forte") != "forte":
        errors.append("perfil manual não venceu a leitura")
    ids = {"cs2_competitive", "rl_competitive", "close_heavy", "disable_fso", "clean_temp", "disable_game_dvr"}
    approved, held = decide("fraco", "entrada", ids, True)
    if not {"cs2_competitive", "rl_competitive", "disable_game_dvr"} <= set(approved):
        errors.append(f"perfil fraco não aprovou o esperado: {approved}")
    if "close_heavy" not in held or "disable_fso" not in held or "clean_temp" not in held:
        errors.append(f"perfil fraco não segurou o esperado: {held}")
    approved, held = decide("forte", "forte", ids, True)
    if "cs2_competitive" not in held or "rl_competitive" not in approved or "close_heavy" in approved:
        errors.append(f"perfil forte marcou o que não devia: {approved} {held}")
    raw = (
        '{"profile":"forte","approve":["rl_competitive","inventado"],'
        '"hold":{"cs2_competitive":"placa forte"},'
        '"summary":"A placa forte não precisa do preset baixo."}'
    )
    parsed = interpret_model_text(raw, {"rl_competitive", "cs2_competitive"})
    if not parsed or parsed["approve"] != ["rl_competitive"] or "cs2_competitive" not in parsed["hold"]:
        errors.append(f"leitura do complemento falhou: {parsed}")
    if interpret_model_text("sou uma IA e não tenho JSON", {"rl_competitive"}) is not None:
        errors.append("texto sem JSON foi aceito")
    banned = interpret_model_text(
        '{"profile":"fraco","approve":["rl_competitive"],"hold":{},"summary":"Sou uma IA pronta para conversar."}',
        {"rl_competitive"},
    )
    if not banned or banned["summary"] or banned["approve"] != ["rl_competitive"]:
        errors.append(f"frase interna não foi descartada: {banned}")
    return errors


def _check_debloat() -> list[str]:
    from orion.fixer.debloat import catalog_guard, inspect

    errors = catalog_guard()
    if errors:
        return errors
    try:
        state = inspect()
    except Exception as error:
        return [f"leitura do debloat falhou: {error}"]
    if not isinstance(state.get("apps"), list) or not isinstance(state.get("services"), dict):
        return ["inventário do debloat veio incompleto"]
    print(f"Debloat: {len(state['apps'])} aplicativos candidatos, {len(state['services'])} serviços vistos")
    return []


def run_selftest() -> int:
    errors = _check_editors()
    errors.extend(_check_product())
    errors.extend(_check_debloat())
    print("Editores e regras:", "ok" if not errors else errors)
    if errors:
        print("\nFALHOU:")
        for error in errors:
            print(" -", error)
        return 1
    snapshot = run_scan(lambda message: print(".", message, flush=True))
    report = analyze(snapshot)
    names = [game.name for game in snapshot.games]
    print("\nPC:", snapshot.cpu_name.strip())
    print("GPU:", ", ".join(gpu.name for gpu in snapshot.gpus) or "nenhuma")
    print("RAM livre:", snapshot.ram_available_gb, "de", snapshot.ram_total_gb)
    print("Energia:", snapshot.power_plan)
    for disk in snapshot.disks:
        print(f"Disco {disk.letter}: {disk.media} {disk.free_gb:.0f}/{disk.total_gb:.0f} GB {disk.name}")
    if snapshot.adapters:
        print("Adaptadores:", snapshot.adapters)
    if snapshot.displays:
        screen = snapshot.displays[0]
        print(f"Tela: {screen.width}x{screen.height} @{screen.hz}")
    print("Jogos:", len(names))
    for game in snapshot.games:
        print(f"  - {game.name} [{game.platform}] {game.drive_media} {game.drive_letter}: {game.profile}")
    print("\nNota:", report.score)
    print(report.headline)
    print("\nProblemas:")
    for issue in snapshot.issues:
        fix = f" -> {issue.fix_id}" if issue.fix_id else ""
        print(f"  [{issue.severity}] {issue.title}{fix}")
    if snapshot.notes:
        print("Avisos:", snapshot.notes)
    folded = " ".join(names).lower()
    if "counter-strike 2" not in folded:
        errors.append("CS2 não foi encontrado na Steam")
    if not any("rocket league" in name.lower() for name in names):
        errors.append("Rocket League não foi encontrado")
    if "xeon" not in snapshot.cpu_name.lower():
        errors.append("o processador lido não é o Xeon deste PC")
    titles = " ".join(issue.title + issue.evidence for issue in snapshot.issues).lower()
    if "hd" not in titles and "mecânico" not in titles and "mecanico" not in titles:
        errors.append("não acusou jogo em HD mecânico")
    if "rocket league" not in titles and "vsync" not in titles:
        errors.append("não acusou o VSync ou a config do Rocket League")
    if "counter-strike" not in report.as_text().lower() and "cs2" not in report.as_text().lower():
        errors.append("a leitura não cita o CS2")
    if not 0 <= report.score <= 100:
        errors.append("nota fora de 0–100")
    print("\nSaúde:")
    for line in snapshot.healthy:
        print("  +", line)
    if errors:
        print("\nFALHOU:")
        for error in errors:
            print(" -", error)
        return 1
    print("\nVarredura conferida, sem aplicar correção.")
    return 0
