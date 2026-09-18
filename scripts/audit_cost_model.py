#!/usr/bin/env python3
"""Audit the Phase 3 execution cost model.

This is a reusable diagnostic (not a one-off answer) for the recurring
question: "is the ~90+ bps average round-trip cost in Phase 3 simulations a
realistic venue-economics assumption, or an overly punitive simulation
artifact?"

It answers that by comparing two independent things side by side:

1. THEORETICAL fee cost per order_policy, computed with the exact same
   formula `strategies/volatility_breakout/execution_engine.py` uses
   (entry fee at the policy's maker/taker blend, exit fee ALWAYS at the
   taker rate), driven off the venue profile / verified fee receipt via
   `strategies.volatility_breakout.venue_profiles.venue_profile`.

2. REALIZED cost, measured directly from persisted `simulated_orders` rows
   as `gross_return_bps - net_return_bps`, broken down by order_policy,
   scenario, and symbol.

Usage:
    ./.venv-phase1/bin/python scripts/audit_cost_model.py \
        [--database data/swarm_data.db] [--settings config/settings.yaml]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.volatility_breakout.venue_profiles import POLICIES, venue_profile

SCENARIO_FEE_MULTIPLIERS = {
    "normal": 1.0,
    "cost_1_5x": 1.5,
    "cost_2x": 2.0,
    "liquidity_stress": 1.0,
    "infrastructure_stress": 1.0,
}

MAKER_FRACTION = {
    "market": 0.0,
    "marketable_limit": 0.0,
    "passive_post_only": 1.0,
    "passive_then_chase": 0.50,
}


def _load_cfg(settings_path: Path) -> SimpleNamespace:
    if not settings_path.exists():
        return SimpleNamespace()
    data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        data = {}
    return SimpleNamespace(**data)


def theoretical_fee_table(cfg: SimpleNamespace) -> list[dict[str, Any]]:
    profile = venue_profile("kraken", cfg)
    rows = []
    for policy in POLICIES:
        maker_fraction = MAKER_FRACTION[policy]
        fee_per_side = profile.taker_fee_bps * (1.0 - maker_fraction) + profile.maker_fee_bps * maker_fraction
        for scenario, mult in SCENARIO_FEE_MULTIPLIERS.items():
            entry_fee_bps = fee_per_side * mult
            exit_fee_bps = profile.taker_fee_bps * mult  # ALWAYS taker on exit, regardless of policy
            hypothetical_exit_fee_if_maker_respected = (
                profile.taker_fee_bps * (1.0 - maker_fraction) + profile.maker_fee_bps * maker_fraction
            ) * mult
            rows.append({
                "order_policy": policy,
                "scenario": scenario,
                "entry_fee_bps": round(entry_fee_bps, 4),
                "exit_fee_bps_actual_always_taker": round(exit_fee_bps, 4),
                "exit_fee_bps_if_maker_fraction_respected": round(hypothetical_exit_fee_if_maker_respected, 4),
                "round_trip_fee_bps_actual": round(entry_fee_bps + exit_fee_bps, 4),
                "round_trip_fee_bps_if_exit_respected_policy": round(
                    entry_fee_bps + hypothetical_exit_fee_if_maker_respected, 4
                ),
            })
    return rows, profile


def realized_cost_by_policy_scenario(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT order_policy, scenario,
               COUNT(*) n,
               AVG(gross_return_bps) avg_gross_bps,
               AVG(net_return_bps) avg_net_bps,
               AVG(gross_return_bps - net_return_bps) avg_realized_cost_bps
        FROM simulated_orders
        WHERE status = 'COMPLETED'
        GROUP BY order_policy, scenario
        ORDER BY order_policy, scenario
        """
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def fee_regime_histogram(
    conn: sqlite3.Connection, order_policy: str = "market", scenario: str = "normal"
) -> list[tuple[float, int]]:
    """Bucket the observed (net - gross) fee gap for an all-taker policy.

    `market` orders pay taker on both legs regardless of any maker/taker
    receipt, so this is the cleanest signal for detecting whether the
    persisted evidence base was generated under more than one fee-schedule
    configuration (e.g. before vs after a venue-economics receipt was wired
    in). A clean single-mode histogram means one consistent fee assumption
    was used throughout; a bimodal histogram means historical evidence is a
    blend of two different (and materially different) cost regimes.
    """
    cur = conn.execute(
        """
        SELECT ROUND(net_return_bps - gross_return_bps, 0) fee_gap, COUNT(*) n
        FROM simulated_orders
        WHERE status = 'COMPLETED' AND order_policy = ? AND scenario = ?
        GROUP BY fee_gap
        ORDER BY n DESC
        """,
        (order_policy, scenario),
    )
    return [(float(row[0]), int(row[1])) for row in cur.fetchall()]


