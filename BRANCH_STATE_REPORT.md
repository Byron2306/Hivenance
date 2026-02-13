# Branch State Report (VAMP / Hivenance)

## Executive summary
- The UI that still contains **full SwarmGuard + BuzzCoin integration**, app logo assets, and bee-based agent output rendering is the **Flask UI served by `UIAgent`** (mounted at `/api/` through FastAPI).
- The React frontend is currently only an iframe wrapper around that Flask UI.
- New trading modules (Learning Engine, Gas Optimizer, Adaptive Coin Selector, Safety System) are integrated in coordinator startup.
- I fixed the learning-engine save-state race and repaired the temporary export test to align with current UI internals.
- I audited corrupted DB artifacts and validated current DB integrity.

## Which UI has your full SwarmGuard/BuzzCoin/icon/bee integration?

### ✅ Fully integrated: Flask UI (`agents/ui_agent.py`)
- SwarmGuard page and APIs are present (`/swarmguard`, `/swarmguard.json`, rules/risk endpoints, reset endpoint).
- BuzzCoin page and APIs are present (`/buzz`, `/buzz/status`, `/buzz/ledger`, `/buzz/leaderboard`, `/buzz/credit`, `/buzz/recent`).
- App logo and visual assets are embedded in dashboard HTML (`/static/hivenance_logo.png`, `/static/swarmguard.png`, `/static/buzzcoin.png`).
- Bee agent output system is present (bee grid/card styling, bee ordering, buzz message mapping).

### ⚠️ Wrapper-only: React frontend (`frontend/src/App.js`)
- React app currently renders only a fullscreen iframe to `${REACT_APP_BACKEND_URL}/api/`.
- It does not directly implement SwarmGuard/BuzzCoin/bee logic itself.

### ⚠️ Desktop UI is separate and not the authoritative integrated surface
- Desktop renderer has its own icon asset usage, but the branch’s full SwarmGuard/BuzzCoin + bee-output integration lives in Flask UI code.

## Current architecture state

### 1) UI stack has shifted away from a standalone React UI
- `frontend/src/App.js` renders a full-screen iframe to `${REACT_APP_BACKEND_URL}/api/`.
- `backend/server.py` explicitly mounts the “ORIGINAL Hivenance Flask UI” at `/api/`.
- `UIAgent` owns dashboard views and the majority of app UX/API routes.

**Impact:** If your original UI was React-native, this branch currently presents Flask-first UI behavior.

### 2) Rigorous trading/profit modules integrated in coordinator
- `SwarmCoordinator` initializes:
  - `LearningEngine`
  - `GasOptimizer`
  - `AdaptiveCoinSelector`
  - `FoolproofSafetySystem`

### 3) Learning/gas/safety/adaptive controls exposed in UI API
`agents/ui_agent.py` includes endpoints for:
- Learning status/coin/risk/auto-trade/approvals
- Safety status/audit/circuit breaker
- Gas status/batch execution
- Adaptive selector status/rotation
- Mobile consolidated dashboard

## Fixes made in this pass

### A) Learning-engine save-state race fixed
- Root issue: `_save_state()` iterated over mutable dicts while other threads could mutate them.
- Fix: take lock-protected snapshots (`list(self.coin_performance.items())`, `list(self.worker_performance.items())`) and iterate snapshots for DB writes.

### B) tmp export test repaired/investigated
- Root issue: `scripts/tmp_export_test.py` referenced removed private attributes (`ui._trade_buffer`, `ui._log_buffer`) and an endpoint not present anymore (`/debug/export_buffers`).
- Fix: converted it into a pytest-friendly smoke test that:
  - creates a minimal dummy coordinator,
  - instantiates `UIAgent`,
  - validates existing endpoints (`/metrics.json`, `/tape.json`, `/audit.json`).

## Corrupted DB audit

### Findings
- Corruption artifact files found: **203** total in `data/`:
  - 73 main DB backups (`swarm_data.db.corrupt.*`)
  - 65 SHM backups (`swarm_data.db-shm.corrupt.*`)
  - 65 WAL backups (`swarm_data.db-wal.corrupt.*`)
- Timestamp range in filenames indicates a concentrated failure window:
  - first: `1769659438` (`2026-01-29T04:03:58Z`)
  - last: `1769684021` (`2026-01-29T10:53:41Z`)
- Current DB health checks (`PRAGMA integrity_check`) report **ok** for:
  - `data/swarm_data.db`
  - `data/learning.db`
  - `data/test.db`
  - `data/test_learning.db`

### Interpretation
- The large number of `.corrupt.*` files strongly suggests repeated recovery/rotation events in a short time window.
- Present DB files are currently readable and pass integrity checks, but the event history indicates prior write instability or abrupt process termination patterns.

## Test & validation report (VAMP-wide check)

### Backend comprehensive suite
Command:
- `python3 backend_test.py`

Result:
- **13/13 tests passed**.
- Includes learning/gas/safety/adaptive modules, coordinator integration, and API route registration.

### Repo pytest sweep
Command:
- `pytest -q`

Result:
- Now passes after repairing `scripts/tmp_export_test.py`.

