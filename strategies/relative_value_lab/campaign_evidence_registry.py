from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

SCHEMA="hivenance_phase14_campaign_evidence_v1"
RESEARCH_ONLY="RESEARCH_ONLY"


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CampaignEvidence:
    campaign_id: str
    model_id: str
    horizon_seconds: int
    evidence_role: str
    source_commit: str
    freeze_id: str
    market_tape_sha256: str
    forecast_book_sha256: str
    preoutcome_cohort_sha256: str | None
    started_at: str | None
    ended_at: str | None
    fills: int
    distinct_symbols: int
    distinct_worlds: int
    mean_gross_bps: float | None
    median_gross_bps: float | None
    mean_net_bps: float | None
    median_net_bps: float | None
    mean_excess_vs_random_bps: float | None
    largest_symbol_fraction: float | None
    execution_eligible: bool = False
    promotion_eligible: bool = False
    authority_effect: str = "NONE_RESEARCH_ONLY"

    def payload(self) -> dict[str, Any]:
        return asdict(self)

    def receipt(self) -> dict[str, Any]:
        payload=self.payload()
        return {
            "schema":SCHEMA,
            "evidence":payload,
            "evidence_sha256":_sha256_json(payload),
        }


def validate_campaign_evidence(receipt: Mapping[str, Any]) -> None:
    if str(receipt.get("schema") or "") != SCHEMA:
        raise ValueError("campaign_evidence_schema_mismatch")
    evidence=receipt.get("evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("campaign_evidence_missing")
    expected=str(receipt.get("evidence_sha256") or "")
    if not expected or expected != _sha256_json(evidence):
        raise ValueError("campaign_evidence_hash_mismatch")
    if bool(evidence.get("execution_eligible")):
        raise ValueError("campaign_evidence_execution_authority_forbidden")
    if bool(evidence.get("promotion_eligible")):
        raise ValueError("campaign_evidence_promotion_authority_forbidden")
    if str(evidence.get("authority_effect") or "") != "NONE_RESEARCH_ONLY":
        raise ValueError("campaign_evidence_authority_effect_forbidden")
    if int(evidence.get("horizon_seconds") or 0) <= 0:
        raise ValueError("campaign_evidence_invalid_horizon")
    if int(evidence.get("fills") or 0) < 0:
        raise ValueError("campaign_evidence_invalid_fills")


def registry_manifest(receipts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    validated=[]
    seen=set()
    for receipt in receipts:
        validate_campaign_evidence(receipt)
        evidence=dict(receipt["evidence"])
        campaign_id=str(evidence.get("campaign_id") or "")
        if not campaign_id:
            raise ValueError("campaign_evidence_missing_campaign_id")
        if campaign_id in seen:
            raise ValueError("campaign_evidence_duplicate_campaign_id")
        seen.add(campaign_id)
        validated.append({
            "campaign_id":campaign_id,
            "evidence_sha256":str(receipt["evidence_sha256"]),
            "model_id":str(evidence.get("model_id") or ""),
            "horizon_seconds":int(evidence.get("horizon_seconds") or 0),
            "evidence_role":str(evidence.get("evidence_role") or ""),
        })
    validated.sort(key=lambda row:row["campaign_id"])
    body={
        "schema":"hivenance_phase14_campaign_evidence_registry_v1",
        "campaigns":validated,
        "campaign_count":len(validated),
        "authority_effect":"NONE_RESEARCH_ONLY",
        "execution_eligible":False,
        "promotion_eligible":False,
    }
    return {**body,"registry_sha256":_sha256_json(body)}


def verify_registry_manifest(
    manifest: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
) -> None:
    expected=registry_manifest(receipts)
    if dict(manifest) != expected:
        raise ValueError("campaign_evidence_registry_mismatch")


def phase14_campaign_rows(receipts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return validated campaign-level rows for replication diagnostics.

    Evidence stays campaign-separated. This function intentionally does not pool
    trade rows across campaigns.
    """
    rows=[]
    for receipt in receipts:
        validate_campaign_evidence(receipt)
        e=receipt["evidence"]
        rows.append({
            "campaign_id":e["campaign_id"],
            "fills":int(e["fills"]),
            "distinct_symbols":int(e["distinct_symbols"]),
            "distinct_worlds":(None if e.get("distinct_worlds") is None else int(e["distinct_worlds"])),
            "mean_gross_bps":e.get("mean_gross_bps"),
            "median_gross_bps":e.get("median_gross_bps"),
            "mean_net_bps":e.get("mean_net_bps"),
            "median_net_bps":e.get("median_net_bps"),
            "mean_excess_vs_random_bps":e.get("mean_excess_vs_random_bps"),
            "largest_symbol_fraction":e.get("largest_symbol_fraction"),
        })
    return rows
