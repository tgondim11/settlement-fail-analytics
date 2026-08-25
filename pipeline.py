"""
Settlement Fail Analytics — analytics engine.

Generates a reproducible, synthetic trade-settlement dataset (real
production settlement data is confidential/non-public) calibrated to
publicly-discussed industry norms — low-single-digit fail rates, T+1
settlement for U.S. equities/ETFs/Treasuries post the May 2024 SEC rule
change, T+2 for corporate bonds — and runs the same fail analytics a
settlements/operations team would run in production: fail rate, aging,
root cause, counterparty concentration, and estimated cost of fails.

Run directly to regenerate the dataset and print the analytics summary:

    python pipeline.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
N_TRADES = 15_000
REPORT_DATE = pd.Timestamp("2026-08-25")
LOOKBACK_DAYS = 180

# Annualized short-term funding rate used to estimate the cost of a fail
# (broker/dealer typically bears an interest claim / opportunity cost on
# undelivered notional). Approximate SOFR-era short rate, act/360.
ANNUAL_FUNDING_RATE = 0.053
DAILY_FUNDING_RATE = ANNUAL_FUNDING_RATE / 360

ASSET_CLASSES = ["Equity", "ETF", "Corporate Bond", "Government Bond"]
ASSET_CLASS_WEIGHTS = [0.45, 0.15, 0.25, 0.15]

# T+N settlement cycle by asset class (business days), reflecting the
# May 2024 U.S. move to T+1 for equities/ETFs/Treasuries; corporate
# bonds remain T+2.
SETTLE_CYCLE = {
    "Equity": 1,
    "ETF": 1,
    "Government Bond": 1,
    "Corporate Bond": 2,
}

# Base fail probability by asset class, calibrated so the blended rate
# lands in the low-single-digit range commonly cited for U.S. CNS
# settlement (these are modeling assumptions, not a specific vendor's
# reported figures — documented as such in the README).
BASE_FAIL_RATE = {
    "Equity": 0.016,
    "ETF": 0.010,
    "Corporate Bond": 0.034,
    "Government Bond": 0.014,
}

FAIL_REASONS = [
    "Insufficient Securities (Long Fail)",
    "Insufficient Funds",
    "DK - Trade/Documentation Discrepancy",
    "Settlement Instruction Error",
    "Corporate Action Conflict",
]

# Reason-mix differs by asset class: fixed income fails skew toward
# securities availability; equities skew toward DK/documentation.
FAIL_REASON_WEIGHTS = {
    "Equity": [0.30, 0.15, 0.35, 0.15, 0.05],
    "ETF": [0.30, 0.15, 0.35, 0.15, 0.05],
    "Corporate Bond": [0.55, 0.10, 0.15, 0.15, 0.05],
    "Government Bond": [0.50, 0.10, 0.15, 0.20, 0.05],
}

# Mean days-to-resolve by reason (gamma-distributed around this mean).
RESOLUTION_MEAN_DAYS = {
    "Insufficient Securities (Long Fail)": 5.5,
    "Insufficient Funds": 2.0,
    "DK - Trade/Documentation Discrepancy": 3.0,
    "Settlement Instruction Error": 1.5,
    "Corporate Action Conflict": 6.5,
}

COUNTERPARTIES = [
    "Ashford Securities", "Bellwether Capital Partners", "Caldera Prime Brokerage",
    "Dunmore & Co.", "Everline Global Markets", "Fenwick Custody Solutions",
    "Greystone Trading LLC", "Harborview Asset Services", "Ironwood Clearing",
    "Journeyman Capital", "Kestrel Institutional Brokers", "Lindenmoor Securities",
    "Meridian Capital Partners", "Northbridge Prime Services", "Oakferry Markets",
    "Palisade Trading Group", "Quorum Custody Bank", "Ridgeline Brokerage",
    "Sable Point Capital", "Thornfield Global Clearing",
]

AGING_BUCKETS = [
    (0, 2, "1-2 days"),
    (2, 5, "3-5 days"),
    (5, 10, "6-10 days"),
    (10, np.inf, ">10 days"),
]


def _bucket_days(days: float) -> str:
    for lo, hi, label in AGING_BUCKETS:
        if lo < days <= hi:
            return label
    return "1-2 days"


def generate_trades(n_trades: int = N_TRADES, seed: int = SEED) -> pd.DataFrame:
    """Generate a synthetic, reproducible trade-settlement dataset."""
    rng = np.random.default_rng(seed)

    asset_class = rng.choice(ASSET_CLASSES, size=n_trades, p=ASSET_CLASS_WEIGHTS)

    start_date = REPORT_DATE - pd.Timedelta(days=LOOKBACK_DAYS)
    business_days = pd.bdate_range(start_date, REPORT_DATE)
    trade_date = pd.to_datetime(rng.choice(business_days, size=n_trades))

    settle_date = np.array([
        (pd.Timestamp(td) + pd.tseries.offsets.BDay(SETTLE_CYCLE[ac])).normalize()
        for td, ac in zip(trade_date, asset_class)
    ])

    counterparty = rng.choice(COUNTERPARTIES, size=n_trades)
    # Fixed per-counterparty risk multiplier -> creates realistic
    # concentration in "who fails the most" rather than pure noise.
    cp_risk = {cp: rng.lognormal(mean=0.0, sigma=0.35) for cp in COUNTERPARTIES}

    side = rng.choice(["Buy", "Sell"], size=n_trades)

    price = np.empty(n_trades)
    quantity = np.empty(n_trades)
    for ac in ASSET_CLASSES:
        mask = asset_class == ac
        n = mask.sum()
        if ac in ("Equity", "ETF"):
            price[mask] = rng.lognormal(mean=4.0, sigma=0.7, size=n)  # ~$25-$150
            quantity[mask] = rng.integers(100, 20_000, size=n)
        else:  # bonds priced near par, quantity = face value units
            price[mask] = rng.normal(99.5, 3.0, size=n).clip(80, 110)
            quantity[mask] = rng.integers(10_000, 2_000_000, size=n)

    notional = price * quantity

    df = pd.DataFrame({
        "trade_id": [f"T{100000 + i}" for i in range(n_trades)],
        "trade_date": trade_date,
        "settle_date": settle_date,
        "asset_class": asset_class,
        "counterparty": counterparty,
        "side": side,
        "quantity": quantity.astype(int),
        "price": price.round(2),
        "notional": notional.round(2),
    })

    # Notional-size effect: largest quartile of trades are somewhat more
    # prone to failing (securities availability for block-size trades).
    notional_q75 = df["notional"].quantile(0.75)
    size_multiplier = np.where(df["notional"] >= notional_q75, 1.35, 1.0)

    base_rate = df["asset_class"].map(BASE_FAIL_RATE).to_numpy()
    risk_multiplier = df["counterparty"].map(cp_risk).to_numpy()
    fail_prob = np.clip(base_rate * size_multiplier * risk_multiplier, 0, 0.35)

    is_fail = rng.random(n_trades) < fail_prob
    df["status"] = np.where(is_fail, "Failed", "Settled On Time")

    fail_reason = np.full(n_trades, "", dtype=object)
    days_to_resolve = np.full(n_trades, np.nan)
    actual_settle_date = pd.Series(pd.NaT, index=df.index)

    for ac in ASSET_CLASSES:
        mask = is_fail & (asset_class == ac)
        n = mask.sum()
        if n == 0:
            continue
        reasons = rng.choice(FAIL_REASONS, size=n, p=FAIL_REASON_WEIGHTS[ac])
        fail_reason[mask] = reasons
        means = np.array([RESOLUTION_MEAN_DAYS[r] for r in reasons])
        # Gamma distribution: realistic right-skew (most fails resolve
        # quickly, a long tail takes much longer).
        shape = 2.2
        resolve_days = rng.gamma(shape, means / shape)
        days_to_resolve[mask] = np.round(resolve_days).clip(1, None)

    df["fail_reason"] = fail_reason
    df["days_to_resolve"] = days_to_resolve

    candidate_resolve_date = df["settle_date"] + pd.to_timedelta(
        df["days_to_resolve"].fillna(0), unit="D"
    )
    still_open = is_fail & (candidate_resolve_date > REPORT_DATE)
    resolved_fail = is_fail & ~still_open

    actual_settle_date[resolved_fail] = candidate_resolve_date[resolved_fail]
    df["actual_settle_date"] = actual_settle_date
    df["fail_status"] = np.select(
        [still_open, resolved_fail],
        ["Open", "Resolved"],
        default="N/A",
    )

    # Days late as of report date: full days_to_resolve if resolved,
    # else days elapsed so far for still-open fails.
    days_late = np.full(n_trades, 0.0)
    days_late[resolved_fail] = df.loc[resolved_fail, "days_to_resolve"]
    days_late[still_open] = (REPORT_DATE - df.loc[still_open, "settle_date"]).dt.days
    df["days_late"] = days_late

    df["aging_bucket"] = np.where(
        is_fail, [(_bucket_days(d) if d > 0 else "1-2 days") for d in days_late], ""
    )

    df["estimated_cost"] = (df["notional"] * df["days_late"] * DAILY_FUNDING_RATE).round(2)
    df.loc[~is_fail, "estimated_cost"] = 0.0

    return df


def compute_analytics(df: pd.DataFrame) -> dict:
    """Run the standard suite of settlement-fail analytics on a trade dataset."""
    total_trades = len(df)
    fails = df[df["status"] == "Failed"]
    total_fails = len(fails)
    overall_fail_rate = total_fails / total_trades

    fail_rate_by_asset_class = (
        df.groupby("asset_class")["status"]
        .apply(lambda s: (s == "Failed").mean())
        .sort_values(ascending=False)
        .round(4)
    )

    weekly = df.copy()
    weekly["week"] = weekly["trade_date"].dt.to_period("W").apply(lambda p: p.start_time)
    fail_rate_trend = (
        weekly.groupby("week")["status"]
        .apply(lambda s: (s == "Failed").mean())
        .round(4)
    )

    aging_order = [b[2] for b in AGING_BUCKETS]
    aging_distribution = (
        fails["aging_bucket"].value_counts().reindex(aging_order).fillna(0).astype(int)
    )

    root_cause_breakdown = fails["fail_reason"].value_counts()
    root_cause_pct = (root_cause_breakdown / total_fails).round(4)

    top_counterparties = (
        fails.groupby("counterparty")
        .agg(fail_count=("trade_id", "count"), total_notional=("notional", "sum"))
        .sort_values("fail_count", ascending=False)
        .head(10)
    )

    resolved = fails[fails["fail_status"] == "Resolved"]
    open_fails = fails[fails["fail_status"] == "Open"]
    resolution_stats = {
        "mean_days_to_resolve": round(resolved["days_to_resolve"].mean(), 2) if len(resolved) else None,
        "median_days_to_resolve": round(resolved["days_to_resolve"].median(), 2) if len(resolved) else None,
        "pct_still_open": round(len(open_fails) / total_fails, 4) if total_fails else 0.0,
    }

    total_estimated_cost = round(fails["estimated_cost"].sum(), 2)

    return {
        "total_trades": total_trades,
        "total_fails": total_fails,
        "overall_fail_rate": round(overall_fail_rate, 4),
        "fail_rate_by_asset_class": fail_rate_by_asset_class,
        "fail_rate_trend": fail_rate_trend,
        "aging_distribution": aging_distribution,
        "root_cause_breakdown": root_cause_breakdown,
        "root_cause_pct": root_cause_pct,
        "top_counterparties": top_counterparties,
        "resolution_stats": resolution_stats,
        "total_estimated_cost": total_estimated_cost,
    }


def _print_summary(analytics: dict) -> None:
    print("=" * 60)
    print("SETTLEMENT FAIL ANALYTICS — SUMMARY")
    print("=" * 60)
    print(f"Total trades analyzed:      {analytics['total_trades']:,}")
    print(f"Total fails:                {analytics['total_fails']:,}")
    print(f"Overall fail rate:          {analytics['overall_fail_rate']:.2%}")
    print(f"Estimated cost of fails:    ${analytics['total_estimated_cost']:,.2f}")
    print()
    print("Fail rate by asset class:")
    print(analytics["fail_rate_by_asset_class"].apply(lambda x: f"{x:.2%}").to_string())
    print()
    print("Aging distribution (open + resolved fails):")
    print(analytics["aging_distribution"].to_string())
    print()
    print("Root cause breakdown:")
    for reason, count in analytics["root_cause_breakdown"].items():
        pct = analytics["root_cause_pct"][reason]
        print(f"  {reason:<40} {count:>5}  ({pct:.1%})")
    print()
    print("Top 10 counterparties by fail count:")
    print(analytics["top_counterparties"].to_string())
    print()
    stats = analytics["resolution_stats"]
    print("Resolution stats:")
    print(f"  Mean days to resolve:     {stats['mean_days_to_resolve']}")
    print(f"  Median days to resolve:   {stats['median_days_to_resolve']}")
    print(f"  Still open as of report date: {stats['pct_still_open']:.2%}")
    print("=" * 60)


def main() -> None:
    df = generate_trades()
    analytics = compute_analytics(df)
    _print_summary(analytics)

    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)
    df.to_csv(data_dir / "trades.csv", index=False)

    summary = {
        "total_trades": analytics["total_trades"],
        "total_fails": analytics["total_fails"],
        "overall_fail_rate": analytics["overall_fail_rate"],
        "total_estimated_cost": analytics["total_estimated_cost"],
        "fail_rate_by_asset_class": analytics["fail_rate_by_asset_class"].to_dict(),
        "aging_distribution": analytics["aging_distribution"].to_dict(),
        "root_cause_breakdown": analytics["root_cause_breakdown"].to_dict(),
        "resolution_stats": analytics["resolution_stats"],
    }
    with open(data_dir / "analytics_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)


if __name__ == "__main__":
    main()
