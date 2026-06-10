"""RUN: tek komutluk orkestrator. export -> (LEAN | stub) -> compare -> parite raporu.

  python -m lean_oracle.run --window 90d --symbols TOP10 [--strategy AD]
                            [--mode stub|lean] [--online]

mode=stub (varsayilan): Docker gerektirmez; stub LEAN istatistigi ile boru hatti
  uctan uca calistirir.
mode=lean: gercek LEAN backtest. lean CLI (izole venv) + Docker GEREKIR. Bu fonksiyon
  tam otomatiktir: workspace'i (lean.json) gerekirse 'lean init' ile kurar, projeyi
  workspace'e yerlestirir, backtest'i kosar, sonucu compare'e verir. Docker yoksa net hata.
"""
import argparse
import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

from . import compare, export
from ._stub import generate as generate_stub

BASE = Path(__file__).resolve().parent
ALGO_SRC = BASE / "algorithm"
WORKSPACE = BASE / "lean_workspace"
PROJECT = WORKSPACE / "oracle_algo"
_DOCKER_BIN = r"C:\Program Files\Docker\Docker\resources\bin"
_LEAN_EXES = [BASE / ".venv" / "Scripts" / "lean.exe", BASE / ".venv" / "bin" / "lean"]


def _lean_exe() -> str | None:
    for p in _LEAN_EXES:
        if p.exists():
            return str(p)
    return shutil.which("lean")


def _docker_exe() -> str | None:
    found = shutil.which("docker")
    if found:
        return found
    p = Path(_DOCKER_BIN) / "docker.exe"
    return str(p) if p.exists() else None


def _subenv() -> dict:
    env = dict(os.environ)
    if Path(_DOCKER_BIN).exists():
        env["PATH"] = _DOCKER_BIN + os.pathsep + env.get("PATH", "")
    return env


def _docker_ok() -> bool:
    exe = _docker_exe()
    if not exe:
        return False
    try:
        return subprocess.run([exe, "info"], capture_output=True, timeout=15, env=_subenv()).returncode == 0
    except Exception:
        return False


def _ensure_workspace(lean: str) -> None:
    if (WORKSPACE / "lean.json").exists():
        return
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    print("      workspace kuruluyor (lean init)...")
    r = subprocess.run([lean, "init", "-l", "python"], cwd=str(WORKSPACE), env=_subenv(),
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)
    if not (WORKSPACE / "lean.json").exists():
        raise SystemExit(
            "lean init basarisiz. QC girisi gerekebilir:\n"
            f"  {lean} login\n" + (r.stderr or r.stdout or "")[-500:]
        )


def _prepare_project(export_dir: Path) -> None:
    PROJECT.mkdir(parents=True, exist_ok=True)
    shutil.copy(ALGO_SRC / "main.py", PROJECT / "main.py")
    shutil.copy(ALGO_SRC / "config.json", PROJECT / "config.json")
    inp = PROJECT / "oracle_input"
    if inp.exists():
        shutil.rmtree(inp)
    inp.mkdir(parents=True)
    shutil.copy(export_dir / "signals.json", inp / "signals.json")
    shutil.copy(export_dir / "config.json", inp / "config.json")
    shutil.copytree(export_dir / "data", inp / "data")


