"""Transforma a medição em causa, evidência e melhora esperada."""

from __future__ import annotations

from orion.models import GameEntry, Issue, Snapshot
from orion.scanner.configs import cs2_preset_needed, discord_overlay_enabled, rl_preset_needed
from orion.scanner.profiles import gpu_tier, polars_or_old_amd, weak_cpu
from orion.scanner.processes import CLOSE_CANDIDATES

HIGH_POWER = {
    "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",  # Alto desempenho
    "e9a42b02-d5df-448d-aa00-03f14749eb61",  # Desempenho máximo
}

LEVEL_NAME = {"0": "baixo", "1": "médio-baixo", "2": "médio", "3": "alto"}


def _gb(size: int | None) -> str:
    if not size:
        return "tamanho não lido"
    return f"{size / (1024 ** 3):.0f} GB"


def _issue(**kwargs) -> Issue:
    return Issue(**kwargs)


def _primary_display(snapshot: Snapshot):
    if not snapshot.displays:
        return None
    for display in snapshot.displays:
        if display.primary:
            return display
    return snapshot.displays[0]


def _disk(snapshot: Snapshot, letter: str):
    for disk in snapshot.disks:
        if disk.letter.upper() == (letter or "").upper():
            return disk
    return None


def _ssd_free(snapshot: Snapshot):
    ssds = [disk for disk in snapshot.disks if disk.media == "SSD"]
    if not ssds:
        return None
    return max(ssds, key=lambda item: item.free_gb)


def _games(snapshot: Snapshot, profile: str) -> list[GameEntry]:
    return [game for game in snapshot.games if game.profile == profile]


def _int_setting(values: dict, key: str, default: int = 0) -> int:
    try:
        return int(str(values.get(key, default)).strip())
    except (TypeError, ValueError):
        return default


