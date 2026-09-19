#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from collections import deque
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_live_profit_streak_swarm import KrakenPublicFeed
from strategies.relative_value_lab.conducting_queen import ConductingQueen
from strategies.relative_value_lab.contracts import RelativeMarketState, RELATIVE_VALUE_AUTHORITY
from strategies.relative_value_lab.forecast import OUMeanReversionForecaster, OUForecastConfig
from strategies.relative_value_lab.governance_epoch import ResearchGovernanceEpochService
from strategies.relative_value_lab.musical_cognition import MusicalMotifAccumulator
from strategies.relative_value_lab.pair_lab import PairRelationshipLab
from strategies.relative_value_lab.pollen_economy import QueenPollenEconomy
from strategies.relative_value_lab.pollen_paper_runtime import ProspectivePollenPaperRuntime
from strategies.relative_value_lab.pollen_profit_lab import QueenPollenConductor, settle_pollen_from_forecast
from strategies.relative_value_lab.polyphonic_entrainment import PolyphonicEntrainment
from strategies.relative_value_lab.polyphonic_quorum import PolyphonicQuorum, PolyphonicQuorumConfig
from strategies.relative_value_lab.waggle_protocol import BeeLineage, LineageRegistry, WaggleProtocol
from strategies.relative_value_lab.world_score import CanonicalWorldScore, ScoreObservation


AUTHORITY = "PUBLIC_MARKET_PAPER_ONLY_NO_PRIVATE_KEYS_NO_ORDERS"
STRUCT_ROOT = "sha256:" + "1" * 64
MOTION_ROOT = "sha256:" + "2" * 64


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _spread(price_a: float, price_b: float, alpha: float, beta: float) -> float:
    return math.log(float(price_a)) - float(alpha) - float(beta) * math.log(float(price_b))


def _direction(value: float) -> str:
    if value > 0:
        return "LONG_A_SHORT_B"
    if value < 0:
        return "LONG_B_SHORT_A"
    return "ABSTAIN"


def _pair_cost_bps(feed: KrakenPublicFeed, a: str, b: str, extra_cost_bps: float) -> float:
    # Conservative mark-to-mid round-trip proxy: one full quoted spread per leg.
    # Extra costs are explicit user configuration; no hidden venue fee assumption.
    return max(
        0.0,
        float(feed.last_spread_bps.get(a, 0.0))
        + float(feed.last_spread_bps.get(b, 0.0))
        + float(extra_cost_bps),
    )


def _registry() -> LineageRegistry:
    return LineageRegistry([
        BeeLineage(
            lineage_digest=STRUCT_ROOT,
            family="structural",
            root_lineage_digest=STRUCT_ROOT,
            description="Frozen OU pair-relationship voice",
        ),
        BeeLineage(
            lineage_digest=MOTION_ROOT,
            family="microstructure",
            root_lineage_digest=MOTION_ROOT,
            description="Recent public relative-motion voice",
        ),
    ])


def _world_frame(
    *,
    pair_id: str,
    symbol_a: str,
    symbol_b: str,
    now_ms: int,
    feed: KrakenPublicFeed,
):
    observations = []
    for symbol in (symbol_a, symbol_b):
        payload = {
            "symbol": symbol,
            "price": float(feed.last_prices[symbol]),
            "bid": float(feed.last_bid.get(symbol, 0.0)),
            "ask": float(feed.last_ask.get(symbol, 0.0)),
            "spread_bps": float(feed.last_spread_bps.get(symbol, 0.0)),
            "transport": "kraken_public_multi_pair_ticker",
        }
        observations.append(ScoreObservation(
            observation_id="obs_" + _digest({"pair": pair_id, "ts": now_ms, **payload}).split(":", 1)[1][:24],
            source_id=f"kraken:{symbol}",
            source_class="public_market_ticker",
            scope=f"symbol:{symbol}",
            observed_at_ms=now_ms,
            received_at_ms=now_ms,
            evidence_root=_digest(payload),
            payload=payload,
        ))
    return CanonicalWorldScore.assemble(
        observations=observations,
        assembled_at_ms=now_ms,
        freshness_window_ms=15_000,
    )


