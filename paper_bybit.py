from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bybit_public import fetch_klines
from crypto_lab import atr, ema, rsi


@dataclass
class PaperPosition:
    symbol: str
    quantity: float
    entry: float
    stop: float
    take_profit: float
    margin: float
    leverage: float
    opened_at: str
    side: str = "LONG"
    risk_fraction: float = 0.0


def default_state(capital: float) -> dict:
    return {"cash": capital, "positions": {}, "trades": [], "last_seen": {}, "risk": {"consecutive_stops": 0}}


def load_state(path: Path, capital: float) -> dict:
    if not path.exists():
        return default_state(capital)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_state(path: Path, state: dict) -> None:
    state.setdefault("risk", {"consecutive_stops": 0})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)


def latest_signal(candles, args: argparse.Namespace) -> tuple[str, dict]:
    closed = candles[:-1] if len(candles) > 1 else candles
    closes = [candle.close for candle in closed]
    volumes = [candle.volume for candle in closed]
    fast = ema(closes, args.fast_ema)
    slow = ema(closes, args.slow_ema)
    strength = rsi(closes, args.rsi_period)
    volatility = atr(closed, args.atr_period)
    idx = len(closed) - 1

    recent_low = min(candle.low for candle in closed[max(0, idx - args.short_breakdown_lookback) : idx]) if idx > 0 else closed[idx].low
    avg_volume = sum(volumes[max(0, idx - args.volume_lookback) : idx]) / min(args.volume_lookback, idx) if idx > 0 else volumes[idx]

    info = {
        "timestamp": closed[idx].timestamp,
        "close": closed[idx].close,
        "low": closed[idx].low,
        "volume": closed[idx].volume,
        "avg_volume": avg_volume,
        "recent_low": recent_low,
        "atr": volatility[idx],
        "rsi": strength[idx],
        "fast": fast[idx],
        "slow": slow[idx],
        "atr_pct": volatility[idx] / closed[idx].close if volatility[idx] else None,
    }

    if idx < 1 or any(value is None for value in (fast[idx], slow[idx], strength[idx], volatility[idx])):
        return "WAIT", info

    crossed_up = fast[idx] > slow[idx] and fast[idx - 1] <= slow[idx - 1]
    crossed_down = fast[idx] < slow[idx] and fast[idx - 1] >= slow[idx - 1] if fast[idx - 1] and slow[idx - 1] else False
    long_momentum = args.min_rsi <= strength[idx] <= args.max_rsi
    short_momentum = args.short_min_rsi <= strength[idx] <= args.short_max_rsi

    if crossed_up and long_momentum:
        return "BUY", info
    breakdown = closed[idx].close < recent_low
    volume_ok = closed[idx].volume >= avg_volume * args.short_volume_multiplier
    bearish_structure = fast[idx] < slow[idx]

    close_position_in_range = (closed[idx].close - closed[idx].low) / (closed[idx].high - closed[idx].low) if closed[idx].high > closed[idx].low else 1.0
    bearish_close = close_position_in_range <= args.short_max_close_position

    if crossed_down and short_momentum and breakdown and volume_ok and bearish_structure and bearish_close and args.allow_short:
        return "SHORT", info
    if crossed_down:
        return "SELL", info
    return "HOLD", info


def choose_leverage(info: dict, args: argparse.Namespace, side: str = "LONG") -> float:
    if not args.adaptive_leverage:
        return args.leverage

    rsi_value = info.get("rsi")
    atr_pct = info.get("atr_pct")
    fast_value = info.get("fast")
    slow_value = info.get("slow")
    price = info.get("close")

    if any(value is None for value in (rsi_value, atr_pct, fast_value, slow_value, price)):
        return args.min_leverage

    if side == "SHORT":
        trend_gap = max((slow_value - fast_value) / price, 0)
        momentum_score = max(0.0, min((args.short_max_rsi - rsi_value) / max(args.short_max_rsi - args.short_min_rsi, 1), 1.0))
    else:
        trend_gap = max((fast_value - slow_value) / price, 0)
        momentum_score = max(0.0, min((rsi_value - args.min_rsi) / max(args.max_rsi - args.min_rsi, 1), 1.0))
    trend_score = max(0.0, min(trend_gap / args.strong_trend_gap, 1.0))

    if atr_pct >= args.high_volatility:
        volatility_score = 0.25
    elif atr_pct <= args.low_volatility:
        volatility_score = 1.0
    else:
        span = args.high_volatility - args.low_volatility
        volatility_score = 1.0 - ((atr_pct - args.low_volatility) / span) * 0.75

    quality = (momentum_score * 0.4) + (trend_score * 0.35) + (volatility_score * 0.25)
    leverage = args.min_leverage + (args.max_leverage - args.min_leverage) * quality
    return round(max(args.min_leverage, min(leverage, args.max_leverage)), 1)


