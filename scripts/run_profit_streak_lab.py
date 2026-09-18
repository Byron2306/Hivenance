#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass

from strategies.volatility_breakout.profit_streak_engine import EquityPoint, ProfitStreakEngine


@dataclass
class Wallet:
    cash: float
    qty: list[float]
    entry: list[float]
    fees: float = 0.0
    actions: int = 0


def generate_prices(seed: int, seconds: int, symbols: int, regime: str) -> list[list[float]]:
    rng = random.Random(seed)
    vols = [rng.uniform(0.00025, 0.0007) for _ in range(symbols)]
    returns = [[0.0 for _ in range(symbols)] for _ in range(seconds)]
    if regime == "bursty":
        bursts = [[] for _ in range(symbols)]
        for j in range(symbols):
            t = 0
            while t < seconds:
                if rng.random() < 0.035:
                    duration = rng.randint(4, 24)
                    direction = -1 if rng.random() < 0.5 else 1
                    drift = rng.uniform(0.00018, 0.00065) * direction
                    bursts[j].append((t, min(seconds, t + duration), drift))
                    t += duration
                else:
                    t += 1
        for t in range(seconds):
            for j in range(symbols):
                drift = sum(value for start, end, value in bursts[j] if start <= t < end)
                returns[t][j] = rng.gauss(drift, vols[j])
    elif regime == "meanrev":
        prev = [0.0] * symbols
        for t in range(seconds):
            for j in range(symbols):
                value = -0.45 * prev[j] + rng.gauss(0.0, vols[j])
                returns[t][j] = value
                prev[j] = value
    else:
        for t in range(seconds):
            for j in range(symbols):
                returns[t][j] = rng.gauss(0.0, vols[j])

    prices = [[100.0 for _ in range(symbols)] for _ in range(seconds)]
    for t in range(1, seconds):
        for j in range(symbols):
            prices[t][j] = prices[t - 1][j] * math.exp(returns[t][j])
    return prices


def equity(wallet: Wallet, prices: list[float]) -> float:
    return wallet.cash + sum(qty * price for qty, price in zip(wallet.qty, prices))


def simulate(prices: list[list[float]], *, mode: str, cost_bps_side: float, notional_usd: float = 25.0) -> dict:
    symbols = len(prices[0])
    wallet = Wallet(1000.0, [0.0] * symbols, [0.0] * symbols)
    streak = ProfitStreakEngine(fast_horizon_sec=5, slow_horizon_sec=10, max_retracement_usd=0.05)
    history: list[float] = []

    for t, row in enumerate(prices):
        marked = equity(wallet, row)
        history.append(marked)
        streak.observe(EquityPoint(
            ts=float(t),
            equity_usd=marked,
            cumulative_cost_usd=wallet.fees,
            context={"mode": mode, "symbols": symbols},
        ))
        if t < 12:
            continue
        for j in range(symbols):
            r3 = row[j] / prices[t - 3][j] - 1.0
            r5 = row[j] / prices[t - 5][j] - 1.0
            r10 = row[j] / prices[t - 10][j] - 1.0
            have = wallet.qty[j] != 0.0
            enter = (r3 > 0.00045) if mode == "trade" else (r5 > 0.00055 and r10 > 0.00085)
            if not have and enter:
                notional = min(notional_usd, wallet.cash)
                fee = notional * cost_bps_side / 10000.0
                if notional <= fee:
                    continue
                wallet.qty[j] = (notional - fee) / row[j]
                wallet.entry[j] = row[j]
                wallet.cash -= notional
                wallet.fees += fee
                wallet.actions += 1
            elif have:
                pnl = row[j] / wallet.entry[j] - 1.0 if wallet.entry[j] else 0.0
                if mode == "trade":
                    leave = r3 <= 0.0
                else:
                    leave = (r5 < -0.00035 and r10 < 0.00015) or pnl < -0.0045
                if leave:
                    gross = wallet.qty[j] * row[j]
                    fee = gross * cost_bps_side / 10000.0
                    wallet.cash += gross - fee
                    wallet.fees += fee
                    wallet.qty[j] = 0.0
                    wallet.actions += 1

    last = prices[-1]
    for j in range(symbols):
        if wallet.qty[j] != 0.0:
            gross = wallet.qty[j] * last[j]
            fee = gross * cost_bps_side / 10000.0
            wallet.cash += gross - fee
            wallet.fees += fee
            wallet.qty[j] = 0.0
            wallet.actions += 1
    streak.finalize()
    return {
        "mode": mode,
        "start_equity_usd": 1000.0,
        "end_equity_usd": round(wallet.cash, 6),
        "net_usd": round(wallet.cash - 1000.0, 6),
        "actions": wallet.actions,
        "fees_usd": round(wallet.fees, 6),
        "streaks": streak.completed_receipts(),
        "authority": "paper_synthetic_only_no_orders",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic paper-only profit-streak comparison lab")
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--symbols", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260918)
    parser.add_argument("--regime", choices=("bursty", "noise", "meanrev"), default="bursty")
    parser.add_argument("--cost-bps-side", type=float, default=4.0)
    args = parser.parse_args()

    prices = generate_prices(args.seed, max(30, args.seconds), max(1, args.symbols), args.regime)
    report = {
        "schema": "hivenance_profit_streak_lab_v1",
        "synthetic": True,
        "regime": args.regime,
        "seconds": args.seconds,
        "symbols": args.symbols,
        "seed": args.seed,
        "cost_bps_side": args.cost_bps_side,
        "trade_control": simulate(prices, mode="trade", cost_bps_side=args.cost_bps_side),
        "streak_candidate": simulate(prices, mode="streak", cost_bps_side=args.cost_bps_side),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
