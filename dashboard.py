from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


def money(value: float) -> str:
    return f"{value:,.2f} USDT"


def signed_money(value: float) -> str:
    prefix = "+" if value >= 0 else ""
    return f"{prefix}{money(value)}"


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"cash": 100.0, "positions": {}, "trades": [], "last_seen": {}}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def estimate_equity(state: dict) -> float:
    equity = float(state.get("cash", 0))
    for raw_position in state.get("positions", {}).values():
        equity += float(raw_position.get("margin", 0))
    return equity


def render_positions(positions: dict) -> str:
    if not positions:
        return '<tr><td colspan="8">Nessuna posizione aperta</td></tr>'

    rows = []
    for symbol, position in sorted(positions.items()):
        rows.append(
            "<tr>"
            f"<td>{html.escape(symbol)}</td>"
            f"<td>{html.escape(position.get('side', 'LONG'))}</td>"
            f"<td>{float(position['leverage']):.1f}x</td>"
            f"<td>{float(position['entry']):,.4f}</td>"
            f"<td>{float(position['stop']):,.4f}</td>"
            f"<td>{float(position['take_profit']):,.4f}</td>"
            f"<td>{money(float(position['margin']))}</td>"
            f"<td>{html.escape(position['opened_at'])}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def render_trades(trades: list[dict]) -> str:
    if not trades:
        return '<tr><td colspan="7">Nessun trade chiuso</td></tr>'

    rows = []
    for trade in reversed(trades[-20:]):
        pnl = float(trade["pnl"])
        pnl_class = "positive" if pnl >= 0 else "negative"
        rows.append(
            "<tr>"
            f"<td>{html.escape(trade['symbol'])}</td>"
            f"<td>{html.escape(trade['reason'])}</td>"
            f"<td>{float(trade['entry']):,.4f}</td>"
            f"<td>{float(trade['exit']):,.4f}</td>"
            f"<td>{float(trade['quantity']):.8f}</td>"
            f'<td class="{pnl_class}">{signed_money(pnl)}</td>'
            f"<td>{html.escape(trade['closed_at'])}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def build_dashboard(state: dict, target: float) -> str:
    cash = float(state.get("cash", 0))
    equity = estimate_equity(state)
    closed_pnl = sum(float(trade.get("pnl", 0)) for trade in state.get("trades", []))
    progress = max(0.0, min(equity / target, 1.0)) if target > 0 else 0.0
    positions = state.get("positions", {})
    trades = state.get("trades", [])
    last_seen = state.get("last_seen", {})

    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bybit Paper Dashboard</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #101418;
      --panel: #171d22;
      --line: #27313a;
      --text: #ecf2f7;
      --muted: #95a3ad;
      --good: #41d18c;
      --bad: #ff6b6b;
      --accent: #ffd166;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.45;
    }}
    main {{
      width: min(1180px, calc(100% - 32px));
      margin: 0 auto;
      padding: 28px 0 48px;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: end;
      margin-bottom: 24px;
    }}
    h1, h2 {{ margin: 0; }}
    h1 {{ font-size: 28px; }}
    h2 {{ font-size: 18px; margin-bottom: 12px; }}
    .muted {{ color: var(--muted); }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 20px;
    }}
    .metric, section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .metric {{ padding: 16px; }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 8px;
      text-transform: uppercase;
    }}
    .metric strong {{ font-size: 22px; }}
    .progress {{
      height: 10px;
      background: #0c0f12;
      border: 1px solid var(--line);
      border-radius: 999px;
      overflow: hidden;
      margin-top: 10px;
    }}
    .bar {{
      width: {progress * 100:.2f}%;
      height: 100%;
      background: var(--accent);
    }}
    section {{
      padding: 16px;
      margin-top: 14px;
      overflow-x: auto;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 760px;
    }}
    th, td {{
      text-align: left;
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
      white-space: nowrap;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }}
    .positive {{ color: var(--good); }}
    .negative {{ color: var(--bad); }}
    @media (max-width: 800px) {{
      header {{ display: block; }}
      .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 520px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Bybit Paper Dashboard</h1>
        <div class="muted">Simulazione locale, nessun ordine reale</div>
      </div>
      <div class="muted">Ultime candele: {html.escape(json.dumps(last_seen, sort_keys=True))}</div>
    </header>

    <div class="grid">
      <div class="metric"><span>Cassa</span><strong>{money(cash)}</strong></div>
      <div class="metric"><span>Equity stimata</span><strong>{money(equity)}</strong></div>
      <div class="metric"><span>PNL chiuso</span><strong class="{"positive" if closed_pnl >= 0 else "negative"}">{signed_money(closed_pnl)}</strong></div>
      <div class="metric"><span>Target</span><strong>{money(target)}</strong><div class="progress"><div class="bar"></div></div></div>
    </div>

    <section>
      <h2>Posizioni Aperte</h2>
      <table>
        <thead><tr><th>Symbol</th><th>Lato</th><th>Leva</th><th>Entry</th><th>Stop</th><th>Take profit</th><th>Margine</th><th>Aperta</th></tr></thead>
        <tbody>{render_positions(positions)}</tbody>
      </table>
    </section>

    <section>
      <h2>Trade Chiusi</h2>
      <table>
        <thead><tr><th>Symbol</th><th>Motivo</th><th>Entry</th><th>Exit</th><th>Quantita</th><th>PNL</th><th>Chiusa</th></tr></thead>
        <tbody>{render_trades(trades)}</tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Genera una dashboard HTML per il paper trading Bybit.")
    parser.add_argument("--state", default="paper_state/bybit_paper.json")
    parser.add_argument("--output", default="dashboard.html")
    parser.add_argument("--target", type=float, default=1000.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    state = load_state(Path(args.state))
    output = Path(args.output)
    output.write_text(build_dashboard(state, args.target), encoding="utf-8")
    print(f"Dashboard generata: {output}")


if __name__ == "__main__":
    main()