def _find_lean_result() -> Path | None:
    bt = PROJECT / "backtests"
    if not bt.exists():
        return None
    for c in sorted(bt.glob("*/*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if c.name.split(".")[0].isdigit() and "order-events" not in c.name:
            try:
                data = json.loads(c.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict) and ("statistics" in data or "Statistics" in data):
                return c
    return None


def _run_lean(export_dir: Path) -> dict:
    lean = _lean_exe()
    if not lean:
        raise SystemExit("lean CLI yok. Kur: pip install -r tools/lean_oracle/requirements.txt "
                         "(izole venv: tools/lean_oracle/.venv)")
    if not _docker_ok():
        raise SystemExit("Docker calismiyor. Docker Desktop kur/baslat ya da --mode stub kullan.")
    _ensure_workspace(lean)
    _prepare_project(export_dir)
    print("      lean backtest calisiyor (ilk seferde motor imaji cekilir)...")
    subprocess.run([lean, "backtest", "oracle_algo"], cwd=str(WORKSPACE), env=_subenv(), check=True)
    result = _find_lean_result()
    if not result:
        raise SystemExit("LEAN sonuc JSON'u bulunamadi.")
    return compare.load_lean_statistics(result)


def _top_strategy_names(n: int) -> list[str]:
    """Leaderboard sirasi (calmar DESC, junk gizli, yil filtreli) ilk N benzersiz strateji adi."""
    from app.db.database import query_all
    rows = query_all(
        """
        SELECT strategy_name, MAX(calmar) AS c
        FROM optimizer_results
        WHERE backtest_days >= 365 AND max_drawdown > 0 AND trades >= 20
        GROUP BY strategy_name
        ORDER BY c DESC
        LIMIT ?
        """,
        (n,),
    )
    return [r["strategy_name"] for r in rows]


def _run_one(window, symbols, exec_tf, name, mode):
    export_dir = asyncio.run(export.run_export(window, symbols, name, exec_tf, offline=True))
    if mode == "lean":
        stats = _run_lean(export_dir)
        source = "lean"
    else:
        stub = json.loads(generate_stub(export_dir).read_text())
        stats = stub["statistics"]
        source = "stub"
    compare.run_compare(export_dir, stats, source)
    return export_dir


def _batch(window, symbols, exec_tf, mode, n):
    names = _top_strategy_names(n)
    print(f"=== BATCH: {len(names)} strateji {mode.upper()} ile dogrulanacak (window={window}, symbols={symbols}) ===", flush=True)
    ok = skip = err = 0
    for i, name in enumerate(names, 1):
        try:
            _run_one(window, symbols, exec_tf, name, mode)
            ok += 1
            print(f"[{i}/{len(names)}] {name}: OK", flush=True)
        except SystemExit as e:
            skip += 1
            print(f"[{i}/{len(names)}] {name}: ATLANDI ({e})", flush=True)
        except Exception as e:  # noqa: BLE001
            err += 1
            print(f"[{i}/{len(names)}] {name}: HATA {type(e).__name__}: {e}", flush=True)
    print(f"=== BATCH BITTI: {ok} OK, {skip} atlandi, {err} hata ===", flush=True)


def main():
    ap = argparse.ArgumentParser(description="LEAN oracle: export -> LEAN/stub -> compare")
    ap.add_argument("--window", default="90d")
    ap.add_argument("--symbols", default="TOP10")
    ap.add_argument("--strategy", default=None)
    ap.add_argument("--exec-tf", default="5")
    ap.add_argument("--mode", default="stub", choices=["stub", "lean"])
    ap.add_argument("--top", type=int, default=0, help="ilk N stratejiyi otomatik dogrula (batch)")
    ap.add_argument("--online", action="store_true")
    args = ap.parse_args()

    if args.top and args.top > 0:
        _batch(args.window, args.symbols, args.exec_tf, args.mode, args.top)
        return

    print(f"[1/3] EXPORT  window={args.window} symbols={args.symbols} strategy={args.strategy or 'auto'}")
    export_dir = asyncio.run(export.run_export(args.window, args.symbols, args.strategy,
                                               args.exec_tf, offline=not args.online))
    manifest = json.loads((export_dir / "manifest.json").read_text())
    print(f"      -> {export_dir.name}  ({manifest['signalCount']} sinyal, "
          f"{len(manifest['tradedSymbols'])} sembol)")

    if args.mode == "lean":
        print("[2/3] LEAN   (gercek motor)")
        stats = _run_lean(export_dir)
        source = "lean"
    else:
        print("[2/3] STUB   (Docker yok -> boru hatti dogrulamasi)")
        stub = json.loads(generate_stub(export_dir).read_text())
        stats = stub["statistics"]
        source = "stub"

    print("[3/3] COMPARE")
    report = compare.run_compare(export_dir, stats, source)
    print(f"\nParite raporu: {report}\n")
    print(report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
