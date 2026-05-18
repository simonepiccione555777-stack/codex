# Crypto Trading Lab

Sistema di studio per strategie crypto ad alto rischio. Non promette di trasformare 100 EUR in 1000 EUR: ti permette di testare se una strategia avrebbe avuto senso sui dati storici, includendo commissioni, slippage, stop loss e blocco per drawdown.

## Perche non promette 10x

Fare 100 -> 1000 in 30 giorni significa circa +900%, cioe un rendimento medio composto di circa +8% al giorno. In crypto e possibile vedere movimenti estremi, ma inseguirli di solito implica un rischio molto alto di perdere gran parte o tutto il capitale.

## Cosa include

- Backtest su dati OHLCV in formato CSV.
- Download dati storici da Bybit V5.
- Paper trading locale su BTCUSDT e ETHUSDT con stato salvato su file.
- Strategia momentum con EMA, RSI, ATR, stop loss e take profit.
- Position sizing basato su rischio per trade.
- Commissioni e slippage configurabili.
- Kill switch se il drawdown supera una soglia.
- Report finale con equity, drawdown, win rate e obiettivo 1000 EUR.

## Formato dati

Metti i dati in `data/BTCUSDT_1h.csv` oppure passa un percorso diverso al comando.

Colonne richieste:

```csv
timestamp,open,high,low,close,volume
2026-01-01T00:00:00Z,42000,42500,41800,42300,1200
```

## Uso

### Paper trading Bybit

Esegue un ciclo paper su BTCUSDT e ETHUSDT usando dati pubblici Bybit. Non apre ordini reali. La simulazione usa capitale iniziale di 100 USDT e leva paper adattiva: di default puo scegliere tra 2x e 70x in base a trend, momentum e volatilita.

```powershell
python paper_bybit.py
```

Lo stato viene salvato in `paper_state/bybit_paper.json`. Ogni nuova esecuzione aggiorna cassa, posizioni e trade simulati.

Puoi limitare la leva massima cosi:

```powershell
python paper_bybit.py --max-leverage 10
```

Puoi anche disattivare la leva adattiva e usare una leva fissa:

```powershell
python paper_bybit.py --no-adaptive-leverage --leverage 5
```

### Backtest Bybit

Scarica prima i dati storici da Bybit:

```powershell
python download_bybit_csv.py --symbol BTCUSDT --interval 60 --start 2026-01-01T00:00:00Z --end 2026-02-01T00:00:00Z --output data/BTCUSDT_60_bybit.csv
```

Poi lancia il backtest:

```powershell
python crypto_lab.py --csv data/BTCUSDT_60_bybit.csv --capital 100 --target 1000
```

Esempio con parametri piu aggressivi:

```powershell
python crypto_lab.py --csv data/BTCUSDT_1h.csv --capital 100 --target 1000 --risk 0.04 --take-profit-atr 5 --stop-atr 1.5
```

## Regole operative consigliate

- Parti solo in paper trading.
- Non usare leva finche il backtest e il forward test non sono stabili.
- Rischia al massimo 1-2% per trade se vuoi sopravvivere a una serie negativa.
- Per tentare un 10x userai parametri aggressivi, ma il sistema ti mostrera quanto spesso questo aumenta il drawdown.

## Fonti di rischio

Le crypto sono estremamente volatili e possono perdere valore rapidamente. FINRA avverte che il rischio di perdere tutto l'investimento e significativo; la CFTC considera la speculazione su virtual currency una transazione ad alto rischio.