def close_position(state: dict, position: PaperPosition, price: float, timestamp: str, reason: str, args: argparse.Namespace) -> None:
    exit_price = price * (1 - args.slippage) if position.side == "LONG" else price * (1 + args.slippage)
    gross = position.quantity * exit_price
    fee = gross * args.fee
    if position.side == "SHORT":
        pnl = position.quantity * (position.entry - exit_price) - fee
    else:
        pnl = position.quantity * (exit_price - position.entry) - fee
    state["cash"] += position.margin + pnl
    state["trades"].append(
        {
            "symbol": position.symbol,
            "side": position.side,
            "opened_at": position.opened_at,
            "closed_at": timestamp,
            "entry": position.entry,
            "exit": exit_price,
            "quantity": position.quantity,
            "pnl": pnl,
            "reason": reason,
        }
    )
    risk_state = state.setdefault("risk", {"consecutive_stops": 0})
    if reason == "stop":
        risk_state["consecutive_stops"] = int(risk_state.get("consecutive_stops", 0)) + 1
        if risk_state["consecutive_stops"] >= args.stop_cooldown_after:
            risk_state["cooldown_until"] = add_hours(timestamp, args.cooldown_hours)
    elif pnl > 0:
        risk_state["consecutive_stops"] = 0
        risk_state["cooldown_until"] = ""
    del state["positions"][position.symbol]


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def add_hours(value: str, hours: int) -> str:
    return (parse_timestamp(value) + timedelta(hours=hours)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def in_cooldown(risk_state: dict, timestamp: str) -> bool:
    cooldown_until = risk_state.get("cooldown_until")
    if not cooldown_until:
        return False
    if parse_timestamp(timestamp) >= parse_timestamp(cooldown_until):
        risk_state["consecutive_stops"] = 0
        risk_state["cooldown_until"] = ""
        return False
    return True


def open_risk_fraction(state: dict) -> float:
    return sum(float(position.get("risk_fraction", 0)) for position in state.get("positions", {}).values())


def correlated_position_count(state: dict, symbol: str) -> int:
    prefix = symbol[-4:]
    return sum(1 for open_symbol in state.get("positions", {}) if open_symbol.endswith(prefix))


def paper_step(state: dict, symbol: str, args: argparse.Namespace) -> str:
    candles = fetch_klines(symbol=symbol, interval=args.interval, category=args.category, limit=args.lookback)
    if len(candles) < max(args.slow_ema, args.atr_period, args.rsi_period) + 5:
        return f"{symbol}: pochi dati disponibili."

    signal, info = latest_signal(candles, args)
    timestamp = info["timestamp"]
    price = info["close"]
    atr_value = info["atr"]
    state["last_seen"][symbol] = timestamp
    risk_state = state.setdefault("risk", {"consecutive_stops": 0})

    raw_position = state["positions"].get(symbol)
    if raw_position:
        position = PaperPosition(**raw_position)
        if position.side == "LONG" and price <= position.stop:
            close_position(state, position, position.stop, timestamp, "stop", args)
            return f"{symbol}: chiusa per stop a {position.stop:.4f}."
        if position.side == "LONG" and price >= position.take_profit:
            close_position(state, position, position.take_profit, timestamp, "take_profit", args)
            return f"{symbol}: chiusa per take profit a {position.take_profit:.4f}."
        if position.side == "SHORT" and price >= position.stop:
            close_position(state, position, position.stop, timestamp, "stop", args)
            return f"{symbol}: SHORT chiusa per stop a {position.stop:.4f}."
        if position.side == "SHORT" and price <= position.take_profit:
            close_position(state, position, position.take_profit, timestamp, "take_profit", args)
            return f"{symbol}: SHORT chiusa per take profit a {position.take_profit:.4f}."
        if position.side == "LONG" and info["fast"] is not None and info["slow"] is not None and info["fast"] < info["slow"]:
            close_position(state, position, price, timestamp, "trend_exit", args)
            return f"{symbol}: LONG chiusa per uscita trend a {price:.4f}."
        if position.side == "SHORT" and info["fast"] is not None and info["slow"] is not None and info["fast"] > info["slow"]:
            close_position(state, position, price, timestamp, "trend_exit", args)
            return f"{symbol}: SHORT chiusa per uscita trend a {price:.4f}."
        return f"{symbol}: posizione {position.side} aperta, segnale {signal}, prezzo {price:.4f}."

    if signal not in {"BUY", "SHORT"} or atr_value is None:
        return f"{symbol}: nessuna apertura, segnale {signal}, prezzo {price:.4f}."

    if in_cooldown(risk_state, timestamp):
        return f"{symbol}: BUY ignorato, pausa dopo stop consecutivi."

    current_open_risk = open_risk_fraction(state)
    if current_open_risk >= args.max_open_risk:
        return f"{symbol}: BUY ignorato, budget rischio aperto gia' pieno."

    side = "LONG" if signal == "BUY" else "SHORT"
    leverage = choose_leverage(info, args, side)
    effective_risk = min(args.risk, args.max_open_risk - current_open_risk)
    correlated_count = correlated_position_count(state, symbol)
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
        return f"{symbol}: segnale BUY ignorato, cassa insufficiente."

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
        )
    )
    return f"{symbol}: apertura paper {side} {leverage:.1f}x a {entry:.4f}, margine {margin:.2f} USDT."


