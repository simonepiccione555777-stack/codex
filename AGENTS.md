# Project Agent Rules

This repository is a paper-trading crypto research lab for Bybit public market data.

## Boundaries

- Keep all crypto trading work separate from Flux-related files.
- Do not edit, stage, or commit `FLUXLAB_LAUNCH_KIT.md` or `fluxlab-site/` unless the user explicitly asks for Flux work.
- Do not commit generated reports under `runs/`, paper state under `paper_state/`, downloaded CSVs under `data/`, or generated dashboards.
- Never add API keys, exchange secrets, account identifiers, or real-order execution without an explicit user request.
- Treat the current system as paper trading only. By default, use public Bybit market data and local simulated state.

## Trading Safety

- Do not present backtest performance as a guarantee.
- Report drawdown, trade count, win rate, and profit factor alongside return.
- Prefer changes that improve robustness across multiple periods over changes that only maximize one short window.
- Keep high-leverage behavior behind paper-trading assumptions unless the user explicitly changes the scope.

## Development Workflow

- Use `rg` for search.
- Keep edits scoped to the crypto project.
- Run `python -m py_compile crypto_lab.py bybit_public.py download_bybit_csv.py paper_bybit.py backtest_bybit_paper.py dashboard.py sweep_bybit_params.py` after Python changes.
- If practical, run a short backtest or paper step after strategy changes.
- Before commits, check `git status --short` and stage only crypto project files relevant to the task.
