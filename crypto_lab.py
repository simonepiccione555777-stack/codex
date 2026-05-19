from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean


@dataclass
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Trade:
    entry_time: str
    exit_time: str
    side: str
    entry: float
    exit: float
    quantity: float
    pnl: float
    reason: str


def load_candles(path: Path) -> list[Candle]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        rows = csv.DictReader(handle)
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        missing = required.difference(rows.fieldnames or [])
        if missing:
            raise ValueError(f"CSV incompleto. Mancano colonne: {', '.join(sorted(missing))}")

        candles = [
            Candle(
                timestamp=row["timestamp"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for row in rows
        ]

    if len(candles) < 100:
        raise ValueError("Servono almeno 100 candele per calcolare indicatori sensati.")
    return candles


def ema(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result

    alpha = 2 / (period + 1)
    current = mean(values[:period])
    result[period - 1] = current

    for idx in range(period, len(values)):
        current = values[idx] * alpha + current * (1 - alpha)
        result[idx] = current

    return result


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return result

    gains: list[float] = []
    losses: list[float] = []
    for idx in range(1, period + 1):
        delta = values[idx] - values[idx - 1]
        gains.append(max(delta, 0))
        losses.append(abs(min(delta, 0)))

    avg_gain = mean(gains)
    avg_loss = mean(losses)

    for idx in range(period + 1, len(values)):
        delta = values[idx] - values[idx - 1]
        gain = max(delta, 0)
        loss = abs(min(delta, 0))
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        result[idx] = 100 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))

    return result


def atr(candles: list[Candle], period: int = 14) -> list[float | None]:
    true_ranges: list[float] = []
    for idx, candle in enumerate(candles):
        if idx == 0:
            true_ranges.append(candle.high - candle.low)
            continue

        prev_close = candles[idx - 1].close
        true_ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - prev_close),
                abs(candle.low - prev_close),
            )
        )

    result: list[float | None] = [None] * len(candles)
    if len(true_ranges) < period:
        return result

    current = mean(true_ranges[:period])
    result[period - 1] = current
    for idx in range(period, len(true_ranges)):
        current = (current * (period - 1) + true_ranges[idx]) / period
        result[idx] = current

    return result


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def backtest(args: argparse.Namespace) -> tuple[list[Trade], list[float]]:
    candles = load_candles(Path(args.csv))
    closes = [c.close for c in candles]
    fast = ema(closes, args.fast_ema)
    slow = ema(closes, args.slow_ema)
    strength = rsi(closes, args.rsi_period)
    volatility = atr(candles, args.atr_period)

    cash = args.capital
    equity_curve = [cash]
    position_quantity = 0.0
    entry_price = 0.0
    entry_time = ""
    stop_price = 0.0
    take_profit = 0.0
    peak = cash
    trades: list[Trade] = []

    for idx in range(1, len(candles)):
        candle = candles[idx]
        current_equity = cash + position_quantity * candle.close
        peak = max(peak, current_equity)
        drawdown = (peak - current_equity) / peak if peak else 0

        if drawdown >= args.max_drawdown:
            if position_quantity:
                exit_price = candle.close * (1 - args.slippage)
                pnl = position_quantity * (exit_price - entry_price)
                fee = abs(position_quantity * exit_price) * args.fee
                cash += position_quantity * exit_price - fee
                trades.append(
                    Trade(entry_time, candle.timestamp, "LONG", entry_price, exit_price, position_quantity, pnl - fee, "max_drawdown")
                )
                position_quantity = 0
            equity_curve.append(cash)
            break

        if position_quantity:
            exit_reason = ""
            exit_price = 0.0
            if candle.low <= stop_price:
                exit_price = stop_price * (1 - args.slippage)
                exit_reason = "stop"
            elif candle.high >= take_profit:
                exit_price = take_profit * (1 - args.slippage)
                exit_reason = "take_profit"
            elif fast[idx] is not None and slow[idx] is not None and fast[idx] < slow[idx]:
                exit_price = candle.close * (1 - args.slippage)
                exit_reason = "trend_exit"

            if exit_reason:
                gross = position_quantity * exit_price
                fee = gross * args.fee
                pnl = position_quantity * (exit_price - entry_price) - fee
                cash += gross - fee
                trades.append(Trade(entry_time, candle.timestamp, "LONG", entry_price, exit_price, position_quantity, pnl, exit_reason))
                position_quantity = 0.0

        if position_quantity == 0 and all(x is not None for x in (fast[idx], slow[idx], strength[idx], volatility[idx])):
            trend_up = fast[idx] > slow[idx] and fast[idx - 1] <= slow[idx - 1] if fast[idx - 1] and slow[idx - 1] else False
            healthy_momentum = args.min_rsi <= strength[idx] <= args.max_rsi

            if trend_up and healthy_momentum:
                risk_amount = cash * args.risk
                stop_distance = volatility[idx] * args.stop_atr
                if stop_distance > 0:
                    raw_quantity = risk_amount / stop_distance
                    max_quantity = (cash * args.max_position) / candle.close
                    position_quantity = min(raw_quantity, max_quantity)
                    entry_price = candle.close * (1 + args.slippage)
                    entry_time = candle.timestamp
                    cost = position_quantity * entry_price
                    fee = cost * args.fee

                    if cost + fee <= cash and position_quantity > 0:
                        cash -= cost + fee
                        stop_price = entry_price - stop_distance
                        take_profit = entry_price + volatility[idx] * args.take_profit_atr
                    else:
                        position_quantity = 0.0

        equity_curve.append(cash + position_quantity * candle.close)

    if position_quantity:
        last = candles[-1]
        exit_price = last.close * (1 - args.slippage)
        gross = position_quantity * exit_price
        fee = gross * args.fee
        pnl = position_quantity * (exit_price - entry_price) - fee
        cash += gross - fee
        trades.append(Trade(entry_time, last.timestamp, "LONG", entry_price, exit_price, position_quantity, pnl, "final_close"))
        equity_curve.append(cash)

    return trades, equity_curve