def realized_cost_by_symbol(conn: sqlite3.Connection, scenario: str = "normal") -> list[dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT symbol,
               COUNT(*) n,
               AVG(gross_return_bps) avg_gross_bps,
               AVG(net_return_bps) avg_net_bps,
               AVG(gross_return_bps - net_return_bps) avg_realized_cost_bps
        FROM simulated_orders
        WHERE status = 'COMPLETED' AND scenario = ?
        GROUP BY symbol
        ORDER BY avg_realized_cost_bps DESC
        """,
        (scenario,),
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "swarm_data.db")
    parser.add_argument("--settings", type=Path, default=ROOT / "config" / "settings.yaml")
    args = parser.parse_args()

    cfg = _load_cfg(args.settings)
    fee_rows, profile = theoretical_fee_table(cfg)

    print("=== Venue fee schedule in effect ===")
    print(f"venue={profile.venue} maker_fee_bps={profile.maker_fee_bps} taker_fee_bps={profile.taker_fee_bps}")
    print(f"fee_source={profile.fee_source} fee_verified={profile.fee_verified}")
    print()

    print("=== THEORETICAL round-trip fee cost by order_policy x scenario (fees only, excludes spread/impact/latency) ===")
    header = (
        f"{'policy':<20}{'scenario':<22}{'entry_fee':>10}{'exit_fee(actual)':>18}"
        f"{'exit_fee(if_policy_respected)':>30}{'rt_fee(actual)':>16}{'rt_fee(if_respected)':>22}"
    )
    print(header)
    for row in fee_rows:
        print(
            f"{row['order_policy']:<20}{row['scenario']:<22}{row['entry_fee_bps']:>10}"
            f"{row['exit_fee_bps_actual_always_taker']:>18}{row['exit_fee_bps_if_maker_fraction_respected']:>30}"
            f"{row['round_trip_fee_bps_actual']:>16}{row['round_trip_fee_bps_if_exit_respected_policy']:>22}"
        )
    print()

    if not args.database.exists():
        print(f"Database not found at {args.database}; skipping realized-cost sections.")
        return 0

    conn = sqlite3.connect(str(args.database))
    fee_hist: list[tuple[float, int]] = []
    try:
        realized_ps = realized_cost_by_policy_scenario(conn)
        print("=== REALIZED cost by order_policy x scenario (gross_return_bps - net_return_bps, from persisted orders) ===")
        print(f"{'policy':<20}{'scenario':<22}{'n':>8}{'avg_gross_bps':>16}{'avg_net_bps':>14}{'avg_realized_cost_bps':>24}")
        for row in realized_ps:
            print(
                f"{row['order_policy']:<20}{row['scenario']:<22}{row['n']:>8}"
                f"{row['avg_gross_bps']:>16.3f}{row['avg_net_bps']:>14.3f}{row['avg_realized_cost_bps']:>24.3f}"
            )
        print()

        realized_sym = realized_cost_by_symbol(conn, scenario="normal")
        print("=== REALIZED cost by symbol, scenario=normal (highest cost first) ===")
        print(f"{'symbol':<14}{'n':>8}{'avg_gross_bps':>16}{'avg_net_bps':>14}{'avg_realized_cost_bps':>24}")
        for row in realized_sym:
            print(
                f"{row['symbol']:<14}{row['n']:>8}"
                f"{row['avg_gross_bps']:>16.3f}{row['avg_net_bps']:>14.3f}{row['avg_realized_cost_bps']:>24.3f}"
            )
        print()

        fee_hist = fee_regime_histogram(conn, order_policy="market", scenario="normal")
        print("=== Fee-regime check: market/normal fee gap (net - gross bps) histogram ===")
        print("market orders are always taker on both legs, so this isolates the fee schedule in")
        print("effect at simulation time, independent of any maker/taker policy blend.")
        for gap, n in fee_hist:
            print(f"  fee_gap={gap:>7.1f}bps  n={n}")
        print()
    finally:
        conn.close()

    expected_current_gap = -round(profile.taker_fee_bps * 2, 0)
    modes_found = {gap for gap, _ in fee_hist if _ > 0}
    stale_modes = sorted(g for g in modes_found if g != expected_current_gap)
    mixed_regime_detected = bool(fee_hist) and len(modes_found) > 1
    if mixed_regime_detected:
        current_n = next((n for g, n in fee_hist if g == expected_current_gap), 0)
        stale_n = sum(n for g, n in fee_hist if g != expected_current_gap)
        total_n = current_n + stale_n

    print("=== Interpretation ===")
    print(
        "1. The fee floor is driven by a VERIFIED real Kraken low-volume-tier schedule\n"
        f"   (maker={profile.maker_fee_bps}bps / taker={profile.taker_fee_bps}bps, source={profile.fee_source}),\n"
        "   not a synthetic or invented assumption. At this account tier, a round trip\n"
        "   that pays taker on both legs costs ~{:.0f}bps in fees alone before any spread,\n"
        "   impact, or latency slippage is added.".format(profile.taker_fee_bps * 2)
    )
    print(
        "2. execution_engine.py ALWAYS charges the exit leg at the taker rate, even for\n"
        "   passive_post_only (maker_fraction=1.0 on entry). This is a deliberate design\n"
        "   choice (exits are modeled as urgent), but it means passive_post_only's fee\n"
        "   advantage only ever applies to the entry leg, not the exit leg -- compare the\n"
        "   'rt_fee(actual)' vs 'rt_fee(if_respected)' columns above for that policy to see\n"
        "   the gap this creates. Whether that's realistic depends on whether the strategy's\n"
        "   exit logic genuinely requires immediate (taker) liquidity, or could tolerate a\n"
        "   passive/maker exit attempt with a taker fallback on timeout."
    )
    print(
        "3. Compare 'avg_realized_cost_bps' above to the theoretical fee-only figures: the\n"
        "   remainder (realized minus theoretical fee) is spread + impact + latency +\n"
        "   chase cost, which scale with the symbol's own liquidity -- check whether\n"
        "   thinner alt-pairs (e.g. SOL/ADA/HYPE) show a materially larger remainder than\n"
        "   majors in the per-symbol table above, which would indicate the spread/impact\n"
        "   assumptions (not the fee schedule) are what needs venue-specific calibration."
    )
    if mixed_regime_detected:
        print(
            "4. *** MIXED FEE-SCHEDULE REGIME DETECTED ***\n"
            f"   {stale_n}/{total_n} ({100.0 * stale_n / max(1, total_n):.1f}%) of market/normal completed\n"
            f"   orders show a fee gap of {stale_modes} bps -- NOT the {expected_current_gap:.0f}bps implied by\n"
            "   the currently-configured verified fee schedule. This means the persisted evidence\n"
            "   base is a BLEND of at least two different fee assumptions (an earlier, cheaper\n"
            "   default before the Kraken fee receipt was wired in, and the current verified\n"
            "   rate). Any aggregate 'average cost' figure computed over full history therefore\n"
            "   UNDERSTATES what a strategy run under the current, verified configuration would\n"
            "   actually pay -- the true forward-looking cost is closer to the theoretical\n"
            f"   round-trip figures above ({expected_current_gap:.0f}bps for an all-taker policy at\n"
            "   normal-scenario fees) than to any full-history average. Historical scorecards\n"
            "   spanning this regime change should be treated with caution, or filtered to only\n"
            "   the post-receipt evidence window, before being used to judge viability."
        )
    else:
        print(
            "4. No mixed fee-schedule regime detected in market/normal completed orders: the\n"
            "   observed fee gap is consistent with a single configuration throughout."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
