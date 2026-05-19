from __future__ import annotations

import csv
import json
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import URLError
from urllib.request import urlopen

from crypto_lab import Candle


BASE_URL = "https://api.bybit.com/v5/market/kline"
MAX_RETRIES = 3


def to_millis(value: str) -> int:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def from_millis(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_klines(
    symbol: str,
    interval: str,
    category: str = "spot",
    start: str | None = None,
    end: str | None = None,
    limit: int = 200,
) -> list[Candle]:
    params: dict[str, str | int] = {
        "category": category,
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": min(max(limit, 1), 1000),
    }
    if start:
        params["start"] = to_millis(start)
    if end:
        params["end"] = to_millis(end)

    url = f"{BASE_URL}?{urlencode(params)}"
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urlopen(url, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except (TimeoutError, socket.timeout, URLError) as exc:
            last_error = exc
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Bybit API non raggiungibile dopo {MAX_RETRIES} tentativi: {exc}") from exc
            time.sleep(0.5 * attempt)
    else:
        raise RuntimeError(f"Bybit API non raggiungibile: {last_error}")

    if payload.get("retCode") != 0:
        message = payload.get("retMsg", "Errore sconosciuto Bybit")
        raise RuntimeError(f"Bybit API: {message}")

    raw_rows = payload.get("result", {}).get("list", [])
    candles = [
        Candle(
            timestamp=from_millis(int(row[0])),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )
        for row in raw_rows
    ]
    return sorted(candles, key=lambda candle: candle.timestamp)


def fetch_historical_klines(
    symbol: str,
    interval: str,
    start: str,
    end: str,
    category: str = "spot",
) -> list[Candle]:
    start_ms = to_millis(start)
    current_end_ms = to_millis(end)
    all_candles: list[Candle] = []

    while start_ms < current_end_ms:
        candles = fetch_klines(
            symbol=symbol,
            interval=interval,
            category=category,
            start=from_millis(start_ms),
            end=from_millis(current_end_ms),
            limit=1000,
        )
        if not candles:
            break

        all_candles.extend(candles)
        first_ms = to_millis(candles[0].timestamp)
        if first_ms <= start_ms:
            break
        current_end_ms = first_ms - 1
        time.sleep(0.15)

    unique = {candle.timestamp: candle for candle in all_candles}
    return [unique[key] for key in sorted(unique)]


def save_csv(candles: list[Candle], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for candle in candles:
            writer.writerow([candle.timestamp, candle.open, candle.high, candle.low, candle.close, candle.volume])
