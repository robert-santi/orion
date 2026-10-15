"""Explica este PC com os números que a varredura mediu. Não inventa FPS."""

from __future__ import annotations

from orion.models import Analysis, GameEntry, Snapshot
from orion.scanner.profiles import gpu_tier, weak_cpu

WEIGHTS = {"critico": 10, "alto": 5, "medio": 2, "baixo": 0}


def _game_line(game: GameEntry, snapshot: Snapshot) -> str:
    place = f"{game.drive_media} ({game.drive_letter}:)" if game.drive_letter else "disco não identificado"
    tier = gpu_tier(snapshot.gpus[0].name) if snapshot.gpus else "desconhecida"
    if game.profile == "cs2":
        return (
            f"na {game.platform}, em {place}. "
            "O teto é o núcleo da CPU. Travada no meio do round, com o jogo no HD, é disco. "
            "Sombra e MSAA altos gastam a placa sem ajudar a mira."
        )
    if game.profile == "rocket_league":
        return (
            f"na {game.platform}, em {place}. "
            "O jogo é leve para a placa e sensível a VSync e atraso de quadro. "
            "A correção de configuração muda a resposta do carro mais do que muda o gráfico."
        )
    if game.profile == "heavy":
        disk = " No HD mecânico o mundo aberto engasga ao puxar textura." if game.drive_media == "HDD" else ""
        plate = " A placa de entrada não segura preset alto." if tier in {"entrada", "fraca"} else ""
        return f"na {game.platform}, em {place}.{disk}{plate} Trate como jogo pesado: preset baixo e, se couber, SSD."
    if game.profile == "light":
        return f"na {game.platform}, em {place}. Título leve. Se travar, a causa está no sistema (HD, overlay ou CPU ocupada), não no gráfico dele."
    if game.profile == "medium":
        return f"na {game.platform}, em {place}. Depende de um núcleo decente e sofre no HD. Preset médio ou baixo neste PC."
    return f"na {game.platform}, em {place}. Sem perfil específico: vale o mesmo diagnóstico de disco, overlay e plano de energia."


def analyze(snapshot: Snapshot) -> Analysis:
    penalty = sum(WEIGHTS.get(issue.severity, 0) for issue in snapshot.issues)
    score = max(8, min(100, 100 - penalty))
    cpu_weak = weak_cpu(snapshot.cpu_name, snapshot.cpu_max_mhz)
    gpu_name = snapshot.gpus[0].name if snapshot.gpus else "placa não identificada"
    display = next((item for item in snapshot.displays if item.primary), snapshot.displays[0] if snapshot.displays else None)
    hz = f"{display.hz} Hz" if display else "Hz não lido"

    if score >= 80:
        headline = "Este PC está bem encaminhado. Os itens que sobraram são ajuste fino."
    elif score >= 60:
        headline = "Dá para jogar. Os itens do topo ainda estão custando resposta e estabilidade."
    elif score >= 40:
        headline = "Há defeitos concretos derrubando a fluidez. Parte se corrige; parte é o hardware."
    else:
        headline = "Vários problemas ao mesmo tempo estão segurando os jogos. Comece pelo topo da lista."

    if cpu_weak:
        bottleneck = (
            f"O gargalo de FPS médio é o processador {snapshot.cpu_name.strip()}, "
            f"com clock máximo lido de {snapshot.cpu_max_mhz:.0f} MHz. "
            f"CS2 e Rocket League não usam os {snapshot.cpu_threads} threads por igual: eles esperam um núcleo rápido. "
            f"A {gpu_name} entra como segundo limite quando o gráfico está alto. "
            f"O monitor em {hz} decide quanta dessa taxa a tela consegue mostrar."
        )
    else:
        bottleneck = (
            f"O processador {snapshot.cpu_name.strip()} não é o alerta principal. "
            f"Olhe a placa ({gpu_name}), o disco dos jogos e as opções de VSync. Monitor em {hz}."
        )

    paragraphs = []
    critical = [issue.title for issue in snapshot.issues if issue.severity == "critico"]
    if critical:
        paragraphs.append("O que mais dói agora: " + "; ".join(critical) + ".")
    paragraphs.append(
        "Travada e FPS médio não são a mesma coisa. Mover jogo para SSD e desligar overlay diminuem o tranco. "
        "Baixar sombra e MSAA sobe a média quando a placa está cheia. "
        "Desligar VSync e a aceleração do mouse muda a resposta, não o número bonito do contador."
    )
    if snapshot.healthy:
        paragraphs.append("O que já está a favor: " + " ".join(snapshot.healthy[:4]))

    per_game = [(game.name, _game_line(game, snapshot)) for game in snapshot.games]
    order = []
    for issue in snapshot.issues:
        if issue.severity in {"critico", "alto"}:
            step = issue.title
            if issue.fix_id:
                step += " — o ORION aplica com ponto de restauração."
            else:
                step += " — orientação, sem escrita automática."
            if step not in order:
                order.append(step)
    if not order:
        order.append("Não há correção urgente. Uma nova verificação depois de instalar outro jogo atualiza a lista.")

    limits = [
        "Estas correções não trocam o processador nem a placa.",
        "Elas não criam Hertz que o monitor não tem.",
        "Elas não diminuem o ping da operadora.",
    ]
    if cpu_weak:
        limits.append(
            "Com este Xeon de clock baixo, o CS2 competitivo continua limitado pelo núcleo mesmo depois do preset. "
            "O ganho esperado é menos queda e menos atraso, não triplicar o FPS."
        )
    hdd_games = [game.name for game in snapshot.games if game.drive_media == "HDD"]
    if hdd_games:
        limits.append(
            "Enquanto " + ", ".join(hdd_games[:4]) + " continuar no HD mecânico, "
            "a travada de carregar mapa e shader permanece, mesmo com o resto corrigido."
        )
    return Analysis(
        score=score,
        headline=headline,
        bottleneck=bottleneck,
        paragraphs=paragraphs,
        per_game=per_game,
        order=order[:6],
        limits=" ".join(limits),
    )