def evaluate(snapshot: Snapshot) -> tuple[list[Issue], list[str]]:
    issues: list[Issue] = []
    healthy: list[str] = []
    cpu_weak = weak_cpu(snapshot.cpu_name, snapshot.cpu_max_mhz)
    gpu = snapshot.gpus[0] if snapshot.gpus else None
    tier = gpu_tier(gpu.name) if gpu else "desconhecida"
    display = _primary_display(snapshot)
    cs2 = _games(snapshot, "cs2")
    rl = _games(snapshot, "rocket_league")
    cs2_cfg = snapshot.configs.get("cs2") or {}
    rl_cfg = snapshot.configs.get("rocket_league") or {}

    if cpu_weak:
        issues.append(
            _issue(
                id="cpu_ceiling",
                title="O processador limita o FPS dos jogos competitivos",
                severity="alto",
                category="Hardware",
                cause=(
                    "CS2 e Rocket League dependem de um único núcleo rápido. "
                    f"{snapshot.cpu_name.strip()} trabalha a cerca de {snapshot.cpu_max_mhz:.0f} MHz. "
                    "Esse clock baixo segura a taxa de quadros mesmo quando a placa de vídeo ainda tem folga."
                ),
                evidence=(
                    f"{snapshot.cpu_cores} núcleos, {snapshot.cpu_threads} threads, "
                    f"clock máximo lido em {snapshot.cpu_max_mhz:.0f} MHz, uso agora em {snapshot.cpu_percent:.0f}% "
                    f"(núcleo mais ocupado em {snapshot.cpu_busiest_core:.0f}%)."
                ),
                impact=(
                    "Nenhuma opção do Windows multiplica o FPS deste processador. "
                    "O que muda de verdade é tirar programas do mesmo núcleo, baixar a carga de CPU dentro do jogo "
                    "e reduzir travadas. A média sobe pouco; a estabilidade sobe mais."
                ),
                games=["Counter-Strike 2", "Rocket League"],
            )
        )
    else:
        healthy.append(f"Processador com clock adequado para jogos: {snapshot.cpu_name.strip()}.")

    if gpu is None:
        issues.append(
            _issue(
                id="gpu_missing",
                title="Não foi possível identificar a placa de vídeo",
                severity="medio",
                category="Hardware",
                cause="Sem o nome da placa, o ORION não separa limite de GPU de limite de CPU.",
                evidence="A consulta ao Windows não devolveu um adaptador gráfico.",
                impact="Repita a verificação. Se continuar vazio, o driver da placa pode não estar instalado.",
            )
        )
    else:
        vram = f", {gpu.vram_gb:.0f} GB de VRAM" if gpu.vram_gb else ""
        if tier == "entrada":
            issues.append(
                _issue(
                    id="gpu_entry",
                    title=f"{gpu.name} pede preset mais baixo nos jogos pesados",
                    severity="medio",
                    category="Hardware",
                    cause=(
                        "Esta placa ainda roda CS2 e Rocket League em preset competitivo. "
                        "Em jogos abertos e pesados ela enche a VRAM e o chip, e o HD piora o carregamento de textura."
                    ),
                    evidence=f"Driver {gpu.driver_version or 'não lido'}{vram}. Data do driver: {gpu.driver_date or 'não lida'}.",
                    impact=(
                        "Baixar sombra, anti-aliasing e efeitos devolve FPS nos jogos competitivos. "
                        "Em mundo aberto a melhora existe, mas o teto continua sendo esta placa."
                    ),
                    games=[game.name for game in snapshot.games if game.profile == "heavy"][:6],
                )
            )
        elif tier == "fraca":
            issues.append(
                _issue(
                    id="gpu_weak",
                    title="A placa de vídeo é o limite dos jogos",
                    severity="alto",
                    category="Hardware",
                    cause=f"{gpu.name} não sustenta presets altos nos jogos atuais.",
                    evidence=f"Driver {gpu.driver_version or 'não lido'}{vram}.",
                    impact="Presets baixos e resolução nativa do monitor são o que cabe neste hardware.",
                )
            )
        else:
            healthy.append(f"Placa de vídeo identificada: {gpu.name}{vram}.")

        if gpu.vendor == "amd" and polars_or_old_amd(gpu.name):
            hags = snapshot.hags_mode
            if hags == 2:
                issues.append(
                    _issue(
                        id="hags_on",
                        title="Agendamento de GPU por hardware está ligado numa placa antiga",
                        severity="alto",
                        category="Windows",
                        cause=(
                            "O agendamento de GPU pelo hardware (HAGS) em placas Polaris, como a RX 580, "
                            "é uma causa conhecida de engasgo e tempo de quadro irregular."
                        ),
                        evidence="HwSchMode = 2 no registro da placa.",
                        impact="Desligar e reiniciar costuma reduzir microtravadas. Não aumenta o teto de FPS da placa.",
                        fix_id="hags_off",
                    )
                )
            else:
                healthy.append("Agendamento de GPU por hardware está desligado, que é o estado estável nesta placa AMD antiga.")

    if snapshot.ram_total_gb < 12:
        issues.append(
            _issue(
                id="ram_low",
                title="Pouca memória RAM para manter o jogo e o Windows juntos",
                severity="alto",
                category="Hardware",
                cause="Quando a RAM acaba, o Windows passa a usar o disco. No HD isso congela o jogo por segundos.",
                evidence=f"{snapshot.ram_total_gb:.1f} GB no total, {snapshot.ram_available_gb:.1f} GB livres agora.",
                impact="Fechar navegador e launchers devolve fluidez imediata. Mais RAM seria a correção definitiva.",
            )
        )
    elif snapshot.ram_available_gb < 6:
        issues.append(
            _issue(
                id="ram_pressure",
                title="Pouca RAM livre neste momento",
                severity="medio",
                category="Memória",
                cause="O computador tem memória instalada, mas outros programas já ocuparam a maior parte.",
                evidence=f"{snapshot.ram_available_gb:.1f} GB livres de {snapshot.ram_total_gb:.1f} GB.",
                impact="Fechar os programas pesados devolve folga na hora. O efeito aparece como menos travada, não como mais Hz no monitor.",
                fix_id="close_heavy",
            )
        )
    else:
        sticks = f", {snapshot.ram_sticks} pente(s)" if snapshot.ram_sticks else ""
        speed = f" a {snapshot.ram_speed_mhz} MHz" if snapshot.ram_speed_mhz else ""
        healthy.append(f"Memória folgada: {snapshot.ram_available_gb:.1f} GB livres de {snapshot.ram_total_gb:.1f} GB{sticks}{speed}.")

    for disk in snapshot.disks:
        if disk.health and disk.health.lower() not in {"healthy", "ok", ""}:
            issues.append(
                _issue(
                    id=f"disk_health_{disk.letter}",
                    title=f"O disco {disk.letter}: não está saudável",
                    severity="critico",
                    category="Disco",
                    cause="Disco com aviso de saúde corrompe arquivo de jogo e trava o carregamento.",
                    evidence=f"{disk.name} está como {disk.health}.",
                    impact="Faça cópia dos arquivos importantes. Correção de software não recupera disco falhando.",
                )
            )
        if disk.media == "SSD" and disk.free_percent < 12:
            issues.append(
                _issue(
                    id=f"ssd_full_{disk.letter}",
                    title=f"O SSD {disk.letter}: está com pouco espaço livre",
                    severity="alto",
                    category="Disco",
                    cause="SSD quase cheio fica lento para gravar. O Windows e o cache de shader começam a engasgar.",
                    evidence=f"{disk.free_gb:.0f} GB livres de {disk.total_gb:.0f} GB em {disk.name}.",
                    impact="Liberar espaço devolve a velocidade normal do SSD. A limpeza de temporários ajuda só um pouco.",
                    fix_id="clean_temp",
                )
            )

    hdd_games = [game for game in snapshot.games if game.drive_media == "HDD" and game.profile in {"cs2", "heavy", "medium", "rocket_league"}]
    if hdd_games:
        names = ", ".join(game.name for game in hdd_games[:8])
        ssd = _ssd_free(snapshot)
        room = ""
        if ssd:
            room = f" O SSD {ssd.letter}: ({ssd.name}) tem {ssd.free_gb:.0f} GB livres."
        issues.append(
            _issue(
                id="games_on_hdd",
                title="Jogos instalados em disco rígido mecânico",
                severity="alto",
                category="Disco",
                cause=(
                    "No HD mecânico o jogo para para esperar textura, mapa e shader. "
                    "A média de FPS quase não muda; as travadas no meio da ação mudam muito. "
                    "Isso é forte em CS2, que lê mapa e efeito o tempo todo."
                ),
                evidence=names + "." + room,
                impact=(
                    "Mover o jogo para o SSD reduz as travadas de carregamento. "
                    "Se não houver espaço, o SSD precisa de folga antes: o ORION não apaga jogo nem move dezenas de GB sozinho."
                ),
                games=[game.name for game in hdd_games],
            )
        )
    else:
        relevant = [game for game in snapshot.games if game.profile in {"cs2", "heavy", "medium", "rocket_league"}]
        unknown = [game.name for game in relevant if game.drive_media not in {"HDD", "SSD"}]
        if unknown:
            issues.append(
                _issue(
                    id="disk_unknown",
                    title="Não deu para saber se alguns jogos estão em SSD ou HD",
                    severity="info",
                    category="Disco",
                    cause="Sem o tipo do disco, a travada de carregamento fica sem diagnóstico.",
                    evidence=", ".join(unknown[:8]) + ".",
                    impact="Repita a verificação. Se continuar, o tipo de mídia não veio do Windows.",
                    games=unknown[:8],
                )
            )
        elif relevant:
            healthy.append("Nenhum jogo competitivo ou pesado foi encontrado em HD mecânico.")

    if snapshot.power_guid.lower() not in HIGH_POWER:
        issues.append(
            _issue(
                id="power_plan",
                title="O plano de energia não está em alto desempenho",
                severity="alto",
                category="Windows",
                cause=(
                    "No plano equilibrado o Windows reduz o clock do processador entre um quadro e outro. "
                    "Em CPU já lenta isso aparece como 1% low ruim e mira pesada."
                ),
                evidence=f"Plano ativo: {snapshot.power_plan or snapshot.power_guid or 'não identificado'}.",
                impact="Alto desempenho mantém o clock acordado. A melhora é na estabilidade da taxa, não em um FPS máximo novo.",
                fix_id="power_high",
            )
        )
    else:
        healthy.append(f"Plano de energia já está em {snapshot.power_plan or 'alto desempenho'}.")

    if snapshot.game_mode is False:
        issues.append(
            _issue(
                id="game_mode_off",
                title="Modo de Jogo do Windows está desligado",
                severity="medio",
                category="Windows",
                cause="Com o Modo de Jogo desligado, o Windows não prioriza o processo do jogo diante de atualizações e serviços.",
                evidence="AutoGameModeEnabled = 0.",
                impact="Ligado, reduz interferência de segundo plano. O ganho é pequeno e aparece mais nas quedas do que na média.",
                fix_id="game_mode_on",
            )
        )
    elif snapshot.game_mode is True:
        healthy.append("Modo de Jogo do Windows está ligado.")

    if snapshot.game_dvr is not False:
        evidence = "A gravação em segundo plano está ligada." if snapshot.game_dvr else "A chave da gravação não está desligada de forma explícita."
        issues.append(
            _issue(
                id="game_dvr",
                title="Xbox Game DVR pode estar gravando por baixo do jogo",
                severity="alto",
                category="Windows",
                cause=(
                    "A captura em segundo plano engancha na tela cheia, usa GPU e adiciona atraso. "
                    "Em placa de entrada e em HD isso vira microtravada."
                ),
                evidence=evidence,
                impact="Desligar a captura libera um pouco de GPU e tira uma camada de latência. Não muda a qualidade gráfica do jogo.",
                fix_id="disable_game_dvr",
            )
        )
    else:
        healthy.append("Gravação do Game DVR está desligada.")

    if snapshot.mouse_accel:
        issues.append(
            _issue(
                id="mouse_accel",
                title="Aceleração do mouse está ligada",
                severity="alto",
                category="Controle",
                cause="A aceleração muda a distância da mira conforme a velocidade da mão. Em CS2 e Rocket League a mira deixa de ser repetível.",
                evidence="MouseSpeed ou MouseThreshold diferente de zero no painel do mouse.",
                impact="Desligar não aumenta FPS. A mira fica consistente, que é o que decide duelo nestes dois jogos.",
                fix_id="mouse_accel_off",
                games=["Counter-Strike 2", "Rocket League"],
            )
        )
    elif snapshot.mouse_accel is False:
        healthy.append("Aceleração do mouse já está desligada.")

    if display is None:
        issues.append(
            _issue(
                id="display_unknown",
                title="Não li a taxa de atualização do monitor",
                severity="baixo",
                category="Monitor",
                cause="Sem o Hz do Windows, não dá para saber se o limite é o monitor ou o jogo.",
                evidence="EnumDisplaySettings não devolveu um modo ativo.",
                impact="Confira em Configurações > Sistema > Vídeo > Monitor avançado.",
            )
        )
    elif display.hz and display.hz <= 60:
        issues.append(
            _issue(
                id="refresh_60",
                title=f"O Windows está em {display.width}x{display.height} a {display.hz} Hz",
                severity="medio",
                category="Monitor",
                cause=(
                    "A imagem não mostra mais do que a taxa do monitor. "
                    "Se este painel for de 60 Hz, FPS acima disso não vira mais fluidez na tela. "
                    "Ainda reduz um pouco o atraso da entrada quando o jogo renderiza à frente."
                ),
                evidence=f"Monitor '{display.name}' no modo atual de {display.width}x{display.height} @{display.hz} Hz.",
                impact=(
                    "Se o monitor tiver 75, 120 ou 144 Hz e o Windows estiver em 60, trocar a taxa é o maior salto visível que existe. "
                    "Se 60 Hz for o teto do painel, as correções de software melhoram tranco e atraso, não a suavidade além de 60."
                ),
            )
        )
    elif display.hz >= 120:
        healthy.append(f"Monitor principal em {display.width}x{display.height} a {display.hz} Hz.")

    if snapshot.pending_reboot:
        issues.append(
            _issue(
                id="pending_reboot",
                title="Há uma reinicialização pendente",
                severity="medio",
                category="Windows",
                cause="Driver e atualização só terminam de valer depois do reboot. Até lá o jogo pode usar o driver antigo pela metade.",
                evidence="O Windows marcou reinício pendente de atualização ou de arquivo.",
                impact="Reiniciar aplica o que já foi instalado. Não é um ganho extra em cima disso.",
            )
        )

    def _adapter_text(item: dict) -> str:
        return f"{item.get('media', '')} {item.get('name', '')}".lower()

    wifi = [item for item in snapshot.adapters if any(token in _adapter_text(item) for token in ("802.11", "wi-fi", "wifi", "wireless"))]
    ethernet = [item for item in snapshot.adapters if any(token in _adapter_text(item) for token in ("802.3", "ethernet"))]
    if wifi and not ethernet:
        speed = wifi[0].get("speed") or "velocidade não lida"
        issues.append(
            _issue(
                id="wifi_only",
                title="Os jogos online estão saindo por Wi-Fi",
                severity="medio",
                category="Rede",
                cause="Wi-Fi varia. CS2 e Rocket League transformam essa variação em inimigo teleportando e bola atrasada. Isso não é queda de FPS.",
                evidence=f"Adaptador ativo: {wifi[0].get('name', 'Wi-Fi')} ({speed}). Nenhum Ethernet ativo foi visto.",
                impact="Cabo reduz perda e variação. O FPS da placa continua o mesmo.",
                games=["Counter-Strike 2", "Rocket League"],
            )
        )

    for probe in snapshot.network:
        loss = probe.get("loss_percent")
        avg = probe.get("avg_ms")
        if probe.get("ok") and loss is not None and 0 < loss < 100:
            issues.append(
                _issue(
                    id=f"loss_{probe.get('label', 'rede')}",
                    title=f"Perda de pacote até {probe.get('label', probe.get('host'))}",
                    severity="alto",
                    category="Rede",
                    cause="Pacote perdido não derruba o FPS. Derruba o tick do servidor: tiro que não registra e carro que não vira.",
                    evidence=f"{probe.get('host')} com {loss}% de perda em 3 pacotes.",
                    impact="A correção é rede, cabo ou a operadora. O ORION não muda rota da internet.",
                )
            )
        elif avg is not None and avg >= 80 and probe.get("label") == "Internet":
            issues.append(
                _issue(
                    id="high_ping",
                    title="A latência base da internet está alta",
                    severity="medio",
                    category="Rede",
                    cause="Ping alto é distância e rota até o servidor. Não é configuração de sombra nem de energia.",
                    evidence=f"Média de {avg} ms até {probe.get('host')}.",
                    impact="Mudar de servidor ou de rota melhora a resposta online. A taxa de quadros local fica igual.",
                )
            )

    busy = [proc for proc in snapshot.processes if proc.cpu >= 20 or proc.rss_mb >= 700]
    notable = [proc for proc in busy if proc.note][:5]
    if notable:
        evidence = "; ".join(f"{proc.name} {proc.rss_mb:.0f} MB / {proc.cpu:.0f}% CPU" for proc in notable)
        closable = sorted({proc.name.lower() for proc in snapshot.processes if proc.name.lower() in CLOSE_CANDIDATES and proc.rss_mb >= 250})
        issues.append(
            _issue(
                id="background",
                title="Há programas pesados abertos junto com a área de trabalho",
                severity="medio" if snapshot.cpu_percent < 45 else "alto",
                category="Processos",
                cause=(
                    "Neste processador um núcleo ocupado por navegador ou overlay é um núcleo a menos para o jogo. "
                    + " ".join(proc.note for proc in notable[:2])
                ),
                evidence=evidence + f". Uso total da CPU na verificação: {snapshot.cpu_percent:.0f}%.",
                impact="Fechar o que não estiver em uso sobe o 1% low na hora. O ORION só fecha o que você marcar.",
                fix_id="close_heavy" if closable else None,
            )
        )

    overlay_on, _discord_path = discord_overlay_enabled()
    discord_running = any(proc.name.lower() == "discord.exe" for proc in snapshot.processes)
    if overlay_on and (discord_running or _discord_path):
        issues.append(
            _issue(
                id="discord_overlay",
                title="A sobreposição do Discord está habilitada",
                severity="medio",
                category="Overlay",
                cause="A overlay entra dentro do processo do jogo. Em CS2 isso aparece como microtravada e, às vezes, atraso de input.",
                evidence="enableOverlay não está desligado nas configurações do Discord."
                + (" O Discord está aberto agora." if discord_running else " O Discord está instalado."),
                impact="Desligar a overlay mantém o voz. A melhora é estabilidade, não um salto grande de FPS médio.",
                fix_id="discord_overlay_off",
                games=["Counter-Strike 2", "Rocket League"],
            )
        )

    if any(proc.name.lower() in {"amddvr.exe", "amdow.exe"} for proc in snapshot.processes):
        issues.append(
            _issue(
                id="amd_overlay",
                title="Overlay ou gravação da AMD está em execução",
                severity="alto",
                category="Overlay",
                cause="A gravação instantânea da Radeon faz a mesma coisa que o Game DVR: prende um pedaço da GPU o tempo todo.",
                evidence="Processo amddvr.exe ou amdow.exe encontrado.",
                impact="Desligar Instant Replay no painel AMD (Alt+R) devolve essa fatia da placa. O ORION não mexe no driver.",
            )
        )

    heavy_start = [item.name for item in snapshot.startups if item.heavy]
    if len(heavy_start) >= 3:
        issues.append(
            _issue(
                id="startup",
                title="Vários programas pesados abrem junto com o Windows",
                severity="baixo",
                category="Inicialização",
                cause="Eles já estão na memória quando o jogo abre e continuam acordando durante a partida.",
                evidence=", ".join(heavy_start[:8]) + ".",
                impact="Tirar da inicialização não aumenta o teto de FPS. Evita que eles voltem a competir depois de cada boot.",
                fix_id="disable_heavy_startup",
            )
        )

    _cs2_issues(issues, healthy, snapshot, cs2, cs2_cfg, cpu_weak, display)
    _rl_issues(issues, healthy, snapshot, rl, rl_cfg, display)
    _other_games(issues, snapshot, tier)

    exes = [game.executable for game in snapshot.games if game.executable and game.profile in {"cs2", "rocket_league", "heavy", "medium"}]
    if exes:
        issues.append(
            _issue(
                id="gpu_preference",
                title="Os jogos podem ser fixados na placa de alto desempenho",
                severity="baixo",
                category="Windows",
                cause="Quando há mais de um adaptador, ou quando o Windows escolhe economia, o jogo abre na opção errada.",
                evidence=f"{len(exes)} executáveis de jogo com caminho confirmado.",
                impact="A preferência 'alto desempenho' evita a placa errada. Num PC com uma RX 580 só, o ganho é pequeno e seguro.",
                fix_id="gpu_preference",
                games=[game.name for game in snapshot.games if game.executable][:8],
            )
        )

    if any(game.executable for game in cs2 + rl):
        issues.append(
            _issue(
                id="fso",
                title="Otimizações de tela cheia do Windows nos executáveis do CS2 e do Rocket League",
                severity="baixo",
                category="Windows",
                cause=(
                    "Essas otimizações colocam o jogo em uma camada composta pelo Windows. "
                    "Em algumas placas AMD isso adiciona atraso e travada no modo em tela cheia."
                ),
                evidence="A correção grava DISABLEDXMAXIMIZEDWINDOWEDMODE só nos executáveis encontrados.",
                impact="Pode reduzir latência no modo exclusivo. Em janela sem borda a diferença é menor. Vale a próxima partida, e desfaz pelo backup.",
                fix_id="disable_fso",
                games=[game.name for game in cs2 + rl],
            )
        )

    order = {"critico": 0, "alto": 1, "medio": 2, "baixo": 3, "info": 4}
    issues.sort(key=lambda item: (order.get(item.severity, 9), item.title))
    return issues, healthy


