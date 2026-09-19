#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args():
    p=argparse.ArgumentParser(description="Report HiveNance relative-value ablation autopsy")
    p.add_argument("--input",type=Path,default=Path("data/pollen_paper_ablation.json"))
    p.add_argument("--top",type=int,default=12)
    return p.parse_args()


def main()->int:
    args=parse_args()
    payload=json.loads(args.input.read_text(encoding="utf-8"))
    settled=int(payload.get("settled_count") or 0)
    books={row["variant_id"]:row for row in payload.get("books",[])}
    findings=payload.get("organ_findings",[])
    deltas=payload.get("deltas_vs_full_hive",[])

    print("HiveNance Ablation Autopsy")
    print(f"settled={settled}")
    full=books.get("FULL_HIVE")
    control=books.get("CONTROL_ALL")
    if full:
        print(
            f"FULL_HIVE n={full['selected_count']} net={full['cumulative_net_bps']:+.3f}bps "
            f"mean={full['mean_net_bps']:+.3f} win={full['win_rate']:.3f} "
            f"dd={full['max_drawdown_bps']:.3f}"
        )
    if control:
        print(
            f"CONTROL_ALL n={control['selected_count']} net={control['cumulative_net_bps']:+.3f}bps "
            f"mean={control['mean_net_bps']:+.3f} win={control['win_rate']:.3f} "
            f"dd={control['max_drawdown_bps']:.3f}"
        )

    print("\nORGAN UTILITY")
    order={
        "HARMFUL_CANDIDATE_THIS_SAMPLE":0,
        "ZERO_SELECTION_EFFECT":1,
        "NO_NET_VALUE_THIS_SAMPLE":2,
        "USEFUL_CANDIDATE_THIS_SAMPLE":3,
        "UNRESOLVED_TOO_FEW_CHANGED_CASES":4,
    }
    for row in sorted(findings,key=lambda x:(order.get(x["utility_status"],9),x["organ_id"])):
        print(
            f"{row['organ_id']:22s} {row['utility_status']:34s} "
            f"changed={row['changed_decisions']:4d} "
            f"Δremove={row['cumulative_net_delta_bps']:+.3f}bps"
        )

    changed=[d for d in deltas if int(d.get("changed_decisions") or 0)>0]
    changed.sort(
        key=lambda d:(
            -float(d.get("cumulative_net_delta_bps") or 0.0),
            -int(d.get("changed_decisions") or 0),
            d.get("variant_id",""),
        )
    )

    print("\nMUTATIONS THAT IMPROVED THIS SAMPLE")
    winners=[d for d in changed if float(d.get("cumulative_net_delta_bps") or 0)>0]
    if not winners:
        print("none yet")
    for row in winners[:max(1,args.top)]:
        print(
            f"{row['variant_id']:30s} "
            f"Δ={row['cumulative_net_delta_bps']:+.3f}bps "
            f"changed={row['changed_decisions']}"
        )

    print("\nMUTATIONS THAT HURT THIS SAMPLE")
    losers=[d for d in changed if float(d.get("cumulative_net_delta_bps") or 0)<0]
    if not losers:
        print("none yet")
    for row in sorted(losers,key=lambda d:float(d.get("cumulative_net_delta_bps") or 0.0))[:max(1,args.top)]:
        print(
            f"{row['variant_id']:30s} "
            f"Δ={row['cumulative_net_delta_bps']:+.3f}bps "
            f"changed={row['changed_decisions']}"
        )

    print("\nNOTE")
    print("These are prospective sample effects, not proof of durable edge. ZERO_SELECTION_EFFECT means")
    print("selection-dead weight in this path/sample, not that the organ lacks audit/safety value.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
