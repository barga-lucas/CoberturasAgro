# CoberturasAgro — Did hedging pay off for a Rosario soybean elevator?

*English version, translated from the Spanish original: [versión original en español](README.md)*

## Summary

Backtest of how a Rosario soybean elevator could have hedged with A3 Mercados futures and options,
using daily market data from 2020 to 2026 (6 seasons, 90 scenarios in the main sample).

- **Futures removed about 84% of the price risk** (95% interval 74–90%). For an elevator holding
  grain, the worst case improved from −59 to −27 USD/t.
- **Options protected much less:** a long put removed about 31% of the variance and a long call
  about 67%. They keep part of the upside, but the premium is expensive. A collar (buy a put
  5% below the futures price and sell a call 5% above) removed 69% at almost no cost, still
  below futures.
- **Holding hedged grain earned the basis recovery:** +12.8 USD/t on average (interval +7 to +17)
  before storage and financing costs. That is about 12% a year in dollars, which is the cost level
  at which storing stops paying.
- **The hedge failed during the "dólar soja" FX programs (2022–2023):** it removed only 0–10% of
  the risk, because the physical price included a special exchange rate and the futures price
  did not.
- **Hedging about 1.3 tonnes of futures per tonne** looks slightly better out of sample (87% vs
  81%), but the gain is not statistically robust.

Everything is reproducible from public sources, with no missing values filled in and 141 offline
tests. The limits (six seasons, option premiums that are mostly settlement valuations rather than
trades, no fees or financing costs) are stated
next to each result.

## The question

### The elevator's problem

A grain elevator (*acopio*) near Rosario, Argentina, buys soybeans from farmers at harvest
(March to May), stores them in its silos and sells them months later. Between buying and
selling it holds grain whose price can fall. That is its **price risk**.

It trades at the **Cámara Arbitral de Rosario "pizarra" price**, the reference price for
soybeans delivered in Rosario. It moves with world soybean prices and, in Argentina, also with
the exchange rate, export taxes (*retenciones*) and special FX programs.

**Example.** In April the elevator buys 1,000 tonnes at 300 USD/t and plans to sell them in
September. If by September the pizarra price has fallen to 260 USD/t, it loses 40 USD/t:
40,000 dollars.

### How it can hedge

A3 Mercados (formerly Matba-Rofex) lists soybean futures and options for delivery in Rosario.

- **Futures:** in April the elevator *sells* a soybean future at, say, 305 USD/t. If by
  September the price has fallen and the future is at 265, it buys the future back and gains
  40 USD/t, which offsets the loss on the stored grain. If the price rises, the opposite
  happens: it gains on the grain and loses on the future. Either way, the result is almost
  locked in.
- **Put option:** works like insurance. The elevator pays a premium and, if the price falls,
  the option offsets the drop. If the price rises, it loses only the premium and keeps the gain.
- **Collar:** buy a put and pay for it by selling a call option. The elevator is protected
  against large drops but gives up large rises.

No hedge is perfect. The future tracks the soybean price, but it is not exactly that day's
Rosario pizarra price. The gap between the two is called the **basis**, and how much the basis
moves between buying and selling is a risk the hedge cannot remove.

