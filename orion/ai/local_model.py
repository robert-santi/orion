"""Arquivo público e binário oficial, baixados para data\\. A tela não espera por isso."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import urllib.request
import zipfile
from pathlib import Path

from orion.paths import models_dir, tools_dir
from orion.winutil import CREATE_NO_WINDOW

log = logging.getLogger("orion")

MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/"
    "qwen2.5-0.5b-instruct-q4_k_m.gguf"
)
MODEL_NAME = "qwen2.5-0.5b-instruct-q4_k_m.gguf"
MODEL_BYTES = 491_400_032
MIN_MODEL_BYTES = 450_000_000
MIN_FREE_BYTES = 2 * 1024 ** 3
RELEASES_URL = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=8"
USER_AGENT = "ORION"

_LOCK = threading.Lock()
_HELP = ""


def _skip() -> bool:
    return os.environ.get("ORION_SKIP_MODEL") == "1"


def _free_bytes() -> int:
    return shutil.disk_usage(models_dir()).free


def _model_path() -> Path:
    return models_dir() / MODEL_NAME


def _runtime_dir() -> Path:
    return tools_dir() / "llama"


def _find_exe() -> Path | None:
    root = _runtime_dir()
    if not root.is_dir():
        return None
    found = {path.name.lower(): path for path in root.rglob("*.exe")}
    for name in ("llama-completion.exe", "llama-cli.exe"):
        if name in found:
            return found[name]
    return None


def ready() -> bool:
    exe = _find_exe()
    path = _model_path()
    return exe is not None and path.is_file() and path.stat().st_size >= MIN_MODEL_BYTES


def _request(url: str, timeout: int = 60) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT})


def _download(url: str, dest: Path, timeout: int = 120) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    if partial.exists():
        partial.unlink(missing_ok=True)
    with urllib.request.urlopen(_request(url), timeout=timeout) as response, partial.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            handle.write(chunk)
    partial.replace(dest)


def _runtime_zip_url() -> str:
    with urllib.request.urlopen(_request(RELEASES_URL), timeout=30) as response:
        releases = json.loads(response.read().decode("utf-8"))
    for release in releases:
        for asset in release.get("assets") or []:
            name = str(asset.get("name") or "").lower()
            if name.endswith(".zip") and "win-cpu-x64" in name and "arm" not in name:
                return str(asset["browser_download_url"])
    raise RuntimeError("binário público não encontrado")


def _extract_runtime(archive: Path) -> None:
    target = _runtime_dir()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        root = target.resolve()
        for info in bundle.infolist():
            goal = (target / info.filename).resolve()
            if not goal.is_relative_to(root):
                raise RuntimeError("pacote do runtime inválido")
        bundle.extractall(target)


def ensure_runtime() -> bool:
    if _find_exe() is not None:
        return True
    if _free_bytes() < MIN_FREE_BYTES:
        log.info("espaço insuficiente para o componente interno")
        return False
    archive = tools_dir() / "llama-cpu.zip"
    url = _runtime_zip_url()
    log.info("baixando runtime interno")
    _download(url, archive, timeout=180)
    _extract_runtime(archive)
    archive.unlink(missing_ok=True)
    return _find_exe() is not None


def ensure_weights() -> bool:
    path = _model_path()
    if path.is_file() and path.stat().st_size >= MIN_MODEL_BYTES:
        return True
    if path.is_file():
        path.unlink(missing_ok=True)
    if _free_bytes() < MIN_FREE_BYTES:
        log.info("espaço insuficiente para o arquivo interno")
        return False
    log.info("baixando arquivo interno")
    _download(MODEL_URL, path, timeout=600)
    if path.stat().st_size < MIN_MODEL_BYTES:
        path.unlink(missing_ok=True)
        log.info("arquivo interno incompleto")
        return False
    return True


def ensure() -> bool:
    if _skip():
        return ready()
    with _LOCK:
        try:
            if not ensure_runtime():
                return False
            if not ensure_weights():
                return False
        except Exception:
            log.exception("componente interno")
            return False
        return ready()


def _help_text(exe: Path) -> str:
    global _HELP
    if _HELP:
        return _HELP
    try:
        result = subprocess.run(
            [str(exe), "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        _HELP = ((result.stdout or "") + "\n" + (result.stderr or "")).lower()
    except (OSError, subprocess.TimeoutExpired):
        _HELP = ""
    return _HELP


def _args(exe: Path, model: Path, prompt: str) -> list[str]:
    help_text = _help_text(exe)
    # Nesta versão -c é máscara de CPU e também contexto. Use o nome longo.
    args = [
        str(exe),
        "-m",
        str(model),
        "--ctx-size",
        "1024",
        "--threads",
        "4",
        "--temp",
        "0",
        "--predict",
        "160",
        "-p",
        prompt,
    ]
    if "--no-escape" in help_text:
        args.append("--no-escape")
    if "--no-display-prompt" in help_text:
        args.append("--no-display-prompt")
    if "-no-cnv" in help_text:
        args.append("-no-cnv")
    elif "--no-conversation" in help_text:
        args.append("--no-conversation")
    if "--simple-io" in help_text:
        args.append("--simple-io")
    if "--gpu-layers" in help_text:
        args.extend(["--gpu-layers", "0"])
    if "--no-warmup" in help_text:
        args.append("--no-warmup")
    return args


def complete(prompt: str, timeout: int = 45) -> str:
    if _skip() or not ready():
        return ""
    exe = _find_exe()
    if exe is None:
        return ""
    wrapped = (
        "<|im_start|>system\n"
        "Responda apenas com um objeto JSON.<|im_end|>\n"
        "<|im_start|>user\n"
        f"{prompt}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )
    try:
        result = subprocess.run(
            _args(exe, _model_path(), wrapped),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        log.info("complemento interno demorou ou falhou")
        return ""
    return (result.stdout or "").strip()
