from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from bybit_public import fetch_historical_klines
from paper_bybit import (
    PaperPosition,
    choose_leverage,
    classify_regime,
    close_position,
    default_state,
    in_cooldown,
    latest_signal,
    portfolio_value,
    update_trailing_stop,
)


def run_symbol_step(state: dict, symbol: str, history: list, candle, args: argparse.Namespace, regime: dict | None = None) -> str | None:
    signal, info = latest_signal(history, args)
    timestamp = info["timestamp"]
    price = info["close"]
    atr_value = info["atr"]
    state["last_seen"][symbol] = timestamp
    risk_state = state.setdefault("risk", {"consecutive_stops": 0})

    raw_position = state["positions"].get(symbol)
    if raw_position:
        position = PaperPosition(**raw_position)
        position = update_trailing_stop(position, price, atr_value, args)
        state["positions"][symbol] = asdict(position)
        if position.side == "LONG" and candle.low <= position.stop:
            close_position(state, position, position.stop, timestamp, "stop", args)
            return f"{timestamp} {symbol} LONG STOP {position.stop:.4f}"
        if position.side == "LONG" and candle.high >= position.take_profit:
            close_position(state, position, position.take_profit, timestamp, "take_profit", args)
            return f"{timestamp} {symbol} LONG TAKE_PROFIT {position.take_profit:.4f}"
        if position.side == "SHORT" and candle.high >= position.stop:
            close_position(state, position, position.stop, timestamp, "stop", args)
            return f"{timestamp} {symbol} SHORT STOP {position.stop:.4f}"
        if position.side == "SHORT" and candle.low <= position.take_profit:
            close_position(state, position, position.take_profit, timestamp, "take_profit", args)
            return f"{timestamp} {symbol} SHORT TAKE_PROFIT {position.take_profit:.4f}"
        if position.side == "LONG" and info["fast"] is not None and info["slow"] is not None and info["fast"] < info["slow"]:
            close_position(state, position, price, timestamp, "trend_exit", args)
            return f"{timestamp} {symbol} LONG TREND_EXIT {price:.4f}"
        if position.side == "SHORT" and info["fast"] is not None and info["slow"] is not None and info["fast"] > info["slow"]:
            close_position(state, position, price, timestamp, "trend_exit", args)
            return f"{timestamp} {symbol} SHORT TREND_EXIT {price:.4f}"
        return None

    if signal not in {"BUY", "SHORT"} or atr_value is None:
        return None

    if in_cooldown(risk_state, timestamp):
        return None

    current_open_risk = sum(float(position.get("risk_fraction", 0)) for position in state.get("positions", {}).values())
    if current_open_risk >= args.max_open_risk:
        return None

    side = "LONG" if signal == "BUY" else "SHORT"
    regime = regime or {"name": "OFF", "long_allowed": True, "short_allowed": True}
    if side == "LONG" and not regime["long_allowed"]:
        return None
    if side == "SHORT" and not regime["short_allowed"]:
        return None

    leverage = choose_leverage(info, args, side)
    effective_risk = min(args.risk, args.max_open_risk - current_open_risk)
    correlated_count = sum(1 for open_symbol in state.get("positions", {}) if open_symbol.endswith(symbol[-4:]))
    if side == "SHORT":
        leverage = min(leverage, args.short_max_leverage)
        effective_risk *= args.short_risk_multiplier
        effective_risk = min(effective_risk, args.short_max_risk)
        if correlated_count > 0:
            effective_risk *= args.short_correlated_risk_multiplier
    elif correlated_count > 0:
        effective_risk *= args.correlated_risk_multiplier
    if leverage >= args.high_leverage_threshold:
        effective_risk = min(effective_risk, args.high_leverage_max_risk)

    available_margin = state["cash"] * args.max_symbol_allocation
    available_notional = available_margin * leverage
    risk_amount = state["cash"] * effective_risk
    stop_distance = atr_value * args.stop_atr
    quantity = min(risk_amount / stop_distance, available_notional / price) if stop_distance > 0 else 0
    entry = price * (1 + args.slippage) if side == "LONG" else price * (1 - args.slippage)
    notional = quantity * entry
    margin = notional / leverage
    fee = notional * args.fee

    if quantity <= 0 or margin + fee > state["cash"]:
        return None

    state["cash"] -= margin + fee
    state["positions"][symbol] = asdict(
        PaperPosition(
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry=entry,
            stop=entry - stop_distance if side == "LONG" else entry + stop_distance,
            take_profit=entry + atr_value * args.take_profit_atr if side == "LONG" else entry - atr_value * args.take_profit_atr,
            margin=margin,
            leverage=leverage,
            opened_at=timestamp,
            risk_fraction=effective_risk,
            best_price=entry,
        )
    )
    return f"{timestamp} {symbol} OPEN_{side} {leverage:.1f}x entry={entry:.4f} margin={margin:.2f}"


