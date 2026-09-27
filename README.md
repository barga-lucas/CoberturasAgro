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

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/base_dark.png">
  <img alt="Daily Rosario soybean basis 2020-2026: stable around −3 USD/t, with spikes up to 250 USD/t during the dólar soja program windows" src="docs/img/base_light.png">
</picture>

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

## Hedging backtest (`src/coberturas/analisis/cobertura.py`)

### Two elevator cases

Following the BCR training material on grain elevators, an elevator hedges its **net exposed
position**, which can go either way:

- **Case A — long physical.** Bought soybeans "a precio" and holds them. Loses if prices fall.
  Hedges: sell futures, or buy a put.
- **Case B — short physical.** Received soybeans "a fijar" (the farmer fixes the price later)
  but already sold them "a precio" to free up silo space. Loses if prices rise before the
  farmer fixes. Hedges: buy futures, or buy a call.

**Scenarios:** enter at the end of March, April or May (harvest intake) and exit at the end of
June … November (when farmers fix prices): 18 scenarios per season, 2020–2026. Results are in
USD per tonne, one tonne hedged 1:1. The hedge contract, the same for futures and options, is
the first SOJ.ROS May/Jul/Nov contract at least two months after the exit month (options
expire about a month before their future). Options are at-the-money at entry, bought at the
entry settlement premium and sold at the exit settlement premium.

### Results — main sample (excluding "dólar soja" periods)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/estrategias_dark.png">
  <img alt="Range of hedging results per strategy for cases A and B: futures hedges have the narrowest range and remove 84% of the risk; put 31%, call 67%" src="docs/img/estrategias_light.png">
</picture>

90 scenarios, 6 seasons. *Effectiveness* = share of the unhedged variance removed.

| | Mean | Worst | Std. dev. | Effectiveness |
|---|---:|---:|---:|---:|
| **A** unhedged | +19.6 | −59.0 | 42.0 | — |
| **A** short futures | +12.8 | −27.4 | 16.6 | **84%** |
| **A** long put | +13.2 | −40.6 | 31.1 | 31%\* |
| **B** unhedged | −19.6 | −127.3 | 42.0 | — |
| **B** long futures | −12.8 | −61.7 | 16.6 | **84%** |
| **B** long call | −14.5 | −75.7 | 23.3 | 67%\* |

\* Put and call rows use the scenarios where the option existed at entry (86 and 88 of 90);
the paired comparison on the common sample gives the same picture.

**What this says**

1. **A futures hedge removes most of the price risk: ~84% of the variance, ~87% in the fully
   normal periods.** The worst outcome for a long elevator goes from −59 to −27 USD/t, and to
   −7 USD/t outside the blend period.
2. **What remains after a futures hedge is basis risk, and for a long elevator it has been
   positive on average: +12.8 USD/t.** That is the post-harvest recovery of the basis seen above.
   It is the elevator's reward for storing grain, *before* storage and financing costs, which
   this backtest does not include. The short elevator (case B) pays the same amount.
3. **Options sit in between.** They keep part of the upside, but the premium makes them a
   costlier and much less complete hedge, especially the put.
4. **The unhedged averages are not a structural result.** They mainly reflect the price rallies
   of 2020 and 2025 in a sample of only six seasons.

### "Dólar soja" periods, reported separately

24 scenarios, 2 seasons (2022–2023), in which the holding period overlaps a Programa de
Incremento Exportador window. **Hedge effectiveness collapses to 0–10%.** The peso pizarra
embedded the special exchange rate while A3 futures did not, so the physical–futures
relationship broke. A short elevator hedged with futures (case B) averaged −43 USD/t, with a
worst case of −203 USD/t. **A futures hedge protects against price risk, but not against
a regulatory change in the exchange rate.**

Regime windows, verified against the decree texts: PIE I 2022-09-05 → 09-30 (Decree 576/2022),
PIE II 2022-11-28 → 12-30 (787/2022), PIE III 2023-04-10 → 05-31 (194/2023), PIE IV and
extensions 2023-09-05 → 12-10 (443, 492, 549, 597/2023). The 80/20 "blend" (Decree 28/2023,
2023-12-13 → 2025-04-14, repealed by 269/2025) is flagged separately but kept in the main
sample: the basis stayed normal in 2024.

### Limitations

- **Small sample:** six seasons. The 18 scenarios within a season are highly correlated.
- **No costs:** commissions, margin financing, premium financing and storage costs are all
  left out.
- **Retrospective monthly comparison:** if the last day of a month has no price, the previous
  day is used, which is only known after the fact.
- **Only one hedge ratio (1:1) and one strike rule (at the money).**

## Decisions taken

1. **Hedger profile: elevator (acopiador)** — buys physical soybeans, stores them, sells later.
2. **FX for pizarra ARS → USD: BCRA A 3500**, same day.
3. Days without pizarra ("S/C") or without FX stay missing; nothing is forward-filled.
4. Contract expiry is inferred conservatively from the data (a contract is "expired" only if it
   stopped trading inside or after its delivery month); there is no downloadable official
   calendar.

5. **Two elevator cases** (long and short physical), entries Mar–May, exits Jun–Nov.
6. **"Dólar soja" periods reported separately** from the main results.

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

Regenerate the charts (downloads or reads the cached data and recomputes everything):

```bash
.venv/Scripts/python scripts/graficos.py
```
