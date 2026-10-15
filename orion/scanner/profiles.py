"""Classifica jogos e o hardware sem fingir que todo título se comporta igual."""

from __future__ import annotations

HEAVY_NAMES = (
    "hogwarts",
    "cyberpunk",
    "red dead",
    "starfield",
    "alan wake",
    "the last of us",
    "black myth",
    "monster hunter",
    "forza horizon",
    "call of duty",
    "warzone",
    "lost ark",
)
MEDIUM_NAMES = (
    "efootball",
    "e-football",
    "fortnite",
    "valorant",
    "apex",
    "overwatch",
    "combat master",
    "outlast",
    "albion",
    "sims",
    "gta",
    "rust",
    "pubg",
    "destiny",
    "rocket league",
    "counter-strike",
    "minecraft",
    "league of legends",
    "dota",
)
LIGHT_NAMES = (
    "fall guys",
    "unrailed",
    "don't starve",
    "dont starve",
    "goose goose",
    "stardew",
    "among us",
    "vampire survivors",
)

# Redistribuíveis e runtimes que aparecem como "jogo" na Steam.
STEAM_TOOLS = {
    "228980",
    "1070560",
    "1113280",
    "1391110",
    "1628350",
    "1826330",
    "1493710",
    "1580130",
}


def profile_for(name: str, app_id: str) -> str:
    folded = name.lower()
    if app_id in {"730", "240", "4465480"} or "counter-strike" in folded:
        return "cs2"
    if app_id == "252950" or "rocket league" in folded:
        return "rocket_league"
    if any(token in folded for token in HEAVY_NAMES):
        return "heavy"
    if any(token in folded for token in LIGHT_NAMES):
        return "light"
    if any(token in folded for token in MEDIUM_NAMES):
        return "medium"
    return "generic"


def is_steam_tool(app_id: str, name: str) -> bool:
    folded = name.lower()
    if app_id in STEAM_TOOLS:
        return True
    return "redistributable" in folded or "steamworks common" in folded


def weak_cpu(name: str, max_mhz: float) -> bool:
    folded = name.lower()
    if "xeon" in folded and (not max_mhz or max_mhz < 3600):
        return True
    old_tokens = (
        "celeron",
        "pentium",
        "athlon",
        "a4-",
        "a6-",
        "a8-",
        "i3-2",
        "i3-4",
        "i5-2",
        "i5-3",
        "i7-2",
        "i7-3",
    )
    return bool(max_mhz and max_mhz < 3200 and any(token in folded for token in old_tokens))


def gpu_tier(name: str) -> str:
    folded = name.lower()
    if any(token in folded for token in ("uhd", "iris", "hd graphics", "vega 3", "vega 8", "vega 11", "radeon(tm) graphics")):
        return "fraca"
    strong = (
        "4090",
        "4080",
        "4070",
        "3090",
        "3080",
        "3070",
        "7900",
        "7800",
        "6950",
        "6900",
        "6800",
        "9070",
        "5080",
        "5070",
        "4080",
    )
    mid = (
        "4060",
        "4050",
        "3060",
        "3050",
        "2080",
        "2070",
        "2060",
        "1080",
        "1070",
        "6700",
        "6600",
        "5700",
        "7600",
        "7700",
        "6800",
        "rx 6700",
        "rx 6600",
    )
    entry = (
        "rx 580",
        "rx 570",
        "rx 480",
        "rx 470",
        "rx 590",
        "gtx 1650",
        "gtx 1660",
        "gtx 1060",
        "gtx 1050",
        "gtx 970",
        "gtx 960",
        "5500",
        "6500",
        "6400",
        "1630",
        "mx150",
        "mx250",
        "mx350",
        "mx450",
    )
    if any(token in folded for token in strong):
        return "forte"
    if any(token in folded for token in mid):
        return "intermediaria"
    if any(token in folded for token in entry):
        return "entrada"
    if "nvidia" in folded or "geforce" in folded or "radeon" in folded or "arc a" in folded:
        return "intermediaria"
    return "desconhecida"


def gpu_vendor(name: str) -> str:
    folded = name.lower()
    if "nvidia" in folded or "geforce" in folded:
        return "nvidia"
    if "amd" in folded or "radeon" in folded:
        return "amd"
    if "intel" in folded or "arc" in folded:
        return "intel"
    return "outro"


def polars_or_old_amd(name: str) -> bool:
    folded = name.lower()
    return any(token in folded for token in ("rx 580", "rx 570", "rx 480", "rx 470", "rx 590", "rx 560", "rx 550"))
