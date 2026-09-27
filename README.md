# CoberturasAgro — Did hedging pay off for Rosario soybean sellers?

## The question

A grain elevator (*acopiador*) near Rosario buys soybeans from farmers, stores them and sells
later. A producer or elevator, Argentina, sells into the
physical market at the **Cámara Arbitral de Rosario "pizarra" price**. Between planting and
harvest that price can move a lot — and in Argentina it also moves with the exchange rate,
export taxes (*retenciones*) and special FX programs.

**How much of that price risk could an elevator holding soybean inventory have removed with futures and options on
A3 Mercados (formerly Matba-Rofex), and which strategy — no hedge, short futures, long puts
or a collar — gave the best risk/return trade-off across recent seasons?**

Sub-questions:

1. **Basis:** how does the spread between the Rosario physical price and the futures price
   behave, and how predictable is it? Basis risk is the part a futures hedge cannot remove.
2. **Strategy backtest:** for each season, simulate the result of each hedging strategy from
   a fixed decision date to harvest.
3. **Risk, not just average return:** worst case, dispersion of outcomes, and the cost of the
   option premium paid for protection.

## Status

Work in progress. Data ingestion done for:

| Source | What | Coverage verified | Module |
|---|---|---|---|
| CAC-BCR (Cámara Arbitral de Rosario) | Daily pizarra price, ARS/tonne | 2015-01-02 → today | `src/coberturas/data/pizarra.py` |
| BCRA API v4 (variable 5) | Wholesale FX, Com. A 3500 | 2015-01-02 → today | `src/coberturas/data/fx.py` |
| Yahoo Finance `ZS=F` | CBOT soybean, continuous front month | 2015-01-01 → today | `src/coberturas/data/cbot.py` |
| A3 Mercados public API (`apicem.matbarofex.com.ar`) | SOJ.ROS futures settlements (USD/t) and option premiums by strike | 2020-01-02 → today (nothing earlier) | `src/coberturas/data/a3.py` |

### Data findings so far

- **The backtest window is 2020 onward.** A3's public API has no data before January 2020,
  so hedging with real futures/options prices can be tested for roughly six soybean seasons.

- **"S/C" (sin cotización) days:** some days the Cámara publishes no pizarra price. They are
  kept as explicit missing values, never filled. They cluster heavily in **2023 (144 of 244
  trading days)**, during the "dólar soja" special-FX programs, which is itself an
  interesting fact about the Argentine market.

## First results: the basis (`src/coberturas/analisis/base.py`)

**Basis = Rosario physical price (pizarra ARS/t ÷ same-day BCRA A 3500) − A3 SOJ.ROS futures
settlement (USD/t).** Only Rosario-delivery contracts in the liquid months (Jan, May, Jul, Sep,
Nov, which concentrate almost all volume).

- **Futures converge to the physical price.** Over the last 3 market days of each expired
  contract, the basis in normal periods has a median of **−4.1 USD/t** (interquartile range
  −6.2 to −2.6; 29 contracts, 2020–2026). This also validates the A 3500 conversion: using the
  previous day's rate barely changes the result.
- **In normal years the basis is small and stable:** median about −3 USD/t in 2020, 2021 and
  2024–2026, with a daily standard deviation of 4–9 USD/t. That is what makes a futures hedge
  effective: most of the price risk is in the futures price, which the hedge removes.
- **Seasonality relevant to an elevator:** the basis is weakest at harvest (April–July,
  about −6 USD/t) and turns positive in February–March (+4 to +13 USD/t, when the nearby
  contract is already the new-crop May). An elevator that buys at harvest and sells later earns
  part of that basis recovery. *(Hypothesis to test in the backtest.)*
- **Regime breaks.** Deviations above 30 USD/t cluster in Sep 2022, Nov–Dec 2022, Mar–May 2023
  and Sep 2023–Feb 2024. They coincide with the Programa de Incremento Exportador
  ("dólar soja", Decrees 576/2022, 787/2022, 194/2023, 443/2023 and extensions), during which
  the peso pizarra embedded a special exchange rate while futures did not. The exact start and
  end dates of each program **still have to be checked against the Boletín Oficial** before
  they are encoded.

## Decisions taken

1. **Hedger profile: elevator (acopiador)** — buys physical soybeans, stores them, sells later.
2. **FX for pizarra ARS → USD: BCRA A 3500**, same day.
3. Days without pizarra ("S/C") or without FX stay missing; nothing is forward-filled.
4. Contract expiry is inferred conservatively from the data (a contract is "expired" only if it
   stopped trading inside or after its delivery month); there is no downloadable official
   calendar.

## Still open

- How to treat the "dólar soja" periods in the backtest (exclude, or report separately).
- The elevator's storage horizon and which contract it hedges with.

## Principles

- No silent approximations: when a data point is missing or ambiguous, the code stops
  or marks it explicitly instead of guessing.
- Every data source is parsed with validation and covered by offline tests.

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows venv
.venv/Scripts/python -m pytest -q
```

Raw downloads are cached in `data/raw/` (not versioned).
