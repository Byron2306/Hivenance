from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Mapping, Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .harmony_law import (
    HarmonyBeeMessage,
    HarmonyChorusDecision,
    HarmonyLaw,
    HarmonyLawDecision,
    horizon_band,
    make_message_id,
)


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class BeeLineage:
    """Registered evidence lineage.

    Descendants that share a root_lineage_digest remain one independent
    evidentiary lineage for quorum purposes.
    """

    lineage_digest: str
    family: str
    root_lineage_digest: str
    description: str = ""
    parent_lineage_digest: Optional[str] = None
    registered: bool = True
    control: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LineageRegistry:
    """Deterministic anti-clone registry for HiveNance evidence families."""

    def __init__(self, lineages: Sequence[BeeLineage] | None = None) -> None:
        self._lineages: dict[str, BeeLineage] = {}
        for lineage in lineages or ():
            self.register(lineage)

    def register(self, lineage: BeeLineage) -> None:
        if not str(lineage.lineage_digest).startswith("sha256:"):
            raise ValueError("lineage_digest_must_be_sha256_bound")
        if not str(lineage.root_lineage_digest).startswith("sha256:"):
            raise ValueError("root_lineage_digest_must_be_sha256_bound")
        existing = self._lineages.get(lineage.lineage_digest)
        if existing is not None and existing != lineage:
            raise ValueError("lineage_registration_conflict")
        self._lineages[lineage.lineage_digest] = lineage

    def get(self, lineage_digest: str) -> Optional[BeeLineage]:
        return self._lineages.get(lineage_digest)

    def canonical_family_map(self) -> dict[str, str]:
        return {
            digest: lineage.family
            for digest, lineage in self._lineages.items()
            if lineage.registered and not lineage.control
        }

    def root_for(self, lineage_digest: str) -> Optional[str]:
        lineage = self.get(lineage_digest)
        if lineage is None or not lineage.registered or lineage.control:
            return None
        return lineage.root_lineage_digest

    def snapshot(self) -> tuple[BeeLineage, ...]:
        return tuple(self._lineages[key] for key in sorted(self._lineages))


