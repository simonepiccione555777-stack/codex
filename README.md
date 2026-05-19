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

Profilo piu aggressivo per cercare crescita rapida in paper trading:

```powershell
python paper_bybit.py --profile moonshot
```

Il profilo `moonshot` rischia 8% per trade, puo allocare fino al 75% della cassa per simbolo e usa un RR teorico 1:3. Il drawdown puo diventare molto piu pesante.

Gli short sono supportati e usano una logica piu selettiva: breakdown sotto il minimo recente, volume sopra media, chiusura debole nella parte bassa della candela e rischio ridotto. Puoi abilitarli cosi:

```powershell
python paper_bybit.py --profile moonshot --allow-short
```

Il trailing stop e' integrato ma disattivato di default: nel backtest 3 mesi riduce un po' il drawdown ma taglia troppo i trade migliori. Puoi testarlo cosi:

```powershell
python paper_bybit.py --profile moonshot --allow-short --trailing-stop
```

Il profilo include anche freni di rischio:

- rischio aperto totale massimo 12%;
- size ridotta quando BTCUSDT ed ETHUSDT sono aperti insieme;
- pausa di 24 ore dopo 2 stop consecutivi;
- se la leva supera 25x, rischio effettivo massimo 5% sul trade.
- filtro regime BTCUSDT 4H: long moonshot solo in regime rialzista, short solo in regime ribassista.
- protezione da drawdown: se l'equity scende troppo dal massimo, il sistema mette in pausa nuove aperture;
- protezione giornaliera: se la perdita del giorno supera la soglia, il sistema evita nuovi ingressi fino al giorno successivo.

Genera una dashboard locale:

```powershell
python dashboard.py
```

Poi apri `dashboard.html` nel browser.
La dashboard mostra capitale, equity stimata, PnL chiuso, stato rischio, posizioni aperte, ultimi trade, curva equity dei trade chiusi e riepilogo del backtest a 6 mesi se e' presente il report `runs/dashboard_backtest_6m.json`.

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

Oppure rigioca direttamente la logica del paper trader su BTCUSDT e ETHUSDT:

```powershell
python backtest_bybit_paper.py --start 2026-04-18T00:00:00Z --end 2026-05-18T00:00:00Z --output runs/backtest_2026-04-18_2026-05-18.json
```

Backtest del profilo aggressivo:

```powershell
python backtest_bybit_paper.py --profile moonshot --start 2026-04-18T00:00:00Z --end 2026-05-18T00:00:00Z --output runs/backtest_moonshot_2026-04-18_2026-05-18.json
```

Backtest con short abilitati:

```powershell
python backtest_bybit_paper.py --profile moonshot --allow-short --start 2026-02-18T00:00:00Z --end 2026-05-18T00:00:00Z --output runs/backtest_moonshot_longshort_3m.json
```

Backtest 6 mesi con filtro regime:

```powershell
python backtest_bybit_paper.py --profile moonshot --allow-short --start 2025-11-18T00:00:00Z --end 2026-05-18T00:00:00Z --output runs/backtest_moonshot_regime_6m.json
```

Il report del backtest mostra anche sintesi per mese, lato long/short e motivo di uscita. Questo serve a capire se la strategia sta guadagnando per vera qualita' del setup o solo per pochi trade fortunati.

Puoi confrontare diverse combinazioni di filtro regime, stop, take profit e protezioni cosi:

```powershell
python sweep_bybit_params.py --start 2025-11-18T00:00:00Z --end 2026-05-18T00:00:00Z --output runs/sweep_moonshot_6m.json
```

Il ranking non cerca solo il rendimento massimo: penalizza drawdown alto e campioni con pochi trade, cosi evita di premiare configurazioni troppo fragili.
Di default prova 6 combinazioni rapide. Per una ricerca piu' ampia puoi aggiungere `--wide` oppure `--deep`, ma richiedono piu' tempo.

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
