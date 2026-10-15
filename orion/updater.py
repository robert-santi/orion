"""Atualização pela versão publicada. O usuário não informa endereço."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from orion import __version__
from orion.paths import app_root, data_dir, updates_dir
from orion.store import load_settings
from orion.winutil import CREATE_NO_WINDOW

USER_AGENT = "ORION"
_HTTPS = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com[:/](?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
_SSH = re.compile(
    r"git@github\.com:(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?$",
    re.IGNORECASE,
)
SOURCE_FILES = ("main.py", "requirements.txt", "version.json", "LEIA-ME.txt", "build.ps1")
OFFICIAL_REPO = "https://github.com/robert-santi/orion"
RELEASE_ASSET = "ORION-windows.zip"


@dataclass
class RemoteUpdate:
    ok: bool
    message: str
    sha: str = ""
    kind: str = "error"


@dataclass
class UpdateReport:
    ok: bool
    message: str
    sha: str = ""
    needs_exit: bool = False


def channel(settings: dict | None = None) -> tuple[str, str, str]:
    current = settings if settings is not None else load_settings()
    url = str(current.get("git_url") or "").strip() or OFFICIAL_REPO
    branch = str(current.get("git_branch") or "main").strip() or "main"
    token = str(current.get("git_token") or "").strip()
    return url, branch, token


def _version_parts(text: str) -> tuple[int, ...]:
    cleaned = (text or "").strip()
    if cleaned[:1].lower() == "v":
        cleaned = cleaned[1:]
    numbers: list[int] = []
    for piece in cleaned.split("."):
        digits = ""
        for char in piece:
            if char.isdigit():
                digits += char
            else:
                break
        numbers.append(int(digits) if digits else 0)
    return tuple(numbers)


def version_status(local: str, remote: str) -> str:
    if _version_parts(remote) > _version_parts(local):
        return "new"
    return "same"


def github_repo(url: str) -> tuple[str, str] | None:
    text = (url or "").strip()
    match = _HTTPS.fullmatch(text) or _SSH.fullmatch(text)
    if not match:
        return None
    return match.group("owner"), match.group("repo")


def _state_path() -> Path:
    return data_dir() / "update_state.json"


def stored_sha() -> str:
    path = _state_path()
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("sha") or "")


def remember_sha(sha: str) -> None:
    payload = {"sha": sha, "noted_at": datetime.now().isoformat(timespec="seconds")}
    _state_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def worktree_dirty() -> bool:
    root = app_root()
    if not (root / ".git").exists():
        return False
    git = shutil.which("git")
    if not git:
        return False
    try:
        result = subprocess.run(
            [git, "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool((result.stdout or "").strip())


def _redact(text: str, token: str) -> str:
    if token and text:
        return text.replace(token, "••••")
    return text


def _api(url: str, token: str, timeout: int = 40) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:240]
        raise RuntimeError(f"A consulta respondeu {error.code}. {_redact(detail, token)}") from error


def _git_remote_sha(url: str, branch: str, token: str) -> str:
    git = shutil.which("git")
    if not git:
        raise RuntimeError("Este endereço não é do GitHub e o Git não está instalado neste PC.")
    remote = url
    if token and url.lower().startswith("https://"):
        remote = "https://x-access-token:" + token + "@" + url[8:]
    try:
        result = subprocess.run(
            [git, "ls-remote", remote, branch],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=40,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("Não foi possível consultar o repositório.") from error
    if result.returncode != 0:
        raise RuntimeError(_redact((result.stderr or "Falha ao consultar o Git.").strip(), token)[:300])
    line = (result.stdout or "").strip().splitlines()
    if not line:
        raise RuntimeError("O ramo informado não existe nesse endereço.")
    return line[0].split()[0]


def _latest_release(owner: str, name: str, token: str) -> str:
    payload = json.loads(_api(f"https://api.github.com/repos/{owner}/{name}/releases/latest", token))
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("tag_name") or "").strip()


def look_up() -> RemoteUpdate:
    url, branch, token = channel()
    repo = github_repo(url)
    frozen = bool(getattr(sys, "frozen", False))
    try:
        if frozen:
            if repo is None:
                return RemoteUpdate(False, "A atualização do programa instalado usa a versão publicada.")
            try:
                tag = _latest_release(repo[0], repo[1], token)
            except RuntimeError as error:
                text = _redact(str(error), token)
                if "respondeu 404" in text:
                    return RemoteUpdate(True, "Ainda não há versão publicada.", "", "none")
                return RemoteUpdate(False, text)
            if not tag:
                return RemoteUpdate(True, "Ainda não há versão publicada.", "", "none")
            if version_status(__version__, tag) == "new":
                return RemoteUpdate(True, "Há uma versão nova publicada.", tag, "new")
            return RemoteUpdate(True, "Este PC já está na versão publicada.", tag, "same")
        if repo:
            owner, name = repo
            payload = json.loads(_api(f"https://api.github.com/repos/{owner}/{name}/commits/{branch}", token))
            sha = str(payload.get("sha") or "")
        else:
            sha = _git_remote_sha(url, branch, token)
    except Exception as error:
        return RemoteUpdate(False, _redact(str(error), token))
    if not sha:
        return RemoteUpdate(False, "A versão publicada não devolveu um identificador.")
    current = stored_sha()
    if not current:
        return RemoteUpdate(True, "Primeira leitura da versão publicada.", sha, "first")
    if current == sha:
        return RemoteUpdate(True, "Este PC já está na versão publicada.", sha, "same")
    return RemoteUpdate(True, "Há uma versão nova publicada.", sha, "new")


def _safe_extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            goal = (dest / info.filename).resolve()
            if not goal.is_relative_to(root):
                raise RuntimeError("O pacote de atualização é inválido.")
        bundle.extractall(dest)


def _find_source(root: Path) -> Path | None:
    if (root / "main.py").is_file() and (root / "orion").is_dir():
        return root
    for path in root.rglob("main.py"):
        if (path.parent / "orion").is_dir():
            return path.parent
    return None


def _find_exe(root: Path) -> Path | None:
    matches = [path for path in root.rglob("ORION.exe") if path.is_file()]
    if not matches:
        return None
    matches.sort(key=lambda path: (0 if "dist" in {part.lower() for part in path.parts} else 1, len(path.parts)))
    return matches[0]


def _copy_source(src: Path, dst: Path) -> None:
    for name in SOURCE_FILES:
        item = src / name
        if item.is_file():
            shutil.copy2(item, dst / name)
    orion_src = src / "orion"
    if orion_src.is_dir():
        shutil.copytree(
            orion_src,
            dst / "orion",
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )


def _stage_clean() -> Path:
    stage = updates_dir() / "stage"
    if stage.exists():
        shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    return stage


def _download_release_dir(owner: str, name: str, tag: str, token: str) -> Path:
    safe_tag = quote(tag, safe="")
    payload = json.loads(_api(f"https://api.github.com/repos/{owner}/{name}/releases/tags/{safe_tag}", token))
    assets = payload.get("assets") if isinstance(payload, dict) else None
    asset = None
    if isinstance(assets, list):
        asset = next((item for item in assets if isinstance(item, dict) and item.get("name") == RELEASE_ASSET), None)
    if not isinstance(asset, dict):
        raise RuntimeError("A versão publicada não traz o pacote do programa.")
    url = str(asset.get("browser_download_url") or "")
    if not url:
        raise RuntimeError("A versão publicada não traz o pacote do programa.")
    archive = updates_dir() / "incoming.zip"
    archive.write_bytes(_api(url, token, timeout=300))
    stage = _stage_clean()
    try:
        _safe_extract(archive, stage)
    finally:
        archive.unlink(missing_ok=True)
    return stage


def _download_github_zip(owner: str, name: str, sha: str, token: str, dest: Path) -> None:
    data = _api(f"https://api.github.com/repos/{owner}/{name}/zipball/{sha}", token, timeout=180)
    dest.write_bytes(data)


def _clone(url: str, branch: str, token: str, dest: Path) -> None:
    git = shutil.which("git")
    if not git:
        raise RuntimeError("Este endereço não é do GitHub e o Git não está instalado neste PC.")
    remote = url
    if token and url.lower().startswith("https://"):
        remote = "https://x-access-token:" + token + "@" + url[8:]
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    result = subprocess.run(
        [git, "clone", "--depth", "1", "--branch", branch, remote, str(dest)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        creationflags=CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        raise RuntimeError(_redact((result.stderr or "Falha ao baixar o repositório.").strip(), token)[:300])


def _schedule_exe_swap(source_dir: Path, sha: str) -> None:
    script = updates_dir() / "aplicar.ps1"
    state = _state_path()
    script.write_text(
        "\n".join(
            [
                "param([int]$WaitPid, [string]$Source, [string]$Destination, [string]$Exe, [string]$Sha, [string]$StateFile)",
                "while (Get-Process -Id $WaitPid -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 400 }",
                "& robocopy $Source $Destination /E /XD data /NFL /NDL /NJH /NJS /nc /ns /np",
                "if ($LASTEXITCODE -ge 8) { exit $LASTEXITCODE }",
                "$json = @{ sha = $Sha; noted_at = (Get-Date -Format s) } | ConvertTo-Json -Compress",
                "[System.IO.File]::WriteAllText($StateFile, $json)",
                "Start-Process -FilePath $Exe -WorkingDirectory (Split-Path -Parent $Exe)",
                "exit 0",
            ]
        ),
        encoding="ascii",
    )
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-WaitPid",
            str(os.getpid()),
            "-Source",
            str(source_dir),
            "-Destination",
            str(app_root()),
            "-Exe",
            str(app_root() / "ORION.exe"),
            "-Sha",
            sha,
            "-StateFile",
            str(state),
        ],
        creationflags=CREATE_NO_WINDOW,
    )


def _relaunch_source() -> None:
    subprocess.Popen([sys.executable, str(app_root() / "main.py")], cwd=str(app_root()))


def install(ref: str) -> UpdateReport:
    url, branch, token = channel()
    repo = github_repo(url)
    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        if repo is None:
            return UpdateReport(False, "A atualização do programa instalado usa a versão publicada.")
        try:
            stage = _download_release_dir(repo[0], repo[1], ref, token)
        except Exception as error:
            return UpdateReport(False, _redact(str(error), token))
        exe = _find_exe(stage)
        if exe is None:
            return UpdateReport(False, "O pacote publicado não traz o ORION.exe.", ref)
        _schedule_exe_swap(exe.parent, ref)
        return UpdateReport(True, "A atualização entra assim que o ORION fechar.", ref, True)
    stage = _stage_clean()
    try:
        if repo:
            archive = updates_dir() / "incoming.zip"
            _download_github_zip(repo[0], repo[1], ref, token, archive)
            _safe_extract(archive, stage)
            archive.unlink(missing_ok=True)
        else:
            _clone(url, branch, token, stage / "clone")
    except Exception as error:
        return UpdateReport(False, _redact(str(error), token))
    source = _find_source(stage)
    if source is None:
        return UpdateReport(False, "O pacote não traz o código do programa.", ref)
    _copy_source(source, app_root())
    remember_sha(ref)
    _relaunch_source()
    return UpdateReport(True, "Arquivos atualizados. O programa vai reabrir.", ref, True)
