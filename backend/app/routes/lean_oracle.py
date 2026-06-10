"""LEAN oracle parite raporlarini UI'a sunan SALT-OKUNUR route.

tools/lean_oracle/oracle_export/ altindaki uretilmis raporlari okur. DB'ye, canli
trading'e, LEAN motoruna DOKUNMAZ; yalnizca dosya okur.
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from tools.lean_oracle.export import parse_symbols_arg, parse_window_days

router = APIRouter()

# subprocess argparse parametre dogrulamasi (lider '-' yok -> opsiyon karismasi yok)
_ARG_OK = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,80}")

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_EXPORT_ROOT = _BACKEND_ROOT / "tools" / "lean_oracle" / "oracle_export"
_LEAN_VENV = _BACKEND_ROOT / "tools" / "lean_oracle" / ".venv" / "Scripts" / "lean.exe"
_DOCKER_CANDIDATES = [
    r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
    "/usr/bin/docker",
    "/usr/local/bin/docker",
]


def _docker_cli() -> str | None:
    found = shutil.which("docker")
    if found:
        return found
    for c in _DOCKER_CANDIDATES:
        if Path(c).exists():
            return c
    return None


def _docker_ready() -> bool:
    """Docker daemon gercekten ayakta mi? (PATH'ten bagimsiz, bilinen yolu da dener)."""
    exe = _docker_cli()
    if not exe:
        return False
    try:
        return subprocess.run([exe, "info"], capture_output=True, timeout=6).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _run_dirs() -> list[Path]:
    if not _EXPORT_ROOT.exists():
        return []
    dirs = [d for d in _EXPORT_ROOT.iterdir() if d.is_dir() and (d / "manifest.json").exists()]
    return sorted(dirs, key=lambda d: d.stat().st_mtime, reverse=True)


@router.get("/status")
async def status():
    runs = _run_dirs()
    docker_ready = await asyncio.to_thread(_docker_ready)
    return {
        "dockerAvailable": docker_ready,
        "dockerInstalled": _docker_cli() is not None,
        "leanInstalled": _LEAN_VENV.exists() or shutil.which("lean") is not None,
        "runCount": len(runs),
        "latestRun": runs[0].name if runs else None,
        "exportRootExists": _EXPORT_ROOT.exists(),
    }


@router.get("/runs")
async def runs():
    out = []
    for d in _run_dirs():
        manifest = _read_json(d / "manifest.json") or {}
        out.append({
            "runId": d.name,
            "strategy": manifest.get("strategy"),
            "window": manifest.get("window"),
            "execTf": manifest.get("execTf"),
            "signalCount": manifest.get("signalCount"),
            "tradedSymbols": manifest.get("tradedSymbols", []),
            "summary": manifest.get("myMetricsSummary", {}),
            "hasReport": (d / "parity_report.json").exists(),
        })
    return {"runs": out}


@router.get("/report")
async def report(run: str | None = None):
    dirs = _run_dirs()
    if not dirs:
        return {"empty": True, "reason": "no_runs"}
    target = None
    if run:
        target = next((d for d in dirs if d.name == run), None)
        if target is None:
            return {"empty": True, "reason": "run_not_found"}
    else:
        target = next((d for d in dirs if (d / "parity_report.json").exists()), dirs[0])

    report_json = _read_json(target / "parity_report.json")
    manifest = _read_json(target / "manifest.json") or {}
    if not report_json:
        return {"empty": True, "reason": "no_report", "runId": target.name, "manifest": manifest}
    return {
        "empty": False,
        "runId": target.name,
        "meta": report_json.get("meta", {}),
        "rows": report_json.get("rows", []),
        "manifest": manifest,
        "markdown": _read_text(target / "parity_report.md"),
    }


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return None


# ---- Tek-is calistirici: UI'dan bir strateji icin LEAN parite kosumu tetikler ----
_JOB: dict = {"running": False, "strategy": None, "mode": None, "done": False, "error": None, "log": ""}
_JOB_LOCK = threading.Lock()


def _run_job(strategy: str, window: str, symbols: str) -> None:
    try:
        mode = "lean" if _docker_ready() else "stub"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(_BACKEND_ROOT / "tools") + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONIOENCODING"] = "utf-8"
        docker = _docker_cli()
        if docker:
            env["PATH"] = str(Path(docker).parent) + os.pathsep + env.get("PATH", "")
        with _JOB_LOCK:
            _JOB["mode"] = mode
        proc = subprocess.run(
            [sys.executable, "-m", "lean_oracle.run", "--strategy", strategy,
             "--mode", mode, "--window", window, "--symbols", symbols],
            cwd=str(_BACKEND_ROOT), env=env, capture_output=True, text=True, timeout=600,
        )
        tail = ((proc.stdout or "")[-1500:] + (proc.stderr or "")[-1500:]).strip()
        with _JOB_LOCK:
            _JOB["log"] = tail
            _JOB["error"] = None if proc.returncode == 0 else f"exit {proc.returncode}"
            _JOB["done"] = True
            _JOB["running"] = False
    except Exception as err:  # noqa: BLE001
        with _JOB_LOCK:
            _JOB["error"] = str(err)
            _JOB["done"] = True
            _JOB["running"] = False


@router.post("/run")
async def run_oracle(request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    strategy = (body or {}).get("strategy")
    if not isinstance(strategy, str) or not strategy.strip():
        return JSONResponse(status_code=400, content={"error": "strategy gerekli"})
    strategy = strategy.strip()
    window = (body or {}).get("window") or "90d"
    symbols = (body or {}).get("symbols") or "TOP10"
    # subprocess argparse'a gidiyor: '-' ile baslayan veya beklenmedik karakter iceren
    # degerler opsiyon karismasi yaratmasin (kabuk yok -> komut enjeksiyonu degil, saglamlik).
    if not _ARG_OK.fullmatch(strategy):
        return JSONResponse(status_code=400, content={"error": "gecersiz strategy"})
    try:
        parse_window_days(str(window))
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "gecersiz window (orn. 90d)"})
    try:
        parse_symbols_arg(str(symbols))
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "gecersiz symbols (TOP10 veya ALL)"})
    with _JOB_LOCK:
        if _JOB["running"]:
            return JSONResponse(status_code=409, content={"started": False, "reason": "busy", "current": _JOB["strategy"]})
        _JOB.update({"running": True, "strategy": strategy, "mode": None, "done": False, "error": None, "log": ""})
    threading.Thread(target=_run_job, args=(strategy, window, symbols), daemon=True).start()
    return {"started": True, "strategy": strategy}


@router.get("/run-status")
async def run_status():
    with _JOB_LOCK:
        return dict(_JOB)