def _ensemble(
    *,
    forecast,
    diagnostics,
    frame,
    pair_id: str,
    symbol_a: str,
    symbol_b: str,
    previous_a: float,
    previous_b: float,
    current_a: float,
    current_b: float,
    now_ms: int,
    economy: QueenPollenEconomy,
):
    reg = _registry()
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)

    structural_evidence = _digest({
        "pair_id": pair_id,
        "forecast_id": forecast.forecast_id,
        "stability": diagnostics.stability_score,
        "half_life": diagnostics.half_life_seconds,
        "hedge_alpha": diagnostics.hedge_alpha,
        "hedge_ratio": diagnostics.hedge_ratio,
        "spread": diagnostics.spread_last,
        "equilibrium": diagnostics.ou_equilibrium,
    })

    previous_spread = _spread(
        previous_a,
        previous_b,
        float(diagnostics.hedge_alpha),
        float(diagnostics.hedge_ratio),
    )
    current_spread = _spread(
        current_a,
        current_b,
        float(diagnostics.hedge_alpha),
        float(diagnostics.hedge_ratio),
    )
    motion_bps = (current_spread - previous_spread) * 10_000.0
    motion_direction = _direction(motion_bps)
    motion_kind = "FOLLOW" if motion_direction == forecast.direction else "DISSENT"
    motion_evidence = _digest({
        "pair_id": pair_id,
        "previous_spread": previous_spread,
        "current_spread": current_spread,
        "motion_bps": motion_bps,
        "symbol_a": symbol_a,
        "symbol_b": symbol_b,
    })

    messages = [
        bus.build_message(
            bee_id="structural-bee",
            family="structural",
            lineage_digest=STRUCT_ROOT,
            message_type="WAGGLE",
            scope=pair_id,
            hypothesis_id=forecast.forecast_id,
            world_state_id=frame.world_state_id,
            world_state_hash=frame.world_state_hash,
            observed_at_ms=now_ms,
            evidence_root=structural_evidence,
            horizon_seconds=forecast.horizon_seconds,
            direction=forecast.direction,
            expected_move_bps=forecast.expected_relative_move_bps,
            uncertainty=forecast.uncertainty,
            independent_claimed=True,
            metadata={"stability_score": diagnostics.stability_score},
        ),
        bus.build_message(
            bee_id="motion-bee",
            family="microstructure",
            lineage_digest=MOTION_ROOT,
            message_type=motion_kind,
            scope=pair_id,
            hypothesis_id=forecast.forecast_id,
            world_state_id=frame.world_state_id,
            world_state_hash=frame.world_state_hash,
            observed_at_ms=now_ms,
            evidence_root=motion_evidence,
            horizon_seconds=forecast.horizon_seconds,
            direction=motion_direction,
            expected_move_bps=motion_bps,
            uncertainty=None,
            independent_claimed=True,
            metadata={"relative_motion_bps": motion_bps},
        ),
    ]

    receipts = []
    for message in messages:
        receipt = bus.publish(
            message,
            current_world_state_id=frame.world_state_id,
            current_world_state_hash=frame.world_state_hash,
            now_ms=now_ms,
        )
        receipts.append(receipt)
        acc.ingest(message=message, receipt=receipt)

    notes = acc.notes(forecast.forecast_id)
    motif = acc.score(forecast.forecast_id)
    entrainment = PolyphonicEntrainment().score(
        hypothesis_id=forecast.forecast_id,
        notes=notes,
    )
    epoch = ResearchGovernanceEpochService.start_epoch_from_frame(
        frame,
        started_at_ms=now_ms,
        ttl_ms=min(15_000, max(1_000, forecast.horizon_seconds * 1000)),
        genre_mode="watchful",
        strictness_level="standard",
        scope="relative_value_lab",
        reason="live_pollen_paper_pair_phrase",
    )
    queen = ConductingQueen().conduct_against_frame(
        frame=frame,
        now_ms=now_ms,
        hypothesis_id=forecast.forecast_id,
        notes=notes,
        motif=motif,
        entrainment=entrainment,
        epoch=epoch,
    )

    quorum = PolyphonicQuorum(PolyphonicQuorumConfig(
        minimum_independent_roots=2,
        minimum_families=2,
        minimum_roles=2,
        phase_window_ms=5_000,
        call_response_window_ms=5_000,
        ensemble_lock_threshold=0.58,
    )).score(notes)

    issue = QueenPollenConductor().issue(
        queen=queen,
        economy=economy,
        reward_scale=10.0,
        maximum_bounties=3,
    )

    for bounty_id in issue.bounty_ids:
        bounty = economy.bounty(bounty_id)
        for message, receipt in zip(messages, receipts):
            stance = (
                "DISSENT"
                if message.message_type == "DISSENT"
                else "SUPPORT"
            )
            try:
                economy.submit_claim(
                    bounty=bounty,
                    bee_id=message.bee_id,
                    receipt=receipt,
                    stance=stance,
                    confidence=0.70,
                    stake=0.25,
                    information_gain_claim=0.50,
                    submitted_at_ms=now_ms,
                )
            except ValueError:
                # Some Queen bounties intentionally expect challenge testimony.
                # Incompatible claims remain unsubmitted rather than coerced.
                pass

    return quorum, issue, motion_bps, motion_kind


