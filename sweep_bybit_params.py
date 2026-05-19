from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from types import SimpleNamespace

from backtest_bybit_paper import apply_profile, run_backtest


def base_args(args: argparse.Namespace) -> SimpleNamespace:
    namespace = SimpleNamespace(
        profile="moonshot",
        allow_short=args.allow_short,
        symbols=args.symbols,
        category=args.category,
        interval=args.interval,
        start=args.start,
        end=args.end,
        capital=args.capital,
        lookback=200,
        risk=0.02,
        max_open_risk=0.10,
        max_equity_drawdown=0.35,
        drawdown_cooldown_hours=24,
        max_daily_loss=0.18,
        daily_loss_cooldown_hours=24,
        correlated_risk_multiplier=0.5,
        stop_cooldown_after=2,
        cooldown_hours=24,
        leverage=2.0,
        adaptive_leverage=True,
        min_leverage=2.0,
        max_leverage=70.0,
        low_volatility=0.006,
        high_volatility=0.025,
        strong_trend_gap=0.01,
        high_leverage_threshold=25.0,
        high_leverage_max_risk=0.05,
        max_symbol_allocation=0.45,
        fee=0.001,
        slippage=0.0005,
        fast_ema=12,
        slow_ema=48,
        rsi_period=14,
        atr_period=14,
        min_rsi=50,
        max_rsi=72,
        short_min_rsi=28,
        short_max_rsi=50,
        short_breakdown_lookback=24,
        volume_lookback=24,
        short_volume_multiplier=1.15,
        short_max_close_position=0.60,
        short_risk_multiplier=0.45,
        short_correlated_risk_multiplier=0.25,
        short_max_risk=0.025,
        short_max_leverage=25.0,
        stop_atr=2.0,
        take_profit_atr=4.0,
        trailing_stop=False,
        trailing_activation_atr=2.0,
        trailing_distance_atr=1.5,
        regime_filter=False,
        regime_symbol="BTCUSDT",
        regime_interval="240",
        regime_lookback=260,
        regime_fast_ema=50,
        regime_slow_ema=200,
        output="",
    )
    return apply_profile(namespace)


def score_result(result: dict) -> float:
    profit_factor = result["profit_factor"] or 0.0
    trade_penalty = 12 - result["closed_trades"] if result["closed_trades"] < 12 else 0
    return result["return_pct"] - (result["max_drawdown_pct"] * 1.25) + (profit_factor * 3) - (trade_penalty * 2)


def run_sweep(args: argparse.Namespace) -> list[dict]:
    fast_slow_pairs = [(20, 100), (30, 120), (40, 160)]
    if args.deep or args.wide:
        stop_take_pairs = [(1.3, 4.0), (1.5, 4.5), (1.8, 5.0)]
        daily_losses = [0.10, 0.14, 0.18] if args.deep else [0.10, 0.14]
        max_drawdowns = [0.22, 0.25, 0.30] if args.deep else [0.25]
    else:
        stop_take_pairs = [(1.5, 4.5)]
        daily_losses = [0.10, 0.14]
        max_drawdowns = [0.25]
    combinations = itertools.product(fast_slow_pairs, stop_take_pairs, daily_losses, max_drawdowns)

    rows: list[dict] = []
    for (fast, slow), (stop_atr, take_profit_atr), max_daily_loss, max_equity_drawdown in combinations:
        candidate = base_args(args)
        candidate.regime_fast_ema = fast
        candidate.regime_slow_ema = slow
        candidate.stop_atr = stop_atr
        candidate.take_profit_atr = take_profit_atr
        candidate.max_daily_loss = max_daily_loss
        candidate.max_equity_drawdown = max_equity_drawdown

        result = run_backtest(candidate)
        rows.append(
            {
                "score": round(score_result(result), 4),
                "return_pct": round(result["return_pct"], 4),
                "max_drawdown_pct": round(result["max_drawdown_pct"], 4),
                "profit_factor": None if result["profit_factor"] is None else round(result["profit_factor"], 4),
                "closed_trades": result["closed_trades"],
                "win_rate_pct": round(result["win_rate_pct"], 4),
                "regime_fast_ema": fast,
                "regime_slow_ema": slow,
                "stop_atr": stop_atr,
                "take_profit_atr": take_profit_atr,
                "max_daily_loss": max_daily_loss,
                "max_equity_drawdown": max_equity_drawdown,
                "monthly": result["monthly"],
                "by_side": result["by_side"],
            }
        )

    return sorted(rows, key=lambda row: row["score"], reverse=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Piccola ricerca parametri per la strategia Bybit paper.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--category", default="spot", choices=["spot", "linear", "inverse"])
    parser.add_argument("--interval", default="60")
    parser.add_argument("--capital", type=float, default=100.0)
    parser.add_argument("--allow-short", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--wide", action="store_true", help="Prova 18 combinazioni invece delle 6 rapide.")
    parser.add_argument("--deep", action="store_true", help="Prova piu' combinazioni, ma richiede piu' tempo.")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = run_sweep(args)

    print("=== Bybit Moonshot Parameter Sweep ===")
    print(f"Periodo: {args.start} -> {args.end}")
    print(f"Combinazioni testate: {len(rows)}")
    print("")
    print("Top risultati bilanciati:")
    for index, row in enumerate(rows[: args.top], start=1):
        print(
            f"{index}. score={row['score']:.2f} return={row['return_pct']:.2f}% "
            f"dd={row['max_drawdown_pct']:.2f}% pf={row['profit_factor']} "
            f"trades={row['closed_trades']} regime={row['regime_fast_ema']}/{row['regime_slow_ema']} "
            f"ATR={row['stop_atr']}/{row['take_profit_atr']} daily_loss={row['max_daily_loss']:.2f} "
            f"max_dd_guard={row['max_equity_drawdown']:.2f}"
        )

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nReport JSON: {output}")


if __name__ == "__main__":
    main()
