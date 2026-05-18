from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


BASE_URL = "https://api.binance.com/api/v3/klines"


def to_millis(value: str) -> int:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def from_millis(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_klines(symbol: str, interval: str, start: str, end: str) -> list[list]:
    start_ms = to_millis(start)
    end_ms = to_millis(end)
    rows: list[list] = []

    while start_ms < end_ms:
        params = urlencode(
            {
                "symbol": symbol.upper(),
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 1000,
            }
        )
        with urlopen(f"{BASE_URL}?{params}", timeout=20) as response:
            batch = json.loads(response.read().decode("utf-8"))

        if not batch:
            break

        rows.extend(batch)
        start_ms = int(batch[-1][0]) + 1
        time.sleep(0.15)

    return rows


def save_csv(rows: list[list], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for row in rows:
            writer.writerow([from_millis(int(row[0])), row[1], row[2], row[3], row[4], row[5]])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scarica dati OHLCV pubblici da Binance.")
    parser.add_argument("--symbol", default="BTCUSDT", help="Coppia, es. BTCUSDT o ETHUSDT.")
    parser.add_argument("--interval", default="1h", help="Intervallo Binance, es. 15m, 1h, 4h, 1d.")
    parser.add_argument("--start", required=True, help="Data inizio ISO, es. 2026-01-01T00:00:00Z.")
    parser.add_argument("--end", required=True, help="Data fine ISO, es. 2026-02-01T00:00:00Z.")
    parser.add_argument("--output", default="data/BTCUSDT_1h.csv", help="Percorso CSV di output.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = fetch_klines(args.symbol, args.interval, args.start, args.end)
    if not rows:
        raise SystemExit("Nessun dato scaricato. Controlla simbolo, intervallo e date.")
    save_csv(rows, Path(args.output))
    print(f"Salvate {len(rows)} candele in {args.output}")


if __name__ == "__main__":
    main()