def _print_summary(runtime: ProspectivePollenPaperRuntime, economy: QueenPollenEconomy) -> None:
    s = runtime.summary()
    c = s.control
    t = s.treatment
    print(
        "PAPER "
        f"settled={c.selected_count} "
        f"control_net={c.cumulative_net_bps:+.3f}bps "
        f"control_streak={c.current_positive_streak}/{c.longest_positive_streak} "
        f"quorum_n={t.selected_count} "
        f"quorum_net={t.cumulative_net_bps:+.3f}bps "
        f"quorum_streak={t.current_positive_streak}/{t.longest_positive_streak} "
        f"delta={s.cumulative_delta_bps:+.3f}bps "
        f"dd={t.max_drawdown_bps:.3f}bps"
    )
    leaders = economy.leaderboard()
    if leaders:
        print(
            "POLLEN "
            + " ".join(
                f"{bee}:balance={balance:.2f},rep={rep:.3f}"
                for bee, balance, rep in leaders
            )
        )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Live public Kraken Pollen/Quorum prospective paper gauntlet"
    )
    p.add_argument(
        "--symbols",
        nargs="+",
        default=["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "ADA/USD", "DOGE/USD"],
    )
    p.add_argument("--interval-sec", type=float, default=5.0)
    p.add_argument("--horizon-sec", type=int, default=30)
    p.add_argument("--min-samples", type=int, default=20)
    p.add_argument("--history-samples", type=int, default=90)
    p.add_argument("--forecast-every-sec", type=float, default=30.0)
    p.add_argument("--extra-cost-bps", type=float, default=0.0)
    p.add_argument("--minimum-net-edge-bps", type=float, default=0.50)
    p.add_argument("--duration-sec", type=int, default=0, help="0 = until Ctrl+C")
    p.add_argument(
        "--ledger",
        type=Path,
        default=Path("data/pollen_paper_gauntlet.jsonl"),
    )
    p.add_argument(
        "--summary-output",
        type=Path,
        default=Path("data/pollen_paper_summary.json"),
    )
    args = p.parse_args()
    if args.interval_sec < 2.0:
        p.error("--interval-sec must be >= 2")
    if args.horizon_sec < 1:
        p.error("--horizon-sec must be positive")
    if args.min_samples < 20:
        p.error("--min-samples must be >= 20")
    if args.forecast_every_sec < args.interval_sec:
        p.error("--forecast-every-sec must be >= --interval-sec")
    return args


def main() -> int:
    args = parse_args()
    feed = KrakenPublicFeed(list(args.symbols))
    histories = {
        symbol: deque(maxlen=max(args.min_samples, args.history_samples))
        for symbol in args.symbols
    }
    runtime = ProspectivePollenPaperRuntime(ledger_path=args.ledger)
    economy = QueenPollenEconomy(initial_pollen=20.0)
    pair_lab = PairRelationshipLab(
        min_samples=args.min_samples,
        min_return_correlation=0.10,
        min_stability_score=0.45,
    )
    forecaster = OUMeanReversionForecaster(
        OUForecastConfig(
            minimum_relationship_stability=0.45,
            minimum_net_edge_bps=args.minimum_net_edge_bps,
        )
    )

    feed.seed_prices()
    for symbol, price in feed.last_prices.items():
        histories[symbol].append(float(price))

    pairs = list(combinations(args.symbols, 2))
    last_forecast_at: dict[str, float] = {}
    bounties_by_forecast: dict[str, tuple[str, ...]] = {}
    quorum_by_forecast: dict[str, Any] = {}

    print("HiveNance Pollen Paper Gauntlet")
    print(f"authority={AUTHORITY}")
    print(
        f"symbols={len(args.symbols)} pairs={len(pairs)} "
        f"cadence={args.interval_sec:.1f}s horizon={args.horizon_sec}s "
        f"min_samples={args.min_samples}"
    )
    print(
        "cost_model=observed quoted spread round-trip proxy"
        + (f"+{args.extra_cost_bps:.3f}bps extra" if args.extra_cost_bps else "")
    )
    print("PRIVATE KEYS: 0 | ORDERS: 0 | EXECUTION AUTHORITY: none")

    deadline = None if args.duration_sec == 0 else time.monotonic() + args.duration_sec
    status = "COMPLETE"
    cycle = 0

    try:
        while deadline is None or time.monotonic() < deadline:
            started = time.monotonic()
            cycle += 1
            prices, _, meta = feed.poll()
            now = time.time()
            now_ms = int(now * 1000)

            for symbol in args.symbols:
                price = float(prices.get(symbol, 0.0))
                if price > 0:
                    histories[symbol].append(price)

            # First settle all forecasts whose horizons have matured using raw
            # public prices and each forecast's frozen hedge relationship.
            settled_now = 0
            for a, b in pairs:
                if a not in prices or b not in prices:
                    continue
                pair_id = PairRelationshipLab.pair_id(a, b)
                batch = runtime.settle_prices(
                    pair_id=pair_id,
                    timestamp_ms=now_ms,
                    price_a=float(prices[a]),
                    price_b=float(prices[b]),
                )
                for settlement in batch.settlements:
                    settled_now += 1
                    quorum = quorum_by_forecast.get(settlement.forecast_id)
                    for bounty_id in bounties_by_forecast.get(settlement.forecast_id, ()):
                        try:
                            settle_pollen_from_forecast(
                                economy=economy,
                                bounty=economy.bounty(bounty_id),
                                settlement=settlement,
                                quorum=quorum,
                                information_gain=1.0,
                            )
                        except ValueError:
                            pass

            eligible_pairs = 0
            new_forecasts = 0
            treatment_ready = 0

            for a, b in pairs:
                ha = list(histories[a])
                hb = list(histories[b])
                n = min(len(ha), len(hb))
                if n < args.min_samples:
                    continue
                ha = ha[-n:]
                hb = hb[-n:]

                diagnostics, _ = pair_lab.analyze(
                    symbol_a=a,
                    symbol_b=b,
                    prices_a=ha,
                    prices_b=hb,
                    sample_interval_sec=args.interval_sec,
                    venue="kraken",
                    observed_at_ms=now_ms,
                    direct_route_available=False,
                )
                if not diagnostics.eligible:
                    continue
                if diagnostics.hedge_alpha is None or diagnostics.hedge_ratio is None:
                    continue
                if diagnostics.spread_last is None:
                    continue
                eligible_pairs += 1

                pair_id = diagnostics.pair_id
                last_time = last_forecast_at.get(pair_id, 0.0)
                if now - last_time < args.forecast_every_sec:
                    continue

                state = RelativeMarketState(
                    schema="hivenance_relative_market_state_v1",
                    pair_id=pair_id,
                    timestamp_ms=now_ms,
                    spread=float(diagnostics.spread_last),
                    spread_zscore=diagnostics.spread_zscore,
                    spread_cost_bps=_pair_cost_bps(feed, a, b, args.extra_cost_bps),
                    authority=RELATIVE_VALUE_AUTHORITY,
                    execution_eligible=False,
                )
                forecast = forecaster.forecast(
                    state=state,
                    diagnostics=diagnostics,
                    horizon_seconds=args.horizon_sec,
                    expected_cost_bps=_pair_cost_bps(feed, a, b, args.extra_cost_bps),
                )
                if forecast.abstain:
                    last_forecast_at[pair_id] = now
                    continue
                if len(ha) < 2 or len(hb) < 2:
                    continue

                frame = _world_frame(
                    pair_id=pair_id,
                    symbol_a=a,
                    symbol_b=b,
                    now_ms=now_ms,
                    feed=feed,
                )
                quorum, issue, motion_bps, motion_kind = _ensemble(
                    forecast=forecast,
                    diagnostics=diagnostics,
                    frame=frame,
                    pair_id=pair_id,
                    symbol_a=a,
                    symbol_b=b,
                    previous_a=ha[-2],
                    previous_b=hb[-2],
                    current_a=ha[-1],
                    current_b=hb[-1],
                    now_ms=now_ms,
                    economy=economy,
                )
                reg = runtime.register(
                    forecast=forecast,
                    state=state,
                    quorum=quorum,
                )
                last_forecast_at[pair_id] = now
                bounties_by_forecast[forecast.forecast_id] = tuple(issue.bounty_ids)
                quorum_by_forecast[forecast.forecast_id] = quorum
                new_forecasts += 1
                treatment_ready += int(reg.treatment_eligible_at_registration)

                print(
                    f"FORECAST {pair_id} id={forecast.forecast_id[-8:]} "
                    f"dir={forecast.direction} exp_net={float(forecast.expected_net_bps or 0.0):+.3f}bps "
                    f"cost={float(forecast.expected_cost_bps or 0.0):.3f}bps "
                    f"motion={motion_bps:+.3f}bps/{motion_kind.lower()} "
                    f"quorum={int(quorum.quorum_formed)} lock={quorum.ensemble_lock:.3f} "
                    f"pollen={','.join(issue.bounty_types) or '-'}"
                )

            warmed = min(len(histories[s]) for s in args.symbols)
            print(
                f"CYCLE {cycle} warm={warmed}/{args.min_samples} "
                f"eligible_pairs={eligible_pairs} new={new_forecasts} "
                f"quorum_ready={treatment_ready} settled={settled_now} "
                f"pending={runtime.pending()} updated={meta.get('updated_pairs', 0)}"
            )
            _print_summary(runtime, economy)

            args.summary_output.parent.mkdir(parents=True, exist_ok=True)
            args.summary_output.write_text(
                json.dumps({
                    **runtime.summary().to_dict(),
                    "pollen_leaderboard": [
                        {"bee_id": bee, "balance": bal, "reputation": rep}
                        for bee, bal, rep in economy.leaderboard()
                    ],
                    "authority": AUTHORITY,
                    "orders_submitted": 0,
                    "private_keys_used": 0,
                }, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            elapsed = time.monotonic() - started
            time.sleep(max(0.0, args.interval_sec - elapsed))
    except KeyboardInterrupt:
        status = "INTERRUPTED"

    print(f"status={status}")
    _print_summary(runtime, economy)
    print(f"ledger={args.ledger}")
    print(f"summary={args.summary_output}")
    print("PRIVATE KEYS: 0 | ORDERS: 0 | EXECUTION AUTHORITY: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
