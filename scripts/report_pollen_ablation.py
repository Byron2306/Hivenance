#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from strategies.relative_value_lab.ablation_lab import CONFIRMATORY_V5_VARIANTS


def parse_args():
    p=argparse.ArgumentParser(description="Report HiveNance relative-value ablation autopsy")
    p.add_argument("--input",type=Path,default=Path("data/pollen_paper_ablation.json"))
    p.add_argument("--top",type=int,default=12)
    p.add_argument("--confirmatory-v5",action="store_true",
                   help="Report only the frozen v5 confirmatory slate with hard robustness verdicts")
    p.add_argument("--minimum-confirmatory-n",type=int,default=20)
    return p.parse_args()


def main()->int:
    args=parse_args()
    payload=json.loads(args.input.read_text(encoding="utf-8"))
    settled=int(payload.get("settled_count") or 0)
    books={row["variant_id"]:row for row in payload.get("books",[])}
    findings=payload.get("organ_findings",[])
    deltas=payload.get("deltas_vs_full_hive",[])
    stability={row["variant_id"]:row for row in payload.get("variant_stability",[])}

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
    winners=[]
    degenerate=[]
    for d in changed:
        if float(d.get("cumulative_net_delta_bps") or 0)<=0:
            continue
        book=books.get(d.get("variant_id"))
        if book and book.get("degenerate_select_none"):
            degenerate.append(d)
        else:
            winners.append(d)
    if not winners:
        print("none yet")
    for row in winners[:max(1,args.top)]:
        book=books.get(row["variant_id"],{})
        stab=stability.get(row["variant_id"],{})
        print(
            f"{row['variant_id']:30s} "
            f"Δ={row['cumulative_net_delta_bps']:+.3f}bps "
            f"changed={row['changed_decisions']} "
            f"n={book.get('selected_count',0)} "
            f"select={float(book.get('selection_rate') or 0.0):.3f} "
            f"halves={float(stab.get('first_half_net_bps') or 0.0):+.2f}/"
            f"{float(stab.get('second_half_net_bps') or 0.0):+.2f} "
            f"w/o_best={float(stab.get('net_without_best_pair_bps') or 0.0):+.2f}"
        )

    print("\nDEGENERATE SELECT-NONE RESULTS")
    if not degenerate:
        print("none")
    for row in degenerate[:max(1,args.top)]:
        print(
            f"{row['variant_id']:30s} "
            f"Δ={row['cumulative_net_delta_bps']:+.3f}bps "
            f"changed={row['changed_decisions']} "
            "reason=selected_zero_trades"
        )

    print("\nNON-DEGENERATE ROBUST CANDIDATES")
    robust=[]
    for row in winners:
        book=books.get(row["variant_id"],{})
        stab=stability.get(row["variant_id"],{})
        if (
            int(book.get("selected_count") or 0) >= 5
            and bool(stab.get("both_halves_positive"))
            and bool(stab.get("survives_best_pair_removal"))
        ):
            robust.append(row)
    if not robust:
        print("none in this sample")
    for row in robust[:max(1,args.top)]:
        book=books.get(row["variant_id"],{})
        stab=stability.get(row["variant_id"],{})
        print(
            f"{row['variant_id']:30s} "
            f"Δ={row['cumulative_net_delta_bps']:+.3f}bps "
            f"n={book.get('selected_count',0)} "
            f"pairs+/-={stab.get('positive_pair_count',0)}/{stab.get('negative_pair_count',0)} "
            f"w/o_best={float(stab.get('net_without_best_pair_bps') or 0.0):+.3f}bps"
        )

    print("\nMUTATIONS THAT HURT THIS SAMPLE")
    losers=[d for d in changed if float(d.get("cumulative_net_delta_bps") or 0)<0]
    if not losers:
        print("none yet")
    for row in sorted(losers,key=lambda d:float(d.get("cumulative_net_delta_bps") or 0.0))[:max(1,args.top)]:
        book=books.get(row["variant_id"],{})
        print(
            f"{row['variant_id']:30s} "
            f"Δ={row['cumulative_net_delta_bps']:+.3f}bps "
            f"changed={row['changed_decisions']} "
            f"n={book.get('selected_count',0)} "
            f"select={float(book.get('selection_rate') or 0.0):.3f}"
        )

    print("\nFRAGILE POSITIVE MUTATIONS")
    fragile=[]
    for row in winners:
        stab=stability.get(row["variant_id"],{})
        if not (
            bool(stab.get("both_halves_positive"))
            and bool(stab.get("survives_best_pair_removal"))
        ):
            fragile.append(row)
    if not fragile:
        print("none")
    for row in fragile[:max(1,args.top)]:
        stab=stability.get(row["variant_id"],{})
        print(
            f"{row['variant_id']:30s} "
            f"halves={float(stab.get('first_half_net_bps') or 0.0):+.3f}/"
            f"{float(stab.get('second_half_net_bps') or 0.0):+.3f} "
            f"best={stab.get('best_pair_id')}:{float(stab.get('best_pair_net_bps') or 0.0):+.3f} "
            f"w/o_best={float(stab.get('net_without_best_pair_bps') or 0.0):+.3f}"
        )

    print("\nSELECTOR EQUIVALENCE CLASSES")
    eq=payload.get("selector_equivalence_classes",[])
    aliases=[row for row in eq if len(row.get("variant_ids",[]))>1]
    aliases.sort(key=lambda row:(-len(row.get("variant_ids",[])),row.get("class_id","")))
    if not aliases:
        print("no exact aliases in settled sample")
    for row in aliases[:max(1,args.top)]:
        variants=",".join(row.get("variant_ids",[]))
        print(
            f"{row['class_id']:18s} n={row.get('selected_count',0):4d} "
            f"select={float(row.get('selection_rate') or 0.0):.3f} "
            f"variants={variants}"
        )


    if args.confirmatory_v5:
        print("\nV5 CONFIRMATORY SLATE")
        print("frozen_before_v5_outcomes=true")
        hash_vectors={}
        for eqrow in payload.get("selector_equivalence_classes",[]):
            for vid in eqrow.get("variant_ids",[]):
                hash_vectors[vid]=set(eqrow.get("variant_ids",[]))

        rows=[]
        for vid in CONFIRMATORY_V5_VARIANTS:
            book=books.get(vid)
            stab=stability.get(vid)
            if not book or not stab:
                continue
            n=int(book.get("selected_count") or 0)
            net=float(book.get("cumulative_net_bps") or 0.0)
            mean=float(book.get("mean_net_bps") or 0.0)
            first=float(stab.get("first_half_net_bps") or 0.0)
            second=float(stab.get("second_half_net_bps") or 0.0)
            without_best=float(stab.get("net_without_best_pair_bps") or 0.0)
            positive_pairs=int(stab.get("positive_pair_count") or 0)
            aliases=hash_vectors.get(vid,set())
            blind_alias=any(x.startswith("HASH_") for x in aliases if x != vid)

            if vid in {"CONTROL_ALL","REJECT_ALL","HASH_25","HASH_50"}:
                verdict="CONTROL"
            elif n < int(args.minimum_confirmatory_n):
                verdict="INSUFFICIENT_N"
            elif blind_alias:
                verdict="DATA_BLIND_ALIAS"
            elif net <= 0 or mean <= 0:
                verdict="NEGATIVE"
            elif first <= 0 or second <= 0:
                verdict="TEMPORALLY_FRAGILE"
            elif without_best <= 0:
                verdict="PAIR_CONCENTRATED"
            elif positive_pairs < 2:
                verdict="INSUFFICIENT_PAIR_BREADTH"
            else:
                verdict="SURVIVED_V5_SAMPLE"

            rows.append((verdict,vid,n,net,mean,first,second,without_best,positive_pairs))
        order={
            "SURVIVED_V5_SAMPLE":0,
            "INSUFFICIENT_N":1,
            "TEMPORALLY_FRAGILE":2,
            "PAIR_CONCENTRATED":3,
            "INSUFFICIENT_PAIR_BREADTH":4,
            "DATA_BLIND_ALIAS":5,
            "NEGATIVE":6,
            "CONTROL":7,
        }
        for verdict,vid,n,net,mean,first,second,without_best,positive_pairs in sorted(
            rows,key=lambda r:(order.get(r[0],9),-r[3],r[1])
        ):
            print(
                f"{vid:36s} {verdict:26s} "
                f"n={n:3d} net={net:+.3f} mean={mean:+.3f} "
                f"halves={first:+.2f}/{second:+.2f} "
                f"w/o_best={without_best:+.2f} pairs+={positive_pairs}"
            )

    print("\nNOTE")
    print("These are prospective sample effects, not proof of durable edge. ZERO_SELECTION_EFFECT means")
    print("selection-dead weight in this path/sample, not that the organ lacks audit/safety value.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())