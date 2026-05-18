from __future__ import annotations

import argparse
from pathlib import Path

from bybit_public import fetch_historical_klines, save_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scarica dati OHLCV pubblici da Bybit.")
    parser.add_argument("--symbol", default="BTCUSDT", help="Coppia, es. BTCUSDT o ETHUSDT.")
    parser.add_argument("--category", default="spot", choices=["spot", "linear", "inverse"])
    parser.add_argument("--interval", default="60", help="Intervallo Bybit: 1, 3, 5, 15, 30, 60, 240, D.")
    parser.add_argument("--start", required=True, help="Data inizio ISO, es. 2026-01-01T00:00:00Z.")
    parser.add_argument("--end", required=True, help="Data fine ISO, es. 2026-02-01T00:00:00Z.")
    parser.add_argument("--output", default="data/BTCUSDT_60_bybit.csv", help="Percorso CSV di output.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candles = fetch_historical_klines(args.symbol, args.interval, args.start, args.end, args.category)
    if not candles:
        raise SystemExit("Nessun dato scaricato. Controlla simbolo, categoria, intervallo e date.")
    save_csv(candles, Path(args.output))
    print(f"Salvate {len(candles)} candele Bybit in {args.output}")


if __name__ == "__main__":
    main()
