# Hivenance x BEAST Deep Integration

Date: Wednesday, August 5, 2026

## What the real BEAST repo adds

After reading the actual `/home/byron/EdgeK-BEAST` tree, the highest-value mechanisms are not "more AI."
They are:

- explicit artifact classes with maximum authority
- proof-carrying receipts instead of trust-by-result
- local adoption gates where remote evidence is advisory until reproduced
- compute-governor style rung selection
- exact identity binding for reusable compute and KV transport
- durable evidence, trace, and authority stores under `.beast`

The deepest BEAST rule worth importing into Hivenance is:

`observation does not grant authority`

That rule fits Phoenix perfectly.

## Concrete BEAST patterns observed

### 1. Compute Governor

From `docs/compute-governor.md`:

- compute decisions are modeled as rungs
- suppression is forbidden without proof
- shadow evidence is collected before enforcement
- counterfactual savings are not treated as realized savings

Hivenance use:

- Phase 2 should treat every challenger forecast as a rung, not a truth source
- Phase 3 should treat every execution policy as a rung, not a privileged path
- Phase 6 should only consume pre-approved paths whose earlier rungs survived validation

### 2. Crystal and authority taxonomy

From `docs/beast-sensorium-proof-carrying-crystal-plan.md`:

- every artifact class gets a maximum authority
- semantic matches are candidates, not execution proof
- capsules carry bytes and identity, not authority
- runtime evidence is separate from actuators

Hivenance use:

- world-state crystals stay `context_only`
- Commons inference receipts stay `proposal_only`
- Commons verifier receipts stay `verify_only`
- negative capability crystals stay `proposal_only`
- only Phase 6 one-use canary receipts should ever reach bounded execution

### 3. KV transport identity discipline

From `docs/kv-cache-transport.md`:

- only exact engine-native bytes move
- payload identity is checksum-bound
- network transport is explicit, never implied by cache existence

Hivenance use:

- sidecar or Commons feature bundles should never gain meaning merely because they exist
- any future crystal cache should bind model/version/config/schema/repo identity
- memfd or KV-forge style reuse in Hivenance should remain optimization-only, never authority-bearing

### 4. Meta Tool Commons adoption model

From `docs/meta-tool-commons.md`:

- global evidence is a prior
- local evidence is stronger
- adoption defaults to dry-run
- local approval decides whether a candidate becomes usable

Hivenance use:

- remote research can improve priors
- local replay, settlement, and phase gates decide capital relevance
- sidecars should raise candidate richness, not override promotion

## The BEAST stores that matter

The actual `.beast` runtime contains durable stores for:

- `commons-remote/*.sqlite3`
- `evidence/evidence.sqlite3`
- `compute_plane/one_use_authority.sqlite`
- `compute/agent_scheduler_receipts.json`
- `local_trace_ledger.sqlite`
- `operations_console/*.sqlite3`

That matters because it shows BEAST is already organized around:

- evidence durability
- one-use authority
- ledgered decisions
- bounded control surfaces

Hivenance should mirror those ideas with smaller, phase-native objects instead of copying the whole stack.

## What Hivenance already has

Phoenix already contains strong equivalents:

- Phase 1 world-state crystals
- Phase 2 Commons tickets and challenger adoption
- Phase 3 admission receipts, negative capability crystals, and abstention-beat receipts
- Phase 4/5 verifier-pool ticketing
- Phase 6 one-use live canary approval flow
- Phase 7 authority separation

The remaining weakness was that these objects were still more conventional than constitutional.
They existed, but they did not all carry a shared artifact/authority contract.

## Changes now added in this repo

### 1. Shared Commons authority contract

Added:

- `agents/commons_authority.py`

This introduces:

- canonical artifact contracts
- explicit authority rank ordering
- schema/field validation for key Phoenix artifacts
- world-state crystal validation
- authority-bound local adoption boundary objects

### 2. Authority-bound local adoption receipts

Updated:

- `agents/data_store_agent.py`

Commons adoption receipts now embed a structured boundary object that records:

- source schema
- source digest
- artifact class
- maximum authority
- requested authority
- granted authority
- local reproduction verdict
- boundary reasons

If a Commons inference or verifier receipt does not satisfy the contract, Hivenance still stores the evidence but records a rejected local adoption receipt instead of silently treating it as usable.

### 3. Stronger Phase 1 world-state crystals

Updated:

- `strategies/volatility_breakout/observation_swarm.py`

World-state crystals now carry:

- `artifact_class`
- `authority`
- `verification_state`
- `applicability_hash`

That makes them usable as deterministic context objects without implying execution authority.

## Next god-tier upgrades

These are the highest-value follow-ons.

### Phase A: Crystal registry

Add a first-class Hivenance crystal registry with three families:

- market world-state crystals
- thesis capability crystals
- negative capability crystals

Each object should expose:

- artifact class
- max authority
- scope tuple
- code/config digest
- world-state digest
- expiry
- local evidence strength
- drift status

### Phase B: Inference rung ledger

Add a compute-governor style ledger for Phase 2 and 3:

- local baseline
- local challenger
- Commons challenger
- abstain
- simulate-only execution policy

Every forecast and every execution-policy candidate should say:

- what rung produced it
- what lower-cost rung could have been enough
- what evidence would justify promotion

### Phase C: One-way evidence diode

Enforce a single rule everywhere:

`settlement updates evidence, never authority`

That means:

- Phase 2 outcomes update slice posteriors
- Phase 3 outcomes update execution-policy scorecards
- Phase 4/5 outcomes update promotion eligibility
- none of those directly change Phase 6 permission

Phase 6 authority should continue to require a fresh bounded receipt.

### Phase D: Sidecar normalization into crystals

Do not let sidecars dump generic blobs into Phoenix.
Normalize them into one of:

- challenger forecast crystal
- verifier replay crystal
- feature-transform crystal
- negative-case crystal

If a sidecar output cannot be expressed as one of those, it should stay as archived evidence only.

### Phase E: Memfd/KV-forge style local cache

For performance, not authority:

- cache reproducible feature bundles
- cache frozen candidate slices
- cache replay manifests
- optionally materialize large ephemeral crystal payloads in memfd-backed temp storage

But keep these rules:

- cache hit does not equal truth
- cache hit does not equal eligibility
- cache hit does not equal live permission

## Profit impact

This does not magically create profit.
It improves the profit path in a more serious way:

- fewer false positives survive into simulation
- remote research becomes richer without becoming dangerous
- failure causes become reusable objects instead of scattered notes
- promotion logic can become more slice-specific and less hand-wavy
- live capital remains tightly bounded while the upstream research pool gets smarter

The practical effect should be:

`more candidate richness -> stricter local pruning -> cleaner execution-policy competition -> fewer fake edges -> higher chance of genuine post-cost survivors`

## Honest assessment

The real BEAST folder is highly relevant to Hivenance, but not because Phoenix should become BEAST.

The right move is:

- keep Phoenix as the market organism
- import BEAST's artifact, authority, and proof discipline
- use Commons and sidecars to widen search
- let only local validated evidence tighten authority

That is the credible route to "god tier."
Not more models.
Better constitutional structure around the models.