def answer_local(snapshot: Snapshot, analysis: Analysis, question: str) -> str:
    folded = question.lower()
    chunks: list[str] = []
    if any(token in folded for token in ("cs2", "cs 2", "counter", "strike")):
        text = next((body for name, body in analysis.per_game if "counter-strike" in name.lower()), "")
        chunks.append("CS2: " + text if text else "CS2 não apareceu na biblioteca.")
        for issue in snapshot.issues:
            if "CS2" in issue.category or "counter" in issue.title.lower():
                chunks.append(f"{issue.title}. Causa: {issue.cause} Melhora esperada: {issue.impact}")
    if any(token in folded for token in ("rocket", "rl")):
        text = next((body for name, body in analysis.per_game if "rocket" in name.lower()), "")
        chunks.append("Rocket League: " + text if text else "Rocket League não apareceu na biblioteca.")
        for issue in snapshot.issues:
            if "Rocket" in issue.category or "rocket" in issue.title.lower():
                chunks.append(f"{issue.title}. Causa: {issue.cause} Melhora esperada: {issue.impact}")
    if any(token in folded for token in ("cpu", "processador", "xeon", "fps", "quadro")):
        chunks.append(analysis.bottleneck)
    if any(token in folded for token in ("hd", "ssd", "disco", "trav")):
        for issue in snapshot.issues:
            if issue.category in {"Disco", "CS2"} and "HD" in issue.title.upper() or "disco" in issue.title.lower() or "HD" in issue.title:
                chunks.append(f"{issue.title}. {issue.cause} {issue.impact}")
    if any(token in folded for token in ("vsync", "input", "atraso", "latência", "latencia", "mouse")):
        for issue in snapshot.issues:
            if any(token in (issue.title + issue.cause).lower() for token in ("vsync", "mouse", "atraso", "quadro")):
                chunks.append(f"{issue.title}. {issue.impact}")
    if any(token in folded for token in ("internet", "ping", "rede", "wifi", "wi-fi")):
        for probe in snapshot.network:
            chunks.append(
                f"{probe.get('label')}: {probe.get('avg_ms')} ms, perda {probe.get('loss_percent')}%."
            )
    if not chunks:
        chunks.append(analysis.headline)
        chunks.append(analysis.bottleneck)
        chunks.append(analysis.limits)
    # A pergunta pode casar vários blocos. Tira repetidos mantendo a ordem.
    unique = []
    for chunk in chunks:
        if chunk and chunk not in unique:
            unique.append(chunk)
    return "\n\n".join(unique[:8])