def summarize(trades: list[Trade], equity_curve: list[float], start_capital: float, target: float) -> str:
    ending = equity_curve[-1]
    peak = start_capital
    max_drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    wins = [trade for trade in trades if trade.pnl > 0]
    losses = [trade for trade in trades if trade.pnl <= 0]
    profit_factor = sum(t.pnl for t in wins) / abs(sum(t.pnl for t in losses)) if losses and sum(t.pnl for t in losses) != 0 else math.inf

    lines = [
        "=== Crypto Trading Lab ===",
        f"Capitale iniziale: {start_capital:.2f} EUR",
        f"Capitale finale:   {ending:.2f} EUR",
        f"Target:            {target:.2f} EUR",
        f"Target raggiunto:  {'SI' if ending >= target else 'NO'}",
        f"Rendimento:        {pct((ending / start_capital) - 1)}",
        f"Max drawdown:      {pct(max_drawdown)}",
        f"Trade totali:      {len(trades)}",
        f"Win rate:          {pct(len(wins) / len(trades)) if trades else '0.00%'}",
        f"Profit factor:     {'inf' if math.isinf(profit_factor) else f'{profit_factor:.2f}'}",
    ]

    if trades:
        lines.extend(["", "Ultimi trade:"])
        for trade in trades[-8:]:
            lines.append(f"{trade.exit_time} {trade.reason:12} entry={trade.entry:.4f} exit={trade.exit:.4f} pnl={trade.pnl:.2f}")

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest crypto con gestione rischio.")
    parser.add_argument("--csv", required=True, help="Percorso CSV OHLCV.")
    parser.add_argument("--capital", type=float, default=100.0, help="Capitale iniziale in EUR.")
    parser.add_argument("--target", type=float, default=1000.0, help="Obiettivo finale in EUR.")
    parser.add_argument("--risk", type=float, default=0.02, help="Quota di capitale rischiata per trade.")
    parser.add_argument("--max-position", type=float, default=0.95, help="Quota massima di capitale allocabile.")
    parser.add_argument("--max-drawdown", type=float, default=0.35, help="Stop del sistema se il drawdown supera questa soglia.")
    parser.add_argument("--fee", type=float, default=0.001, help="Commissione per eseguito, es. 0.001 = 0.10%%.")
    parser.add_argument("--slippage", type=float, default=0.0005, help="Peggioramento prezzo stimato.")
    parser.add_argument("--fast-ema", type=int, default=12)
    parser.add_argument("--slow-ema", type=int, default=48)
    parser.add_argument("--rsi-period", type=int, default=14)
    parser.add_argument("--atr-period", type=int, default=14)
    parser.add_argument("--min-rsi", type=float, default=50)
    parser.add_argument("--max-rsi", type=float, default=72)
    parser.add_argument("--stop-atr", type=float, default=2.0)
    parser.add_argument("--take-profit-atr", type=float, default=4.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trades, equity_curve = backtest(args)
    print(summarize(trades, equity_curve, args.capital, args.target))


if __name__ == "__main__":
    main()