There is also an elevator in the opposite position. It received grain *a fijar* ("price to be
fixed": the farmer chooses later on which day the price is set) and, to free up space, has
already sold it at a fixed price. If the price **rises** before the farmer fixes, it has to pay
more than it received. That elevator hedges by buying futures or calls. The project covers both
cases.

### What it answers

**Had an elevator hedged between 2020 and 2026, how much risk would each strategy have
removed, what would it have cost, and when would it have failed?**

The answer comes from simulating, with real daily prices, what would have happened in each
season:

1. **Basis:** how far and when the Rosario price drifts from the future. That sets the limit
   of what a hedge can achieve.
2. **Backtest:** the result of each strategy (no hedge, futures, options, collar) over 90
   combinations of buying date and selling date.
3. **Risk, not just the average:** the worst result, how much results vary and how much the
   option premium costs.

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
  <img alt="Range of hedging results per strategy for cases A and B: futures hedges have the narrowest range and remove 84% of the risk; collars 69%; put 31%, call 67%; out-of-the-money options less" src="docs/img/estrategias_light.png">
</picture>

90 scenarios, 6 seasons, USD per tonne. *Risk removed* = share of the unhedged variance that the
hedge eliminates. The 95% intervals come from a bootstrap that resamples whole seasons.

| | Mean | Worst | Std. dev. | Risk removed | 95% interval |
|---|---:|---:|---:|---:|---:|
| **A** unhedged | +19.6 | −59.0 | 42.0 | — | |
| **A** short futures | +12.8 | −27.4 | 16.6 | **84%** | 74–90% |
| **A** long put | +13.2 | −40.6 | 31.1 | 31%\* | 18–56% |
| **A** long put, 5% out of the money | +13.5 | −45.8 | 33.6 | 20%\* | 10–38% |
| **A** collar (±5%) | +12.1 | −36.4 | 21.0 | 69%\* | 54–82% |
| **B** unhedged | −19.6 | −127.3 | 42.0 | — | |
| **B** long futures | −12.8 | −61.7 | 16.6 | **84%** | 74–90% |
| **B** long call | −14.5 | −75.7 | 23.3 | 67%\* | 46–78% |
| **B** long call, 5% out of the money | −15.0 | −75.7 | 25.9 | 58%\* | 28–74% |
| **B** reverse collar (±5%) | −12.1 | −66.6 | 21.0 | 69%\* | 54–82% |

\* The option rows use the scenarios where the option was already listed at entry (86 to 88
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

### Out-of-the-money options and collars (`src/coberturas/analisis/collar.py`)

Same scenarios, contract and premium rule as above. The **5% out-of-the-money put** has the
listed strike closest to 95% of the entry futures price; the **5% out-of-the-money call**, the
one closest to 105%. If the closest listed strike is more than 2 percentage points away from
that target, the leg is marked unavailable instead of silently using another strike. The
**collar** of case A buys that put and sells that call; the **reverse collar** of case B buys the
call and sells the put.

- **The collar removed 69% of the risk, far more than a put alone (31% at the money, 20% out of
  the money), and cost almost nothing:** the call sold was worth slightly more than the put
  bought, so the elevator received about 1 USD/t at entry (median). Its average result
  (+12.1 USD/t) is close to the futures hedge (+12.8).
- **Futures are still the better protection.** Their worst case is −27 USD/t against −36 for
  the collar and −46 for the out-of-the-money put. The collar only makes sense for an elevator
  willing to bear price moves of up to 5% in either direction.
- **Variance counts gains as risk.** A put is meant to keep the upside, and that upside
  increases variance, so "risk removed" understates what a put is for. The worst case is the
  fairer comparison for options, and it points the same way.
- **The band width matters in a consistent way.** The wider the band, the less protection:

| Strike distance | Scenarios | A: put out of the money | A: collar | B: call out of the money | B: reverse collar |
|---|---:|---:|---:|---:|---:|
| 3% | 76 | 25% | 77% | 62% | 77% |
| 5% | 86 | 20% | 69% | 55% | 69% |
| 10% | 78 | 10% | 55% | 46% | 55% |

  Each row compares all strategies on the same scenarios, which is why the 5% row can differ
  slightly from the main table. The number of scenarios changes because a strike close enough
  to each target is not always listed.

**Liquidity caveat.** A3 publishes a settlement premium for every listed strike, even on days
without trades. On the entry day, the 5% out-of-the-money put had trades in only 6 of 28
positions and the call in 12 of 29 (on the exit day: 9 of 60 and 23 of 69), although all of
them had open interest. **Most of these premiums are the exchange's valuation, not prices at
which someone actually traded**, so the option and collar results are less reliable than the
futures results. Selling the call also requires margin, whose financing cost is not included.
In the "dólar soja" periods collars failed like every other hedge (about 9% of the risk
removed).

**Synthetic put.** A Bolsa de Comercio de Rosario course on hedging strategies (Cavarozzi, 2026)
recommends the *synthetic put* (sell a future and buy a call at the same strike) when calls are
more liquid than puts, which is common on the local market. The data agree on liquidity: the
out-of-the-money calls above traded about twice as often as the puts. Two checks on whether
the choice changes the hedge:

- **Put-call parity holds in A3 settlement premiums on any given day:** across about 15,000
  call/put pairs with strikes within 5% of the future (2020–2026), C − P − (F − K) has a median
  of 0.0 USD/t, and 90% of the pairs are within ±2 USD/t.
- **Over the actual holding periods the two hedges end up close, but not identical.** In the 64
  main-sample scenarios where a call with the put's strike was listed on both dates, the
  synthetic put differed from the put by a median of 1.0 USD/t (90% of scenarios within
  3.7 USD/t, at most 5.5). The difference is the change in the parity gap between entry and
  exit. Protection is about the same: 41% of the risk removed against 38% for the put on those
  same scenarios, with similar worst cases (−40.6 and −40.1 USD/t). In the other 22 scenarios there was no
  call listed at the put's strike on the entry day.

In this sample the choice between a put and a synthetic put comes down to liquidity and fees
rather than protection.

### Robustness (`src/coberturas/analisis/robustez.py`)

**Confidence intervals.** With only six seasons, and 18 highly correlated scenarios within each
one, a single number like "84%" overstates precision. The intervals in the table above resample
whole seasons (5,000 draws), so they reflect how much the result depends on which years happened
to be in the sample. The futures hedge stays clearly effective (74–90%) and clearly beats the put
(18–56%); against the call (46–78%) the intervals overlap slightly. The average basis gain of the
long elevator (+12.8 USD/t) has an interval of +7 to +17 USD/t, entirely above zero.

**Is hedging one-for-one the right size?** The standard benchmark in the literature is the
*minimum-variance hedge ratio* (Ederington, 1979): the number of tonnes of futures per tonne of
physical that minimises the variance of the hedged position. It is estimated **out of sample**:
the ratio applied in each season is fitted only on earlier seasons, which had all finished before
the elevator enters in March.

| Seasons 2021–2026 (72 scenarios) | Risk removed | Worst |
|---|---:|---:|
| One-for-one (1:1) | 81% | −27.4 |
| Minimum-variance ratio, out of sample | 87% | −23.1 |

- **The estimated ratio is about 1.3 and very stable** (1.27–1.41 across seasons). The physical
  price moved about 45% more than the hedge future (standard deviation 34 vs 24 USD/t). That is
  expected, because the hedge uses deferred contracts (November, or the next May), and deferred
  futures are less volatile than the spot price (the "Samuelson effect").
- **But the improvement is not robust.** The ratio of 1.3 beats one-for-one in 2024–2026 and loses
  in 2021–2022, and most of the gain comes from 2025. The 95% interval of the improvement goes from
  −1 to +8 percentage points and includes zero. This matches Wang, Wu and Yang (2015), who find
  that estimated ratios rarely beat the simple one-for-one hedge reliably out of sample.
- **Practical reading:** hedging somewhat more than one-for-one when using deferred contracts is
  reasonable, but the data are not strong enough to recommend a precise ratio.

The intervals keep the estimated ratios fixed, so they do not include the uncertainty of
re-estimating them. They also measure variance across pooled, overlapping scenarios, not the
annual results of a real portfolio.

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

This is an Argentine case of a phenomenon that is well studied in the United States:
**non-convergence**, when the physical price at the delivery point stops tracking the futures price.
Adjemian, Garcia, Irwin and Smith (2013) document it in US corn, soybean and wheat markets in
2005–2010. Goswami, Karali and Adjemian (2023) show that in those periods futures lose much of their
value as a hedge, whatever hedge ratio is used. The difference here is the cause: it came from an
exchange-rate regulation, not from storage economics.

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
- **Hedge ratios: one-for-one in the main results**; the minimum-variance ratio is tested
  separately. **A single strike rule (at the money).**

## Methodological choices

1. **Hedger: grain elevator**, in its two possible net positions (long and short physical).
2. **Pizarra converted to USD with the BCRA A 3500 rate** of the same day.
3. **No silent approximations:** missing prices stay missing, and invalid or ambiguous data
   stops the code instead of being guessed.
4. **Contract expiry inferred from the data:** a contract counts as expired only if it stopped
   trading within or after its delivery month. There is no downloadable official calendar.
5. **"Dólar soja" periods reported separately**, with dates taken from the decrees.

## Related work

- **Ederington (1979)**, *The Hedging Performance of the New Futures Markets*, Journal of
  Finance: the minimum-variance hedge ratio and the "share of variance removed" measure used here.
- **Wang, Wu and Yang (2015)**, [*Hedging with Futures: Does Anything Beat the Naïve Hedging
  Strategy?*](https://pubsonline.informs.org/doi/10.1287/mnsc.2014.2028), Management Science: the
  one-for-one hedge is hard to beat out of sample. This project reaches the same conclusion.
- **Adjemian, Garcia, Irwin and Smith (2013)**, [*Non-Convergence in Domestic Commodity Futures
  Markets*](https://ers.usda.gov/sites/default/files/_laserfiche/publications/43777/39376_eib115.pdf),
  USDA ERS.
- **Goswami, Karali and Adjemian (2023)**, [*Hedging with futures during nonconvergence in commodity
  markets*](https://www.sciencedirect.com/science/article/pii/S2405851323000545), Journal of
  Commodity Markets: the closest analogue to the "dólar soja" finding.
- **Gorostiaga (2017)**, [*Caracterización de la curva de futuros de soja…: Rosario y
  Chicago*](https://repositorio.utdt.edu/items/34cd5eeb-a536-49d2-ad23-7830d2afafe4), master's
  thesis, Universidad Torcuato Di Tella: the Rosario futures curve. It does not cover the basis or
  hedging.

No public project was found that backtests elevator hedging with A3 Mercados futures and options
against the Rosario physical price.

## Sources

- Price data: [Cámara Arbitral de Cereales de Rosario](https://www.cac.bcr.com.ar/es/precios-de-pizarra/consultas),
  [BCRA statistics API](https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/5),
  A3 Mercados public API used by [cem.matbarofex.com.ar](https://cem.matbarofex.com.ar/),
  [Yahoo Finance ZS=F](https://finance.yahoo.com/quote/ZS=F).
- Hedging strategies and synthetic options: Cavarozzi, F., *Estrategias de cobertura con futuros y
  opciones agrícolas* (2026), Bolsa de Comercio de Rosario course slides (not publicly available).
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
.venv/Scripts/python scripts/resultados_collar.py         # prints the collar tables
```

Raw downloads are cached in `data/raw/`, which is not versioned.

## License

[MIT](LICENSE). The data is not redistributed: each source keeps its own terms.
