from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PYTHON_FILES = [
    "crypto_lab.py",
    "bybit_public.py",
    "download_bybit_csv.py",
    "paper_bybit.py",
    "backtest_bybit_paper.py",
    "dashboard.py",
    "sweep_bybit_params.py",
    "agent_healthcheck.py",
]

FORBIDDEN_TRACKED_PREFIXES = ("runs/", "paper_state/", "data/", "fluxlab-site/")
FORBIDDEN_TRACKED_FILES = {"FLUXLAB_LAUNCH_KIT.md", "dashboard.html"}


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, text=True, capture_output=True)


def ok(message: str) -> None:
    print(f"[OK] {message}")


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def check_command(command: list[str], label: str) -> None:
    result = run(command, check=False)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        fail(label)
    ok(label)


def tracked_files() -> list[str]:
    result = run(["git", "ls-files"])
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def git_status() -> list[str]:
    result = run(["git", "status", "--short"])
    return [line.rstrip() for line in result.stdout.splitlines()]


def check_repository_boundaries() -> None:
    tracked = tracked_files()
    forbidden = [
        path for path in tracked if path in FORBIDDEN_TRACKED_FILES or any(path.startswith(prefix) for prefix in FORBIDDEN_TRACKED_PREFIXES)
    ]
    if forbidden:
        fail(f"File da non tracciare presenti in Git: {', '.join(forbidden)}")
    ok("confini repository rispettati")


def check_untracked_boundaries() -> None:
    status = git_status()
    risky = []
    for line in status:
        path = line[3:].replace("\\", "/") if len(line) > 3 else ""
        staged = line[:2] != "??"
        if staged and (path in FORBIDDEN_TRACKED_FILES or any(path.startswith(prefix) for prefix in FORBIDDEN_TRACKED_PREFIXES)):
            risky.append(line)
    if risky:
        fail(f"File vietati in staging/modifica tracciata: {', '.join(risky)}")
    ok("nessun file vietato in staging")


def check_paper_state(path: Path) -> None:
    if not path.exists():
        ok("paper state assente, verra creato al prossimo ciclo")
        return
    state = json.loads(path.read_text(encoding="utf-8"))
    required = {"cash", "positions", "trades", "last_seen", "risk"}
    missing = sorted(required - set(state))
    if missing:
        fail(f"paper state incompleto: {', '.join(missing)}")
    if float(state.get("cash", 0)) < 0:
        fail("paper state con cassa negativa")
    ok("paper state valido")


def check_backtest_report(path: Path) -> None:
    if not path.exists():
        ok("report 6 mesi assente, dashboard lo mostrera come non disponibile")
        return
    report = json.loads(path.read_text(encoding="utf-8"))
    required = {"return_pct", "max_drawdown_pct", "closed_trades", "win_rate_pct", "profit_factor", "trades", "monthly"}
    missing = sorted(required - set(report))
    if missing:
        fail(f"report backtest incompleto: {', '.join(missing)}")
    if int(report.get("closed_trades", 0)) != len(report.get("trades", [])):
        fail("numero trade chiusi non coerente con la lista trade")
    ok("report backtest 6 mesi valido")


def check_dashboard_generation(state: Path, backtest: Path, output: Path) -> None:
    command = [
        sys.executable,
        "dashboard.py",
        "--state",
        str(state),
        "--backtest",
        str(backtest),
        "--output",
        str(output),
    ]
    check_command(command, "dashboard generata")
    html = output.read_text(encoding="utf-8")
    required_text = ["Bybit Paper Dashboard", "Profitto netto", "Backtest 6 Mesi", "Trade Backtest 6 Mesi"]
    missing = [text for text in required_text if text not in html]
    if missing:
        fail(f"dashboard senza sezioni attese: {', '.join(missing)}")
    ok("dashboard contiene sezioni chiave")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Controllo salute locale per il progetto crypto paper trading.")
    parser.add_argument("--state", default="paper_state/bybit_paper.json")
    parser.add_argument("--backtest", default="runs/dashboard_backtest_6m.json")
    parser.add_argument("--dashboard", default="dashboard.html")
    parser.add_argument("--skip-ruff", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.skip_ruff:
        check_command([sys.executable, "-m", "ruff", "check", "."], "ruff lint")
        check_command([sys.executable, "-m", "ruff", "format", "--check", "."], "ruff format")

    check_command([sys.executable, "-m", "py_compile", *PYTHON_FILES], "compilazione Python")
    check_repository_boundaries()
    check_untracked_boundaries()
    check_paper_state(Path(args.state))
    check_backtest_report(Path(args.backtest))
    check_dashboard_generation(Path(args.state), Path(args.backtest), Path(args.dashboard))
    ok("agent healthcheck completato")


if __name__ == "__main__":
    main()