def _cs2_issues(issues: list[Issue], healthy: list[str], snapshot: Snapshot, games: list[GameEntry], cfg: dict, cpu_weak: bool, display) -> None:
    if not games and not cfg:
        return
    values = cfg.get("values") or {}
    if not values:
        issues.append(
            _issue(
                id="cs2_cfg_missing",
                title="Counter-Strike 2 está instalado, mas o video cfg não foi lido",
                severity="info",
                category="CS2",
                cause="O arquivo cs2_video.txt aparece depois da primeira partida.",
                evidence=cfg.get("install_dir") or "Instalação Steam encontrada.",
                impact="Abra o jogo uma vez e varra de novo para o ORION ler VSync, sombra e MSAA.",
                games=["Counter-Strike 2"],
            )
        )
        return
    width = _int_setting(values, "setting.defaultres")
    height = _int_setting(values, "setting.defaultresheight")
    vsync = _int_setting(values, "setting.mat_vsync")
    cpu_level = str(values.get("setting.cpu_level", ""))
    gpu_level = str(values.get("setting.gpu_level", ""))
    msaa = str(values.get("setting.msaa_samples", ""))
    borderless = values.get("setting.fullscreen") == "0" and values.get("setting.coop_fullscreen") == "1"
    bits = [
        f"{width}x{height}" if width and height else "resolução não lida",
        f"VSync {'ligado' if vsync else 'desligado'}",
        f"CPU do jogo {LEVEL_NAME.get(cpu_level, cpu_level or '?')}",
        f"GPU do jogo {LEVEL_NAME.get(gpu_level, gpu_level or '?')}",
        f"MSAA {msaa or '?'}",
        "janela sem borda" if borderless else "tela cheia ou janela",
    ]
    if vsync:
        issues.append(
            _issue(
                id="cs2_vsync",
                title="VSync do CS2 está ligado",
                severity="alto",
                category="CS2",
                cause="VSync segura o quadro até o próximo refresh e soma atraso na mira.",
                evidence=", ".join(bits) + ".",
                impact="Desligar o VSync reduz o atraso. Pode aparecer tearing. Com monitor de 60 Hz a fluidez da imagem continua em 60.",
                fix_id="cs2_competitive",
                games=["Counter-Strike 2"],
            )
        )
    else:
        healthy.append("VSync do CS2 já está desligado.")
    if cs2_preset_needed(values, cpu_weak):
        issues.append(
            _issue(
                id="cs2_preset",
                title="O CS2 está com carga gráfica e de CPU alta para este PC",
                severity="alto",
                category="CS2",
                cause=(
                    "Sombra dinâmica, oclusão de ambiente e MSAA alto custam caro na RX 580. "
                    "Nível alto de CPU no CS2 pede trabalho extra justamente do núcleo que já é o limite."
                ),
                evidence=", ".join(bits) + f". Arquivo: {cfg.get('video_path') or 'cs2_video.txt'}.",
                impact=(
                    "O preset competitivo baixa sombra, MSAA e o nível de CPU, e mantém a sua resolução. "
                    "A imagem fica mais simples. Neste tipo de hardware o usual é ganhar estabilidade e dezenas de FPS "
                    "quando se sai do preset alto — é estimativa, medida na próxima partida, não uma promessa."
                ),
                fix_id="cs2_competitive",
                games=["Counter-Strike 2"],
            )
        )
    else:
        healthy.append("As opções de vídeo do CS2 já estão próximas de um preset competitivo.")
    if borderless:
        issues.append(
            _issue(
                id="cs2_borderless",
                title="CS2 está em janela sem borda",
                severity="baixo",
                category="CS2",
                cause="A janela sem borda é composta pelo Windows. O alt-tab fica melhor e a latência fica um pouco pior do que na tela cheia exclusiva.",
                evidence="fullscreen = 0 e coop_fullscreen = 1.",
                impact="O ORION não troca o modo de tela sozinho, porque isso muda o alt-tab. Se a latência incomodar, use tela cheia exclusiva dentro do jogo.",
                games=["Counter-Strike 2"],
            )
        )
    if display and width and height and (width != display.width or height != display.height):
        issues.append(
            _issue(
                id="cs2_resolution",
                title="A resolução do CS2 é diferente da área de trabalho",
                severity="info",
                category="CS2",
                cause="Resolução esticada ou reduzida muda nitidez e, às vezes, o quanto a placa desenha.",
                evidence=f"Jogo em {width}x{height} e Windows em {display.width}x{display.height} @{display.hz} Hz.",
                impact="Igualar à nativa deixa o pixel 1:1. Resolução menor pode subir FPS e embaçar a imagem. A escolha fica com você; o ORION não troca isso no preset.",
                games=["Counter-Strike 2"],
            )
        )
    if cfg.get("on_hdd"):
        game = games[0] if games else None
        ssd = _ssd_free(snapshot)
        free = f"{ssd.free_gb:.0f} GB livres em {ssd.letter}:" if ssd else "não há SSD com letra livre"
        size = _gb(cfg.get("size_bytes"))
        issues.append(
            _issue(
                id="cs2_hdd",
                title="Counter-Strike 2 está instalado no HD mecânico",
                severity="critico",
                category="CS2",
                cause=(
                    "CS2 puxa mapa, fumaça e shader durante o round. No HD de notebook isso para o quadro "
                    "mesmo quando o contador de FPS parecia estável no menu."
                ),
                evidence=f"Pasta {cfg.get('install_dir') or (game.install_dir if game else '')}. Tamanho {size}. SSD do sistema: {free}.",
                impact=(
                    "Mover o CS2 para o SSD é a correção de travada mais forte deste PC. "
                    "O ORION não move o jogo automaticamente: são dezenas de GB e a Steam precisa registrar a biblioteca. "
                    "Se o SSD não tiver o tamanho do jogo mais uns 20 GB de folga, apague o que não usa antes."
                ),
                games=["Counter-Strike 2"],
            )
        )