def portfolio_value(state: dict, prices: dict[str, float]) -> float:
    value = state["cash"]
    for symbol, raw_position in state["positions"].items():
        position = PaperPosition(**raw_position)
        mark_price = prices.get(symbol, position.entry)
        if position.side == "SHORT":
            unrealized = position.quantity * (position.entry - mark_price)
        else:
            unrealized = position.quantity * (mark_price - position.entry)
        value += position.margin + unrealized
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Paper trading locale su dati pubblici Bybit.")
    parser.add_argument("--profile", choices=["base", "moonshot"], default="base")
    parser.add_argument("--allow-short", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--category", default="spot", choices=["spot", "linear", "inverse"])
    parser.add_argument("--interval", default="60", help="Intervallo Bybit: 15, 60, 240, D.")
    parser.add_argument("--state", default="paper_state/bybit_paper.json")
    parser.add_argument("--capital", type=float, default=100.0, help="Capitale iniziale paper in USDT.")
    parser.add_argument("--lookback", type=int, default=200)
    parser.add_argument("--risk", type=float, default=0.02)
    parser.add_argument("--max-open-risk", type=float, default=0.10)
    parser.add_argument("--correlated-risk-multiplier", type=float, default=0.5)
    parser.add_argument("--stop-cooldown-after", type=int, default=2)
    parser.add_argument("--cooldown-hours", type=int, default=24)
    parser.add_argument("--leverage", type=float, default=2.0, help="Leva fissa se --no-adaptive-leverage e' attivo.")
    parser.add_argument("--adaptive-leverage", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--min-leverage", type=float, default=2.0)
    parser.add_argument("--max-leverage", type=float, default=70.0)
    parser.add_argument("--low-volatility", type=float, default=0.006, help="ATR/prezzo sotto cui la leva puo' salire.")
    parser.add_argument("--high-volatility", type=float, default=0.025, help="ATR/prezzo sopra cui la leva viene ridotta.")
    parser.add_argument("--strong-trend-gap", type=float, default=0.01, help="Gap EMA/prezzo considerato trend forte.")
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
    state_path = Path(args.state)
    state = load_state(state_path, args.capital)
    prices: dict[str, float] = {}
    messages: list[str] = []

    for symbol in args.symbols:
        messages.append(paper_step(state, symbol, args))
        candles = fetch_klines(symbol=symbol, interval=args.interval, category=args.category, limit=2)
        if candles:
            prices[symbol] = candles[-1].close

    save_state(state_path, state)
    print("=== Bybit Paper Trading ===")
    for message in messages:
        print(message)
    print(f"Cassa: {state['cash']:.2f} USDT")
    print(f"Valore stimato: {portfolio_value(state, prices):.2f} USDT")
    print(f"Posizioni aperte: {len(state['positions'])}")
    print(f"Trade chiusi: {len(state['trades'])}")
    print(f"Stato salvato in: {state_path}")


if __name__ == "__main__":
    main()
