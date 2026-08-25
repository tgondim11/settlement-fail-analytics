# Settlement Fail Analytics

A trade-settlement fail analytics pipeline and Streamlit dashboard, built as a
portfolio project applying supply chain / operations analytics thinking to
post-trade securities settlement — fail-rate monitoring, aging, root-cause
analysis, counterparty concentration, and cost-of-fail estimation.

*Live dashboard: not yet deployed — see the deployment steps in this README.*

## What this is

In securities operations, a "settlement fail" happens when a trade doesn't
settle on its contractual date (T+1 for U.S. equities/ETFs/Treasuries since
the SEC's May 2024 rule change, T+2 for corporate bonds) — usually because
the seller doesn't have the securities to deliver, the buyer doesn't have
funds, or there's a documentation/instruction mismatch. Fails create funding
cost, counterparty risk, and operational overhead, so ops teams track fail
rate, aging, and root cause the way a supply chain team tracks on-time
delivery and stockouts.

This project simulates that workflow end to end:

- **`pipeline.py`** — generates a synthetic trade-settlement dataset and runs
  the analytics: overall fail rate, fail rate by asset class, weekly trend,
  aging buckets, root-cause breakdown, top counterparties by fail count, and
  an estimated funding cost of fails.
- **`app.py`** — a Streamlit dashboard over those analytics, with filters by
  asset class and counterparty.
- **`notebooks/exploratory_analysis.ipynb`** — the same analytics explored
  interactively with matplotlib.

## Why synthetic data

Real settlement-fail data is confidential/non-public — no broker-dealer,
custodian, or clearing corp publishes trade-level fail data. So this project
generates a **reproducible, seeded synthetic dataset** rather than faking a
"real" source. The generator (`generate_trades()` in `pipeline.py`) is
calibrated to be broadly consistent with publicly-discussed industry norms:

- **T+1 settlement** for equities, ETFs, and Treasuries (the U.S. moved from
  T+2 to T+1 in May 2024); **T+2** for corporate bonds.
- **Low-single-digit blended fail rate**, in line with the range commonly
  cited for U.S. CNS settlement — this is a *modeling assumption*, not a
  specific vendor's reported statistic, and is documented as such here so
  it's honest in an interview.
- **Asset-class-dependent fail rates**: fixed income fails more than equities
  in the simulation, reflecting lower liquidity in specific CUSIPs.
- **Size effect**: the largest-notional quartile of trades has an elevated
  fail probability (securities availability for block-size trades).
- **Counterparty concentration**: each synthetic counterparty has a fixed
  risk multiplier, so fails cluster by counterparty rather than being
  uniform noise — mirroring how, in practice, a handful of counterparties
  usually account for a disproportionate share of fails.
- **Reason-mix by asset class**: fixed income skews toward "insufficient
  securities" (long fails), equities skew toward DK/documentation issues.
- **Gamma-distributed resolution times**: most fails resolve in a few days;
  a long right tail takes much longer — matching the shape (not exact
  values) of real operational resolution-time distributions.

The random seed (`SEED = 42`) is fixed, so `python pipeline.py` always
reproduces the exact same dataset and the exact numbers in this README.
Counterparty names are entirely fictional.

## Results (from a real run of `pipeline.py`)

```
Total trades analyzed:      15,000
Total fails:                339
Overall fail rate:          2.26%
Estimated cost of fails:    $11,565,288.45
```

**Fail rate by asset class**

| Asset Class | Fail Rate |
|---|---|
| Corporate Bond | 4.27% |
| Equity | 1.71% |
| Government Bond | 1.46% |
| ETF | 1.30% |

**Aging distribution (days late)**

| Bucket | Fail Count |
|---|---|
| 1-2 days | 152 |
| 3-5 days | 111 |
| 6-10 days | 55 |
| >10 days | 21 |

**Root cause breakdown**

| Reason | Count | % of Fails |
|---|---|---|
| Insufficient Securities (Long Fail) | 151 | 44.5% |
| DK - Trade/Documentation Discrepancy | 71 | 20.9% |
| Settlement Instruction Error | 47 | 13.9% |
| Insufficient Funds | 44 | 13.0% |
| Corporate Action Conflict | 26 | 7.7% |

**Top 10 counterparties by fail count**

| Counterparty | Fail Count | Total Notional |
|---|---|---|
| Journeyman Capital | 37 | $2,297,842,000 |
| Kestrel Institutional Brokers | 28 | $1,117,371,000 |
| Everline Global Markets | 26 | $2,037,170,000 |
| Palisade Trading Group | 25 | $1,584,145,000 |
| Northbridge Prime Services | 24 | $1,276,768,000 |
| Meridian Capital Partners | 23 | $1,638,000,000 |
| Thornfield Global Clearing | 20 | $1,675,653,000 |
| Fenwick Custody Solutions | 20 | $816,378,000 |
| Sable Point Capital | 17 | $883,514,800 |
| Ridgeline Brokerage | 16 | $539,397,500 |

**Resolution stats**

| Metric | Value |
|---|---|
| Mean days to resolve | 3.98 |
| Median days to resolve | 3.0 |
| Still open as of report date | 2.95% |

Reproduce these exact numbers with `python pipeline.py` (seed is fixed at 42).

## Project structure

```
settlement-fail-analytics/
├── app.py                          # Streamlit dashboard
├── pipeline.py                     # Data generation + analytics engine
├── requirements.txt
├── data/                           # Generated by pipeline.py (trades.csv, analytics_summary.json)
└── notebooks/
    └── exploratory_analysis.ipynb  # Interactive exploration of the analytics
```

## Running locally

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt

python pipeline.py             # regenerate data + print analytics summary
streamlit run app.py           # launch the dashboard
```

## Tech stack

Python, pandas, NumPy (data generation + analytics), Streamlit + Plotly
(dashboard), Jupyter + matplotlib (exploratory notebook).

## Author

**Thales Gondim**

I'm interested in the operational side of finance, and built this to bring my Supply Chain & Information Systems background to bear on it — settlement fail management is, at its core, an operations problem: tracking exceptions, root causes, and aging, the same way a supply chain team tracks on-time delivery and stockouts.
