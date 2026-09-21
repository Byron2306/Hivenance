from __future__ import annotations

import argparse
import json
from pathlib import Path

from strategies.relative_value_lab.campaign_evidence_registry import (
    CampaignEvidence,
    phase14_campaign_rows,
    registry_manifest,
)
from strategies.relative_value_lab.phase14_scientific_gate import (
    independent_campaign_replication_summary,
)


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--seed",default="docs/HIVENANCE_PHASE14_RSI_CAMPAIGN_EVIDENCE_SEED_V1.json")
    parser.add_argument("--out",default="data/phase14_rsi_campaign_evidence_registry.json")
    args=parser.parse_args()

    seed=json.loads(Path(args.seed).read_text())
    receipts=[CampaignEvidence(**row).receipt() for row in seed["campaigns"]]
    manifest=registry_manifest(receipts)
    rows=phase14_campaign_rows(receipts)
    court=independent_campaign_replication_summary(rows)

    result={
        "schema":"hivenance_phase14_rsi_campaign_evidence_bundle_v1",
        "seed_schema":seed.get("schema"),
        "receipts":receipts,
        "registry":manifest,
        "replication_court":court,
        "authority_effect":"NONE_RESEARCH_ONLY",
        "execution_eligible":False,
        "promotion_eligible":False,
    }
    out=Path(args.out)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("HIVENANCE_PHASE14_CAMPAIGN_REGISTRY")
    print("campaigns=",manifest["campaign_count"])
    print("registry_sha256=",manifest["registry_sha256"])
    print("classification=",court["classification"])
    print("execution_eligible=False")
    print("promotion_eligible=False")
    print("out=",out)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
