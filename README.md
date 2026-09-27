# CoberturasAgro — Did hedging pay off for a Rosario soybean elevator?

*[Versión en español](README.es.md)*

## The question

A grain elevator (*acopiador*) near Rosario, Argentina, buys soybeans from farmers, stores them
and sells them later. The physical price it deals at is the **Cámara Arbitral de Rosario
"pizarra" price**, which moves with world soybean prices and, in Argentina, also with the
exchange rate, export taxes (*retenciones*) and special FX programs.

**How much of that price risk could the elevator have removed with futures and options on
A3 Mercados (formerly Matba-Rofex), and which strategy gave the best trade-off between
protection and cost over 2020–2026?**

It comes down to three questions:

1. **Basis:** how does the gap between the Rosario physical price and the futures price behave?
   Basis risk is the part a futures hedge cannot remove.
2. **Backtest:** what would each hedging strategy (no hedge, futures, options) have returned
   in each season?
3. **Risk, not just average return:** worst case, dispersion, and the cost of the option
   premium.

## Data

| Source | What | Coverage | Module |
|---|---|---|---|
| Cámara Arbitral de Rosario (BCR) | Daily soybean pizarra price, ARS/t | 2015 → today | `src/coberturas/data/pizarra.py` |
| BCRA API v4 (variable 5) | Wholesale FX rate, Com. A 3500 | 2015 → today | `src/coberturas/data/fx.py` |
| A3 Mercados public API | SOJ.ROS futures settlements (USD/t) and option premiums by strike | 2020 → today (nothing earlier) | `src/coberturas/data/a3.py` |
| Yahoo Finance `ZS=F` | CBOT soybean, continuous front month (reference only) | 2015 → today | `src/coberturas/data/cbot.py` |

- **The backtest starts in 2020** because A3's public API has no earlier data. That gives
  about six soybean seasons.
- **Days without a pizarra price ("S/C", *sin cotización*)** are kept as explicit missing
  values and never filled. There were 144 such days in 2023 alone, during the "dólar soja"
  programs.

## The basis (`src/coberturas/analisis/base.py`)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/base_dark.png">
  <img alt="Daily Rosario soybean basis 2020-2026: stable around −3 USD/t, with spikes up to 250 USD/t during the dólar soja program windows" src="docs/img/base_light.png">
</picture>

**Basis = Rosario physical price (pizarra ARS/t ÷ same-day BCRA A 3500) − A3 SOJ.ROS futures
settlement (USD/t).** The reference contract is the nearest liquid month (Jan, May, Jul, Sep or
Nov, which concentrate almost all the volume).

- **Futures converge to the physical price.** Over the last three market days of each expired
  contract, the basis in normal periods has a median of **−4.1 USD/t** (middle half between
  −6.2 and −2.6; 29 contracts). This also confirms that the A 3500 rate is the right conversion.
- **In normal years the basis is small and stable:** about −3 USD/t, moving 4–9 USD/t day to
  day. That is why a futures hedge works well: most of the price risk sits in the futures price.
- **It is seasonal.** The basis is weakest at harvest (April–July, about −6 USD/t) and recovers
  afterwards. An elevator that buys at harvest and sells later captures that recovery; the
  backtest below measures it.
- **It breaks during the "dólar soja" programs.** Deviations above 30 USD/t cluster in
  Sep 2022, Nov–Dec 2022, Mar–May 2023 and Sep 2023–Feb 2024. During the Programa de
  Incremento Exportador the peso pizarra embedded a special exchange rate, while futures did not.

## Hedging backtest (`src/coberturas/analisis/cobertura.py`)

### Two elevator cases

Following the Bolsa de Comercio de Rosario training material on elevators, an elevator hedges
its **net exposed position**, which can go either way:

- **Case A — long physical.** It bought soybeans "a precio" (at a fixed price) and holds them.
  It loses if prices fall. Hedge: sell futures, or buy a put.
- **Case B — short physical.** It received soybeans "a fijar" (the farmer fixes the price
  later) but already sold them "a precio" to free up silo space. It loses if prices rise before
  the farmer fixes. Hedge: buy futures, or buy a call.

**Scenarios:** enter at the end of March, April or May (harvest intake) and exit at the end of
any month from June to November (when farmers fix their prices). That makes 18 scenarios per
season, 2020–2026. Results are in USD per tonne, hedging one tonne per tonne.

**Hedge contract:** the same contract for futures and options, so the comparison is fair. It is
the first SOJ.ROS May, July or November contract at least two months after the exit month,
because options expire about a month before their future and only those three months have
liquid options. Options are bought at the money at the entry settlement premium and sold at
the exit settlement premium.

### Results — main sample (excluding "dólar soja" periods)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/estrategias_dark.png">
  <img alt="Range of hedging results per strategy for cases A and B: futures hedges have the narrowest range and remove 84% of the risk; put 31%, call 67%" src="docs/img/estrategias_light.png">
</picture>

90 scenarios, 6 seasons, USD per tonne. *Risk removed* = share of the unhedged variance that the
hedge eliminates.

| | Mean | Worst | Std. dev. | Risk removed |
|---|---:|---:|---:|---:|
| **A** unhedged | +19.6 | −59.0 | 42.0 | — |
| **A** short futures | +12.8 | −27.4 | 16.6 | **84%** |
| **A** long put | +13.2 | −40.6 | 31.1 | 31%\* |
| **B** unhedged | −19.6 | −127.3 | 42.0 | — |
| **B** long futures | −12.8 | −61.7 | 16.6 | **84%** |
| **B** long call | −14.5 | −75.7 | 23.3 | 67%\* |

\* The option rows use the scenarios where the option was already listed at entry (86 and 88
of 90). Comparing all strategies on exactly the same scenarios gives the same picture.