@dataclass(frozen=True)
class WaggleReceipt:
    schema: str
    receipt_id: str
    sequence_number: int
    message_id: str
    hypothesis_id: str
    message_type: str
    family: str
    lineage_digest: str
    root_lineage_digest: Optional[str]
    horizon_band: str
    accepted: bool
    choir_eligible: bool
    independent_vote_eligible: bool
    authority_effect: str
    law_decision_id: str
    violations: tuple[str, ...]
    warnings: tuple[str, ...]
    previous_receipt_digest: Optional[str]
    receipt_digest: str
    world_state_id: str
    world_state_hash: str
    evidence_root: str
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WaggleChorusSnapshot:
    schema: str
    snapshot_id: str
    hypothesis_id: str
    world_state_id: str
    message_ids: tuple[str, ...]
    accepted_message_ids: tuple[str, ...]
    refused_message_ids: tuple[str, ...]
    independent_root_lineages: tuple[str, ...]
    dissent_message_ids: tuple[str, ...]
    abandoned: bool
    alarmed: bool
    bands_present: tuple[str, ...]
    authority_effect: str
    harmony_decision_id: str
    violations: tuple[str, ...]
    warnings: tuple[str, ...]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WaggleProtocol:
    """Harmony-gated append-only bee communication bus.

    The protocol does not predict markets or grant authority. It records typed
    testimony, applies Harmony Law before admission, preserves dissent and
    abandonment, and collapses descendant/clone lineages to one independent
    root vote per hypothesis + horizon band + world state.
    """

    version = "hivenance.waggle_protocol.v1"

    def __init__(
        self,
        *,
        registry: LineageRegistry,
        harmony_law: HarmonyLaw | None = None,
    ) -> None:
        self.registry = registry
        self.harmony_law = harmony_law or HarmonyLaw(
            registered_lineages=registry.canonical_family_map()
        )
        self._messages: list[HarmonyBeeMessage] = []
        self._receipts: list[WaggleReceipt] = []
        self._receipt_by_message: dict[str, WaggleReceipt] = {}
        self._independent_vote_keys: set[tuple[str, str, str, str]] = set()

    @staticmethod
    def build_message(
        *,
        bee_id: str,
        family: str,
        lineage_digest: str,
        message_type: str,
        scope: str,
        hypothesis_id: str,
        world_state_id: str,
        world_state_hash: str,
        observed_at_ms: int,
        evidence_root: str,
        horizon_seconds: Optional[int] = None,
        direction: str = "ABSTAIN",
        expected_move_bps: Optional[float] = None,
        uncertainty: Optional[float] = None,
        independent_claimed: bool = False,
        control: bool = False,
        pulse_type: Optional[str] = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> HarmonyBeeMessage:
        identity_payload = {
            "bee_id": bee_id,
            "family": family,
            "lineage_digest": lineage_digest,
            "message_type": message_type,
            "scope": scope,
            "hypothesis_id": hypothesis_id,
            "world_state_id": world_state_id,
            "world_state_hash": world_state_hash,
            "observed_at_ms": int(observed_at_ms),
            "evidence_root": evidence_root,
            "horizon_seconds": horizon_seconds,
            "direction": direction,
            "expected_move_bps": expected_move_bps,
            "uncertainty": uncertainty,
            "independent_claimed": independent_claimed,
            "control": control,
            "pulse_type": pulse_type,
            "metadata": dict(metadata or {}),
        }
        return HarmonyBeeMessage(
            message_id=make_message_id(identity_payload),
            bee_id=bee_id,
            family=family,
            lineage_digest=lineage_digest,
            message_type=message_type,
            scope=scope,
            hypothesis_id=hypothesis_id,
            world_state_id=world_state_id,
            world_state_hash=world_state_hash,
            observed_at_ms=int(observed_at_ms),
            evidence_root=evidence_root,
            horizon_seconds=horizon_seconds,
            direction=direction,
            expected_move_bps=expected_move_bps,
            uncertainty=uncertainty,
            independent_claimed=independent_claimed,
            control=control,
            pulse_type=pulse_type,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
            metadata=dict(metadata or {}),
        )

    def publish(
        self,
        message: HarmonyBeeMessage,
        *,
        current_world_state_id: str,
        current_world_state_hash: str,
        now_ms: int,
    ) -> WaggleReceipt:
        if message.message_id in self._receipt_by_message:
            return self._receipt_by_message[message.message_id]

        decision = self.harmony_law.validate_message(
            message,
            current_world_state_id=current_world_state_id,
            current_world_state_hash=current_world_state_hash,
            now_ms=now_ms,
        )
        warnings = list(decision.warnings)
        violations = list(decision.violations)

        lineage = self.registry.get(message.lineage_digest)
        root = self.registry.root_for(message.lineage_digest)
        independent_vote_eligible = bool(decision.independent_vote_eligible and root)

        # One independent root vote per hypothesis, horizon band and world state.
        # Descendant messages remain visible testimony.
        if independent_vote_eligible and root is not None:
            vote_key = (
                message.hypothesis_id,
                horizon_band(message.horizon_seconds),
                message.world_state_id,
                root,
            )
            if vote_key in self._independent_vote_keys:
                independent_vote_eligible = False
                warnings.append("clone_or_descendant_vote_collapsed")
            else:
                self._independent_vote_keys.add(vote_key)

        if lineage is not None and lineage.family != message.family:
            # Harmony Law catches this for registered independence claims. The
            # bus also refuses mismatched testimony when independence was not
            # claimed, because lineage identity itself must remain truthful.
            violations.append("lineage_family_mismatch")
            independent_vote_eligible = False

        accepted = decision.accepted and not violations
        choir_eligible = accepted and decision.choir_eligible
        sequence_number = len(self._receipts) + 1
        previous_digest = self._receipts[-1].receipt_digest if self._receipts else None

        body = {
            "sequence_number": sequence_number,
            "message": message.to_dict(),
            "law_decision_id": decision.decision_id,
            "accepted": accepted,
            "choir_eligible": choir_eligible,
            "independent_vote_eligible": independent_vote_eligible,
            "root_lineage_digest": root,
            "violations": sorted(set(violations)),
            "warnings": sorted(set(warnings)),
            "previous_receipt_digest": previous_digest,
        }
        receipt_digest = _digest(body)
        receipt = WaggleReceipt(
            schema="hivenance_waggle_receipt_v1",
            receipt_id="wgr_" + receipt_digest.split(":", 1)[1][:24],
            sequence_number=sequence_number,
            message_id=message.message_id,
            hypothesis_id=message.hypothesis_id,
            message_type=message.message_type,
            family=message.family,
            lineage_digest=message.lineage_digest,
            root_lineage_digest=root,
            horizon_band=horizon_band(message.horizon_seconds),
            accepted=accepted,
            choir_eligible=choir_eligible,
            independent_vote_eligible=independent_vote_eligible,
            authority_effect=decision.authority_effect,
            law_decision_id=decision.decision_id,
            violations=tuple(sorted(set(violations))),
            warnings=tuple(sorted(set(warnings))),
            previous_receipt_digest=previous_digest,
            receipt_digest=receipt_digest,
            world_state_id=message.world_state_id,
            world_state_hash=message.world_state_hash,
            evidence_root=message.evidence_root,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )
        self._messages.append(message)
        self._receipts.append(receipt)
        self._receipt_by_message[message.message_id] = receipt
        return receipt

    def chorus_snapshot(
        self,
        *,
        hypothesis_id: str,
        current_world_state_id: str,
        current_world_state_hash: str,
        now_ms: int,
        requested_global_direction: bool = False,
    ) -> WaggleChorusSnapshot:
        messages = [
            message
            for message, receipt in zip(self._messages, self._receipts)
            if message.hypothesis_id == hypothesis_id
            and receipt.choir_eligible
            and message.world_state_id == current_world_state_id
        ]

        harmony = self.harmony_law.validate_chorus(
            messages,
            current_world_state_id=current_world_state_id,
            current_world_state_hash=current_world_state_hash,
            now_ms=now_ms,
            requested_global_direction=requested_global_direction,
        )

        receipts = [
            receipt
            for receipt in self._receipts
            if receipt.hypothesis_id == hypothesis_id
            and receipt.world_state_id == current_world_state_id
        ]
        by_message = {receipt.message_id: receipt for receipt in receipts}
        independent_roots = sorted({
            receipt.root_lineage_digest
            for receipt in receipts
            if receipt.accepted
            and receipt.independent_vote_eligible
            and receipt.root_lineage_digest
        })
        message_by_id = {message.message_id: message for message in self._messages}
        dissent_ids = tuple(
            message_id for message_id in harmony.dissent_message_ids
            if message_id in message_by_id
        )
        accepted_messages = [
            message_by_id[message_id]
            for message_id in harmony.accepted_message_ids
            if message_id in message_by_id
        ]
        abandoned = any(message.message_type == "ABANDON" for message in accepted_messages)
        alarmed = any(
            message.message_type == "ALARM"
            or message.pulse_type in {"ALARM_PULSE", "FREEZE_PULSE"}
            for message in accepted_messages
        )

        warnings = list(harmony.warnings)
        violations = list(harmony.violations)
        if abandoned:
            warnings.append("hypothesis_abandoned")
        if alarmed:
            warnings.append("active_alarm_or_freeze")

        authority_effect = harmony.authority_effect
        if alarmed:
            authority_effect = "REDUCE_OR_FREEZE_ONLY"

        body = {
            "hypothesis_id": hypothesis_id,
            "world_state_id": current_world_state_id,
            "message_ids": [receipt.message_id for receipt in receipts],
            "independent_roots": independent_roots,
            "dissent": list(dissent_ids),
            "abandoned": abandoned,
            "alarmed": alarmed,
            "harmony_decision_id": harmony.decision_id,
            "violations": sorted(set(violations)),
            "warnings": sorted(set(warnings)),
        }
        snapshot_digest = _digest(body)
        return WaggleChorusSnapshot(
            schema="hivenance_waggle_chorus_snapshot_v1",
            snapshot_id="wcs_" + snapshot_digest.split(":", 1)[1][:24],
            hypothesis_id=hypothesis_id,
            world_state_id=current_world_state_id,
            message_ids=tuple(receipt.message_id for receipt in receipts),
            accepted_message_ids=tuple(harmony.accepted_message_ids),
            refused_message_ids=tuple(harmony.refused_message_ids),
            independent_root_lineages=tuple(independent_roots),
            dissent_message_ids=dissent_ids,
            abandoned=abandoned,
            alarmed=alarmed,
            bands_present=tuple(harmony.bands_present),
            authority_effect=authority_effect,
            harmony_decision_id=harmony.decision_id,
            violations=tuple(sorted(set(violations))),
            warnings=tuple(sorted(set(warnings))),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )

    def receipts(self) -> tuple[WaggleReceipt, ...]:
        return tuple(self._receipts)

    def messages(self) -> tuple[HarmonyBeeMessage, ...]:
        return tuple(self._messages)