### Build checks
Commands:
- `npm run build` in `frontend/` ✅
- Desktop UI removed from repository in latest hardening pass.

Results:
- Frontend build succeeds.
- Desktop build section deprecated after desktop UI removal.

### Python compile sanity
Command:
- `python3 -m compileall agents backend swarmguard_service buzzservice main.py SWARM.py`

Result:
- Completed successfully.

## Remaining potential conflicts/redundancies
1. React-vs-Flask product-surface ambiguity remains (React is wrapper; Flask is real UX).
2. Multiple launch surfaces (`run_ui_simple.py`, `run_ui_server.py`, FastAPI mount) still increase drift risk, though desktop shell has been removed.
3. Corrupt-file retention policy is undefined; `data/` can become noisy quickly.

## Strategy alignment: high-volatility, low-stakes philosophy
- The branch can be tuned to your target style (small notional, frequent high-volatility movers) while retaining layered risk controls.
- Adaptive selector defaults were widened to support 20%–100% daily-range candidates via configurable bounds (`adaptive_min_volatility_pct`, `adaptive_max_volatility_pct`) and to tolerate wider spreads for micro-cap movers.
- Risk layers (SwarmGuard, Kill Switch, Safety, Learning approvals) remain in place to limit downside during volatile regimes.

### Important caveat on “guaranteed profit”
- No trading system can guarantee profit in live markets.
- This branch is better framed as a **risk-bounded incremental system**: it can improve expected outcomes with policy gating and small position sizing, but still has market/latency/liquidity tail risk.

## Queen Telegram trade-confirmation layer
- Added optional QUEEN Telegram confirmation gate before BUY/SELL execution intent submission.
- When enabled, the coordinator sends a Telegram message with request ID and waits for `/approve <id>` or `/reject <id>` from configured chat.
- Timeouts and Telegram delivery failures are controlled by `queen_telegram_fail_open` (fail-closed by default).
- New config fields: `queen_telegram_confirm_enabled`, `queen_telegram_confirm_timeout_sec`, `queen_telegram_fail_open`, `telegram_bot_token`, `telegram_chat_id`.

## Swap vs sell: what is most effective?
- In this branch, with on-chain enabled and CEX fallback, **swap-based routing is usually best for continuous repositioning** among volatile targets (fewer idle periods, more tactical rotation).
- **Selling to quote/stable is best when risk-off conditions are detected** (SwarmGuard veto pressure, kill-switch throttle/halt risk, spread/liquidity deterioration).
- Practical recommendation: use swaps as the default tactic in favorable regimes, and force sell-to-stable behavior under governance risk flags.

## UI clutter cleanup plan (practical)
1. Consolidate to one primary dashboard entrypoint (Flask `/api/`) and demote duplicate launch paths.
2. Move advanced control cards (risk map/rules/ledger internals) behind an “Advanced” accordion.
3. Collapse low-frequency cards into tabbed sections (Governance, Safety, Execution, Diagnostics).
4. Keep Bee grid + top KPIs always visible; move deep logs/audit tables to dedicated subpages.
5. Remove duplicate status text blocks that repeat buzz events already shown in Bee cards.
6. Introduce a “focus mode” for trading actions (BUY/SELL/approve) with minimal distractions.

## Is SwarmGuard + BuzzCoin actually beneficial?
- **SwarmGuard:** yes, it adds concrete benefit via deterministic veto/throttle/size-cap policy controls and rulebook governance.
- **BuzzCoin:** beneficial for accountability/game-theory signaling (stake/slash/reward), but optional for pure execution performance.
- Net: keep SwarmGuard mandatory; keep BuzzCoin optional/toggleable depending on whether governance incentives are a priority for your ops style.

## Learning every cycle + worker race integration
- Learning engine now ingests **per-cycle feedback** from council outcomes (not only post-trade PnL).
- Coordinator calls `learning.record_cycle_feedback(...)` every strategy cycle with regime snapshot, worker proposals, council decision, and buzz cycle stake snapshot.
- This allows worker weights to adapt from race outcomes and BUZZ stake pressure, improving strategy adaptation speed between fills.

## BuzzCoin + leaderboard usefulness for learning/trading
- Practical integration path now in place: BUZZ cycle stake snapshots can reinforce/de-emphasize worker base weights in learning.
- This makes leaderboard/stake outcomes actionable (not just visual) by feeding worker weighting priors.
- Recommendation: keep stake-impact bounded (already capped) to avoid overfitting to short-term governance noise.

## OpenClaw removal + UI cleanup status
- OpenClaw runtime decisioning removed from coordinator (QUEEN governance only).
- `/openclaw/chat` now returns `410 openclaw_removed` for compatibility.
- Dashboard clutter reduced by removing OpenClaw chat card and adding `Focus Mode` + `Advanced Cards` toggles.

## Integrity/breach check + external hardening status
- Executed `git fsck --full` with no repository object corruption findings.
- Added security hardening notes in `SECURITY_HARDENING.md`.
- Hardened backend CORS policy from wildcard to explicit allowlist via env.
- Removed hardcoded 1inch key from settings (env-driven only).