def _rl_issues(issues: list[Issue], healthy: list[str], snapshot: Snapshot, games: list[GameEntry], cfg: dict, display) -> None:
    if not games and not cfg:
        return
    values = cfg.get("values") or {}
    if not values:
        issues.append(
            _issue(
                id="rl_cfg_missing",
                title="Rocket League está instalado, mas o ini de sistema não foi lido",
                severity="info",
                category="Rocket League",
                cause="O arquivo nasce em Documentos depois que o jogo grava as opções.",
                evidence=cfg.get("install_dir") or "Instalação encontrada.",
                impact="Abra o jogo, feche, e varra de novo.",
                games=["Rocket League"],
            )
        )
        return
    vsync = str(values.get("UseVsync", "")).lower() == "true"
    width = _int_setting(values, "ResX")
    height = _int_setting(values, "ResY")
    borderless = str(values.get("Borderless", "")).lower() == "true"
    if rl_preset_needed(values) or (display and width > display.width and height > display.height):
        extra = ""
        if display and width > display.width and height > display.height:
            extra = f" O jogo desenha {width}x{height} num monitor de {display.width}x{display.height}, ou seja, pixel que a tela nem mostra."
        issues.append(
            _issue(
                id="rl_preset",
                title="Rocket League está com VSync, atraso de quadro ou efeitos pesados",
                severity="critico" if vsync else "alto",
                category="Rocket League",
                cause=(
                    "UseVsync prende o jogo na taxa do monitor e soma atraso no controle. "
                    "OneFrameThreadLag segura um quadro inteiro antes de mostrar. "
                    "AllowPerFrameSleep faz o jogo dormir entre quadros. "
                    "Sombra e reflexo gastam a RX 580 sem mudar a leitura da bola."
                    + (" A resolução dinâmica mirando 60 FPS ainda embaça a imagem para segurar essa taxa." if str(values.get("UpscaleScreenPercentage", "")).lower() == "true" else "")
                ),
                evidence=(
                    f"UseVsync={values.get('UseVsync', '?')}, OneFrameThreadLag={values.get('OneFrameThreadLag', '?')}, "
                    f"AllowPerFrameSleep={values.get('AllowPerFrameSleep', '?')}, "
                    f"DynamicShadows={values.get('DynamicShadows', '?')}, {width}x{height}, "
                    f"{'sem borda' if borderless else 'tela cheia ou janela'}."
                    + extra
                ),
                impact=(
                    "Desligar VSync e o atraso de um quadro reduz o input lag na hora. "
                    "O FPS deixa de ser cortado pela taxa do monitor e passa a ser o FPS real do PC. "
                    "Pode aparecer tearing. Sombras desligadas sobem um pouco a taxa e limpam a cena. "
                    "Se a resolução do jogo for maior que a do monitor, ela é igualada à nativa."
                ),
                fix_id="rl_competitive",
                games=["Rocket League"],
            )
        )
    else:
        healthy.append("As opções lidas do Rocket League já estão sem VSync e sem o atraso de um quadro.")
    if cfg.get("on_hdd"):
        issues.append(
            _issue(
                id="rl_hdd",
                title="Rocket League está no HD mecânico",
                severity="medio",
                category="Rocket League",
                cause="O mapa do Rocket League é leve, mas shader e textura no HD ainda causam o primeiro engasgo da partida.",
                evidence=cfg.get("install_dir") or "",
                impact="No SSD a partida começa lisa. A média de FPS no meio do jogo muda pouco.",
                games=["Rocket League"],
            )
        )
    elif games:
        healthy.append("Rocket League está fora de HD mecânico.")


def _other_games(issues: list[Issue], snapshot: Snapshot, tier: str) -> None:
    heavy = [game for game in snapshot.games if game.profile == "heavy"]
    if not heavy:
        return
    on_hdd = [game.name for game in heavy if game.drive_media == "HDD"]
    evidence = ", ".join(game.name for game in heavy[:6])
    if on_hdd:
        evidence += ". No HD: " + ", ".join(on_hdd[:6])
    severity = "alto" if tier in {"entrada", "fraca"} and on_hdd else "medio"
    issues.append(
        _issue(
            id="heavy_games",
            title="Há jogos pesados instalados para o conjunto CPU e placa",
            severity=severity,
            category="Jogos",
            cause=(
                "Mundo aberto e MMO puxam streaming de textura, um núcleo e a placa ao mesmo tempo. "
                "Preset alto nesses títulos não é o mesmo problema de um CS2 competitivo."
            ),
            evidence=evidence + ".",
            impact=(
                "O mínimo, FSR ou resolução dinâmica reduz a média. "
                "Tirá-los do HD reduz a travada de entrar no mundo. O teto do hardware continua."
            ),
            games=[game.name for game in heavy],
        )
    )