**What it shows**

1. **Futures remove most of the price risk:** 84% of the variance, 87% outside the 2023–2025
   "blend" FX period. The worst result for a long elevator improves from −59 to −27 USD/t.
2. **What is left after a futures hedge is basis, and for a long elevator it paid:
   +12.8 USD/t on average.** That is the post-harvest basis recovery, the market's reward for
   storing grain. The short elevator (case B) pays that same amount.
3. **Options sit in between.** They keep part of the upside, but the premium makes them a more
   expensive and much less complete hedge, especially the put.
4. **The unhedged averages are not a structural result.** They mostly reflect the price rallies
   of 2020 and 2025 in a sample of only six seasons.

### Does storing pay? Break-even storage and financing cost

The +12.8 USD/t is **before storage and financing costs**. There is no reliable public source
for current storage tariffs or elevator funding rates, so instead of assuming them the backtest
reports the **break-even**: the cost that would bring each scenario's result to zero.

| Main sample (90 scenarios) | 25th pct | Median | 75th pct |
|---|---:|---:|---:|
| Basis gain per month of storage (USD/t per month) | 0.7 | **2.8** | 4.8 |
| The same gain as a simple annual USD return on the grain's value | 2% | **12%** | 21% |

- The hedged position made money in **82%** of the scenarios before costs. It would still have
  covered a storage plus financing cost of **2 USD/t per month in 58%** of them, and of
  3 USD/t per month in 48%.
- **In finance terms:** in the median scenario, storing hedged soybeans paid about 12% a year
  in dollars on the capital tied up in grain. If the elevator's funding and storage costs are
  below that, carrying hedged inventory was worth it.
- Exits in October and November hedge with the next year's May contract (new crop), so their
  larger gains include the old-crop/new-crop spread and are not directly comparable with
  June–September exits.

### "Dólar soja" periods, reported separately

24 scenarios in 2022–2023 whose holding period overlaps a Programa de Incremento Exportador
window. **Here the hedge stopped working: it removed only 0–10% of the risk.** The peso pizarra
included the special exchange rate while A3 futures did not, so the link between physical and
futures prices broke. A short elevator hedged with futures (case B) averaged −43 USD/t, with a
worst case of −203 USD/t. **A futures hedge protects against price moves, not against a change
in exchange-rate rules.**

| Regime | Dates | Source |
|---|---|---|
| PIE I | 2022-09-05 → 2022-09-30 | Decree 576/2022 |
| PIE II | 2022-11-28 → 2022-12-30 | Decree 787/2022 |
| PIE III | 2023-04-10 → 2023-05-31 | Decree 194/2023 |
| PIE IV and extensions | 2023-09-05 → 2023-12-10 | Decrees 443, 492, 549 and 597/2023 |
| 80/20 "blend" | 2023-12-13 → 2025-04-14 | Decree 28/2023, repealed by 269/2025 |

The blend period is flagged but kept in the main sample, because the basis stayed normal
during 2024.

### Limitations

- **Small sample:** six seasons, and the 18 scenarios within a season are highly correlated.
- **No costs in the results:** commissions and the financing of margins and premiums are left
  out; storage and financing are covered by the break-even above.
- **Retrospective monthly rule:** if the last market day of a month has no price, the previous
  day is used, which can only be known after the fact.
- **A single hedge ratio (1:1) and a single strike rule (at the money).**

## Methodological choices

1. **Hedger: grain elevator**, in its two possible net positions (long and short physical).
2. **Pizarra converted to USD with the BCRA A 3500 rate** of the same day.
3. **No silent approximations:** missing prices stay missing, and invalid or ambiguous data
   stops the code instead of being guessed.
4. **Contract expiry inferred from the data:** a contract counts as expired only if it stopped
   trading within or after its delivery month. There is no downloadable official calendar.
5. **"Dólar soja" periods reported separately**, with dates taken from the decrees.

## Sources

- Price data: [Cámara Arbitral de Cereales de Rosario](https://www.cac.bcr.com.ar/es/precios-de-pizarra/consultas),
  [BCRA statistics API](https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/5),
  A3 Mercados public API used by [cem.matbarofex.com.ar](https://cem.matbarofex.com.ar/),
  [Yahoo Finance ZS=F](https://finance.yahoo.com/quote/ZS=F).
- How elevators operate: Landrein, [*Acopios*](https://www.bcr.com.ar/sites/default/files/2018-10/acopio.pdf),
  and Rosa, [*Acopios: ¿mayor giro o mayor almacenamiento?*](https://www.capacitacion.bcr.com.ar/Documentos/EdicionesBCR/5/acopio_rossa.pdf)
  (2001), Bolsa de Comercio de Rosario training material.
- Regime dates: decrees [576/2022](https://www.boletinoficial.gob.ar/detalleAviso/primera/270972/20220905),
  [787/2022](https://www.boletinoficial.gob.ar/detalleAviso/primera/276571/20221128),
  [194/2023](https://www.boletinoficial.gob.ar/detalleAviso/primera/284120/20230410),
  [443/2023](https://www.boletinoficial.gob.ar/detalleAviso/primera/293431/20230905),
  [492/2023](https://www.boletinoficial.gob.ar/detalleAviso/primera/295254/20231002),
  [597/2023](https://www.argentina.gob.ar/normativa/nacional/decreto-597-2023-393336/texto) and
  [28/2023](https://servicios.infoleg.gob.ar/infolegInternet/anexos/395000-399999/395255/norma.htm).

## Running it

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows venv
.venv/Scripts/python -m pytest -q                         # offline tests
.venv/Scripts/python scripts/graficos.py                  # downloads the data and redraws the charts
```

Raw downloads are cached in `data/raw/`, which is not versioned.
