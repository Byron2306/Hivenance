from __future__ import annotations

from typing import Any, Mapping, Sequence

from .queen_input_v2 import (
    QueenExtensionChannel,
    extension_channel,
)


def _roots_from_nodes(nodes: Sequence[Any], family: str) -> tuple[str, ...]:
    roots = {
        root
        for node in nodes
        if str(getattr(node, "family", "")) == str(family)
        for root in tuple(getattr(node, "evidence_roots", ()) or ())
    }
    return tuple(sorted(roots))


def queen_extensions_from_cycle(
    *,
    cycle: Any,
    research_context: Mapping[str, Any] | None = None,
) -> dict[str, QueenExtensionChannel]:
    view = getattr(cycle, "queen_view", None)
    nodes = tuple(getattr(view, "nodes", ()) or ())
    context = dict(research_context or {})

    statistical = None
    learning = getattr(cycle, "learning", {})
    if isinstance(learning, Mapping):
        statistical = learning.get("probabilistic_synthesis")
    if statistical is None and isinstance(context.get("statistics"), Mapping):
        statistical = context.get("statistics")

    regime = context.get("regime") if isinstance(context.get("regime"), Mapping) else None
    external = context.get("external") if isinstance(context.get("external"), Mapping) else None
    calibration = context.get("calibration") if isinstance(context.get("calibration"), Mapping) else None

    out: dict[str, QueenExtensionChannel] = {}

    if isinstance(statistical, Mapping):
        out["STATISTICAL_SYNTHESIS"] = extension_channel(
            name="STATISTICAL_SYNTHESIS",
            state="PRESENT",
            payload=dict(statistical),
            evidence_roots=_roots_from_nodes(nodes, "STATISTICAL_SYNTHESIS"),
        )

    if isinstance(regime, Mapping) and regime:
        roots = tuple(sorted({
            str(root)
            for root in tuple(regime.get("evidence_roots") or ())
            if str(root).startswith("sha256:")
        }))
        out["REGIME_CONTEXT"] = extension_channel(
            name="REGIME_CONTEXT",
            state="PRESENT",
            payload=dict(regime),
            evidence_roots=roots,
        )

    if isinstance(external, Mapping) and external:
        roots = tuple(sorted({
            str(root)
            for item in tuple(external.get("features") or ())
            if isinstance(item, Mapping)
            for root in (item.get("evidence_root"),)
            if root and str(root).startswith("sha256:")
        }))
        out["EXTERNAL_STATISTICS"] = extension_channel(
            name="EXTERNAL_STATISTICS",
            state="PRESENT",
            payload=dict(external),
            evidence_roots=roots,
        )

    if isinstance(calibration, Mapping) and calibration:
        roots = tuple(sorted({
            str(root)
            for root in tuple(calibration.get("evidence_roots") or ())
            if str(root).startswith("sha256:")
        }))
        out["CALIBRATION_CONTEXT"] = extension_channel(
            name="CALIBRATION_CONTEXT",
            state="PRESENT",
            payload=dict(calibration),
            evidence_roots=roots,
        )

    if context:
        roots = tuple(sorted({
            str(root)
            for family in ("statistics", "regime", "external", "calibration")
            for root in tuple((context.get(family) or {}).get("evidence_roots") or ())
            if str(root).startswith("sha256:")
        }))
        out["RESEARCH_CONTEXT"] = extension_channel(
            name="RESEARCH_CONTEXT",
            state="PRESENT",
            payload=context,
            evidence_roots=roots,
        )

    return out