def regime_at(timestamp: str, regime_candles: list, args: argparse.Namespace) -> dict:
    if not args.regime_filter:
        return {"name": "OFF", "long_allowed": True, "short_allowed": True}

    history = [candle for candle in regime_candles if candle.timestamp <= timestamp]
    if len(history) < args.regime_slow_ema + 2:
        return {"name": "UNKNOWN", "long_allowed": False, "short_allowed": False}
    return classify_regime(history, args)


def run_backtest(args: argparse.Namespace) -> dict:
    candles_by_symbol = {
        symbol: fetch_historical_klines(symbol, args.interval, args.start, args.end, args.category)
        for symbol in args.symbols
    }
    regime_candles = (
        fetch_historical_klines(args.regime_symbol, args.regime_interval, args.start, args.end, args.category)
        if args.regime_filter
        else []
    )
    min_length = min(len(candles) for candles in candles_by_symbol.values())
    if min_length < max(args.lookback, args.slow_ema, args.atr_period, args.rsi_period) + 5:
        raise SystemExit("Dati insufficienti per il periodo richiesto.")

    state = default_state(args.capital)
    events: list[str] = []
    equity_curve: list[float] = []

    for idx in range(args.lookback, min_length):
        prices: dict[str, float] = {}
        for symbol, candles in candles_by_symbol.items():
            history = candles[: idx + 1]
            candle = candles[idx]
            prices[symbol] = candle.close
            regime = regime_at(candle.timestamp, regime_candles, args)
            event = run_symbol_step(state, symbol, history, candle, args, regime)
            if event:
                events.append(event)
        equity_curve.append(portfolio_value(state, prices))

    final_prices = {symbol: candles[min_length - 1].close for symbol, candles in candles_by_symbol.items()}
    final_equity = portfolio_value(state, final_prices)
    peak = args.capital
    max_drawdown = 0.0
    for equity in equity_curve or [args.capital]:
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak if peak else 0.0)

    trades = state["trades"]
    wins = [trade for trade in trades if trade["pnl"] > 0]
    losses = [trade for trade in trades if trade["pnl"] <= 0]
    gross_win = sum(trade["pnl"] for trade in wins)
    gross_loss = abs(sum(trade["pnl"] for trade in losses))

    return {
        "start": args.start,
        "end": args.end,
        "symbols": args.symbols,
        "capital": args.capital,
        "final_equity": final_equity,
        "return_pct": (final_equity / args.capital - 1) * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "closed_trades": len(trades),
        "open_positions": state["positions"],
        "win_rate_pct": (len(wins) / len(trades) * 100) if trades else 0.0,
        "profit_factor": gross_win / gross_loss if gross_loss else None,
        "events": events,
        "trades": trades,
        "state": state,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest Bybit della stessa logica paper trading.")
    parser.add_argument("--profile", choices=["base", "moonshot"], default="base")
    parser.add_argument("--allow-short", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--category", default="spot", choices=["spot", "linear", "inverse"])
    parser.add_argument("--interval", default="60")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--capital", type=float, default=100.0)
    parser.add_argument("--lookback", type=int, default=200)
    parser.add_argument("--risk", type=float, default=0.02)
    parser.add_argument("--max-open-risk", type=float, default=0.10)
    parser.add_argument("--correlated-risk-multiplier", type=float, default=0.5)
    parser.add_argument("--stop-cooldown-after", type=int, default=2)
    parser.add_argument("--cooldown-hours", type=int, default=24)
    parser.add_argument("--leverage", type=float, default=2.0)
    parser.add_argument("--adaptive-leverage", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--min-leverage", type=float, default=2.0)
    parser.add_argument("--max-leverage", type=float, default=70.0)
    parser.add_argument("--low-volatility", type=float, default=0.006)
    parser.add_argument("--high-volatility", type=float, default=0.025)
    parser.add_argument("--strong-trend-gap", type=float, default=0.01)
    parser.add_argument("--high-leverage-threshold", type=float, default=25.0)
    parser.add_argument("--high-leverage-max-risk", type=float, default=0.05)
    parser.add_argument("--max-symbol-allocation", type=float, default=0.45)
    parser.add_argument("--fee", type=float, default=0.001)
    parser.add_argument("--slippage", type=float, default=0.0005)
    parser.add_argument("--fast-ema", type=int, default=12)
    parser.add_argument("--slow-ema", type=int, default=48)
    parser.add_argument("--rsi-period", type=int, default=14)
    parser.add_argument("--atr-period", type=int, default=14)
    parser.add_argument("--min-rsi", type=float, default=50)
    parser.add_argument("--max-rsi", type=float, default=72)
    parser.add_argument("--short-min-rsi", type=float, default=28)
    parser.add_argument("--short-max-rsi", type=float, default=50)
    parser.add_argument("--short-breakdown-lookback", type=int, default=24)
    parser.add_argument("--volume-lookback", type=int, default=24)
    parser.add_argument("--short-volume-multiplier", type=float, default=1.15)
    parser.add_argument("--short-max-close-position", type=float, default=0.60)
    parser.add_argument("--short-risk-multiplier", type=float, default=0.45)
    parser.add_argument("--short-correlated-risk-multiplier", type=float, default=0.25)
    parser.add_argument("--short-max-risk", type=float, default=0.025)
    parser.add_argument("--short-max-leverage", type=float, default=25.0)
    parser.add_argument("--stop-atr", type=float, default=2.0)
    parser.add_argument("--take-profit-atr", type=float, default=4.0)
    parser.add_argument("--trailing-stop", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--trailing-activation-atr", type=float, default=2.0)
    parser.add_argument("--trailing-distance-atr", type=float, default=1.5)
    parser.add_argument("--regime-filter", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--regime-symbol", default="BTCUSDT")
    parser.add_argument("--regime-interval", default="240")
    parser.add_argument("--regime-lookback", type=int, default=260)
    parser.add_argument("--regime-fast-ema", type=int, default=50)
    parser.add_argument("--regime-slow-ema", type=int, default=200)
    parser.add_argument("--output", default="")
    return parser.parse_args()


def apply_profile(args: argparse.Namespace) -> argparse.Namespace:
    if args.profile == "moonshot":
        args.risk = 0.08
        args.max_open_risk = 0.12
        args.correlated_risk_multiplier = 0.4
        args.stop_cooldown_after = 2
        args.cooldown_hours = 24
        args.max_symbol_allocation = 0.75
        args.min_leverage = 8.0
        args.max_leverage = 70.0
        args.high_leverage_threshold = 25.0
        args.high_leverage_max_risk = 0.05
        args.stop_atr = 1.5
        args.take_profit_atr = 4.5
        args.trailing_activation_atr = 4.0
        args.trailing_distance_atr = 2.5
        args.regime_filter = True
        args.regime_symbol = "BTCUSDT"
        args.regime_interval = "240"
        args.regime_lookback = 260
        args.regime_fast_ema = 30
        args.regime_slow_ema = 120
        args.max_rsi = 78
        args.short_min_rsi = 22
        args.short_max_rsi = 45
        args.short_breakdown_lookback = 24
        args.volume_lookback = 24
        args.short_volume_multiplier = 1.15
        args.short_max_close_position = 0.60
        args.short_risk_multiplier = 0.45
        args.short_correlated_risk_multiplier = 0.25
        args.short_max_risk = 0.025
        args.short_max_leverage = 25.0
    return args


def main() -> None:
    args = apply_profile(parse_args())
    result = run_backtest(args)
    print("=== Bybit Paper Logic Backtest ===")
    print(f"Periodo: {result['start']} -> {result['end']}")
    print(f"Simboli: {', '.join(result['symbols'])}")
    print(f"Capitale iniziale: {result['capital']:.2f} USDT")
    print(f"Equity finale: {result['final_equity']:.2f} USDT")
    print(f"Rendimento: {result['return_pct']:.2f}%")
    print(f"Max drawdown: {result['max_drawdown_pct']:.2f}%")
    print(f"Trade chiusi: {result['closed_trades']}")
    print(f"Win rate: {result['win_rate_pct']:.2f}%")
    profit_factor = result["profit_factor"]
    print(f"Profit factor: {'n/a' if profit_factor is None else f'{profit_factor:.2f}'}")
    print(f"Posizioni aperte finali: {len(result['open_positions'])}")
    print("")
    print("Eventi:")
    for event in result["events"][-30:]:
        print(event)

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nReport JSON: {output}")


if __name__ == "__main__":
    main()
