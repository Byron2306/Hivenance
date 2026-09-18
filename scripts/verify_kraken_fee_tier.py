#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_phase6_canary import build_private_client, load_local_exchange_credentials
from scripts.run_phase1_observer import load_observer_config


def _num(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed
    except (TypeError, ValueError):
        return None


def _pair_candidates(pair: str, containers: list[dict[str, Any]]) -> list[str]:
    wanted = str(pair or "").upper()
    compact = wanted.replace("/", "")
    candidates = [pair, wanted, compact]
    for container in containers:
        for key in container:
            normalized = str(key or "").upper()
            if normalized == compact or normalized.endswith(compact) or compact.endswith(normalized.strip("XZ")):
                candidates.append(str(key))
    candidates.extend(str(key) for container in containers for key in container.keys())
    return list(dict.fromkeys(item for item in candidates if item))


def _fee_pct_from_payload(payload: Any) -> float | None:
    if isinstance(payload, dict):
        for key in ("fee", "current_fee", "current", "taker", "maker"):
            value = _num(payload.get(key))
            if value is not None:
                return value
    if isinstance(payload, list) and payload:
        last = payload[-1]
        if isinstance(last, dict):
            return _fee_pct_from_payload(last)
        if isinstance(last, (list, tuple)) and len(last) >= 2:
            return _num(last[1])
    return None


def _extract_fee_bps(result: dict[str, Any], pair: str) -> tuple[float | None, float | None, dict[str, Any]]:
    fees = result.get("fees") if isinstance(result.get("fees"), dict) else {}
    fees_maker = result.get("fees_maker") if isinstance(result.get("fees_maker"), dict) else {}
    schedules = result.get("schedules") if isinstance(result.get("schedules"), dict) else {}
    pair_key = next((key for key in _pair_candidates(pair, [fees, fees_maker, schedules]) if key in fees), "")
    maker_key = next((key for key in _pair_candidates(pair, [fees_maker, fees, schedules]) if key in fees_maker), "")
    schedule_key = next((key for key in _pair_candidates(pair, [schedules, fees, fees_maker]) if key in schedules), "")
    taker_schedule = fees.get(pair_key)
    maker_schedule = fees_maker.get(maker_key)
    schedule_payload = schedules.get(schedule_key)
    taker_pct = _fee_pct_from_payload(taker_schedule)
    maker_pct = _fee_pct_from_payload(maker_schedule)
    if (maker_pct is None or taker_pct is None) and isinstance(schedule_payload, dict):
        maker_pct = maker_pct if maker_pct is not None else _fee_pct_from_payload(
            schedule_payload.get("maker") or schedule_payload.get("fees_maker")
        )
        taker_pct = taker_pct if taker_pct is not None else _fee_pct_from_payload(
            schedule_payload.get("taker") or schedule_payload.get("fees")
        )
    if maker_pct is None and taker_pct is not None:
        maker_pct = taker_pct
    return (
        None if maker_pct is None else round(float(maker_pct) * 100.0, 6),
        None if taker_pct is None else round(float(taker_pct) * 100.0, 6),
        {
            "pair_key": pair_key,
            "maker_key": maker_key,
            "schedule_key": schedule_key,
            "maker_schedule": maker_schedule,
            "taker_schedule": taker_schedule,
            "schedule_payload": schedule_payload,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify configured Phase-3 Kraken fees against account tier.")
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path, default=ROOT / "config/volatility_breakout_phase6.yaml")
    parser.add_argument("--pair", default="ETH/USD")
    parser.add_argument("--receipt", type=Path, default=ROOT / "data/kraken_fee_verification_receipt.json")
    parser.add_argument("--apply-settings", action="store_true", help="Update settings.yaml fee fields from verified account tier.")
    parser.add_argument("--debug-response", action="store_true", help="Include sanitized response keys/shapes in the receipt.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    credentials = load_local_exchange_credentials()
    client = build_private_client(cfg)
    if client is None:
        raise SystemExit("Kraken credentials unavailable; cannot verify account fee tier")
    result = client.trade_volume(args.pair)
    maker_bps, taker_bps, raw_schedule = _extract_fee_bps(result, args.pair)
    if maker_bps is None or taker_bps is None:
        debug_path = args.receipt.with_suffix(args.receipt.suffix + ".debug.json")
        debug = {
            "schema": "hivenance_kraken_fee_verification_debug_v1",
            "authority": "fee_model_debug_only",
            "execution_authority": "none",
            "pair": args.pair,
            "result_keys": sorted(str(key) for key in result.keys()),
            "fees_keys": sorted(str(key) for key in (result.get("fees") or {}).keys()) if isinstance(result.get("fees"), dict) else [],
            "fees_maker_keys": sorted(str(key) for key in (result.get("fees_maker") or {}).keys()) if isinstance(result.get("fees_maker"), dict) else [],
            "schedules_keys": sorted(str(key) for key in (result.get("schedules") or {}).keys()) if isinstance(result.get("schedules"), dict) else [],
            "raw_schedule_summary": raw_schedule,
        }
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(json.dumps(debug, indent=2, sort_keys=True, default=str), encoding="utf-8")
        raise SystemExit(f"Kraken TradeVolume response did not include usable maker/taker fee schedule; debug={debug_path}")
    receipt = {
        "schema": "hivenance_kraken_fee_verification_receipt_v1",
        "authority": "fee_model_verification_only",
        "execution_authority": "none",
        "verified_at": time.time(),
        "pair": args.pair,
        "credential_source": credentials.get("source"),
        "maker_fee_bps": maker_bps,
        "taker_fee_bps": taker_bps,
        "fee_source": "kraken_private_trade_volume",
        "configured_before": {
            "phase2_taker_fee_bps_per_side": getattr(cfg, "phase2_taker_fee_bps_per_side", None),
            "phase3_maker_fee_bps": getattr(cfg, "phase3_maker_fee_bps", None),
            "phase3_taker_fee_bps": getattr(cfg, "phase3_taker_fee_bps", None),
            "phase3_fee_profile_verified": getattr(cfg, "phase3_fee_profile_verified", None),
            "phase3_fee_profile_source": getattr(cfg, "phase3_fee_profile_source", None),
        },
        "raw_schedule_summary": raw_schedule,
    }
    if args.debug_response:
        receipt["debug_response_shape"] = {
            "result_keys": sorted(str(key) for key in result.keys()),
            "fees_keys": sorted(str(key) for key in (result.get("fees") or {}).keys()) if isinstance(result.get("fees"), dict) else [],
            "fees_maker_keys": sorted(str(key) for key in (result.get("fees_maker") or {}).keys()) if isinstance(result.get("fees_maker"), dict) else [],
            "schedules_keys": sorted(str(key) for key in (result.get("schedules") or {}).keys()) if isinstance(result.get("schedules"), dict) else [],
        }
    if args.apply_settings:
        data = yaml.safe_load(args.settings.read_text(encoding="utf-8")) or {}
        data["phase2_taker_fee_bps_per_side"] = taker_bps
        data["phase3_maker_fee_bps"] = maker_bps
        data["phase3_taker_fee_bps"] = taker_bps
        data["phase3_fee_profile_verified"] = True
        data["phase3_fee_profile_source"] = f"kraken_private_trade_volume:{args.pair}"
        try:
            receipt_path = args.receipt.relative_to(ROOT)
            data["phase3_venue_economics_receipt"] = str(receipt_path)
        except ValueError:
            data["phase3_venue_economics_receipt"] = str(args.receipt)
        args.settings.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        receipt["settings_updated"] = True
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True, default=str), encoding="utf-8")
    output = {"receipt": str(args.receipt), **receipt}
    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True, default=str))
    else:
        print(
            f"VERIFIED maker={maker_bps:.4f}bps taker={taker_bps:.4f}bps "
            f"pair={args.pair} receipt={args.receipt}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
