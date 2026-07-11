# Crypto Trading Agentic AI System - PRD

## Original Problem Statement
User wants a foolproof governance layer crypto agentic AI system that:
- Works within the philosophy of high volatility, low stakes
- Buys volatile small coins while knowing trends
- Actually makes trades and profits
- Saves gas costs (minimize transaction fees)
- Allows phone communication with Queen for trade authorization
- Has full auto-trade toggle capability
- Learns and adapts over time
- **Flexible governance modes** - SIMPLE (fast) vs GOVERNED (safe)

## Architecture Overview

### Core Components
1. **SwarmCoordinator** - Central orchestrator managing all agents
2. **GovernanceQueen** - Decision-making authority with SVS scoring
3. **StrategyCouncil** - Aggregates worker proposals
4. **Strategy Workers** (SMA, RSI, Breakout, Momentum) - Signal generators
5. **RegimeOracle** - Market regime detection
6. **KillSwitch** - Emergency halt mechanism
7. **SwarmGuard** - Policy enforcement

### NEW Components (Implemented Jan 2026)
1. **Learning Engine** (`learning_engine.py`)
   - Tracks profit margins per coin with decay-weighted history
   - Adaptive strategy weights based on performance
   - Worker performance scoring and automatic rebalancing
   - Trade outcome recording and analysis

2. **Gas Optimizer** (`gas_optimizer.py`)
   - Base L2 exclusive (~$0.001 per tx vs $3 on mainnet)
   - Trade batching for small orders
   - Gas price monitoring and limits
   - 95%+ gas savings vs Ethereum mainnet

3. **Adaptive Coin Selector** (`adaptive_coin_selector.py`)
   - Profit-first coin selection (not just volatility)
   - Historical performance-weighted scoring
   - Regime-aligned opportunity detection
   - Automatic rotation based on profitability

4. **Safety System** (`safety_system.py`)
   - 8-layer multi-layer trade validation
   - Circuit breaker for consecutive losses
   - Position limits based on wallet size
   - Comprehensive audit trail

## Governance Modes (NEW - Feb 2026)

### SIMPLE Mode ⚡
- Fast execution with minimal checks
- Skip council votes for quick decisions
- Reduced validation layers
- Best for: Trending markets, experienced users

### GOVERNED Mode 🛡️
- Full safety validation pipeline
- All 8 validation layers active
- Council approval required
- Best for: Volatile markets, risk-averse users

**Toggle via UI or API:** `POST /api/mode {"mode": "SIMPLE|GOVERNED"}`

## What's Been Implemented

### Phase 1: Learning Core ✅
- [x] Profit margin tracking per coin
- [x] Adaptive strategy weights
- [x] Worker performance scoring
- [x] Trade outcome recording
- [x] Decay-weighted historical scoring

### Phase 2: Gas Optimization ✅
- [x] Base L2 primary network
- [x] Trade batching ($5 threshold)
- [x] Gas efficiency validation
- [x] Cost comparison tracking

### Phase 3: Safety System ✅
- [x] Multi-layer validation (8 layers)
- [x] Circuit breaker mechanism
- [x] Position limits
- [x] Audit trail
- [x] Rate limiting

### Phase 4: API Endpoints ✅
- [x] /api/status - Main status endpoint
- [x] /api/mode - Governance mode toggle
- [x] /api/auto_trade - Auto-trade toggle
- [x] /api/safety/reset - Circuit breaker reset
- [x] /api/ws - WebSocket real-time updates

### Phase 5: WebSocket Implementation ✅ (Feb 2026)
- [x] Real-time status broadcasting
- [x] Mode change events
- [x] Trade event streaming
- [x] Alert system
- [x] Auto-reconnection support

### Phase 6: UI Dashboard ⚠️ (Feb 2026)
- [x] Original Flask dashboard with bee agents, oracles, strategy workers
- [x] Governance mode toggle (SIMPLE/GOVERNED)
- [x] Safety status display
- [x] Learning engine metrics
- [x] Gas optimizer stats
- [ ] **BLOCKED: Platform CDN caching issue** - External preview caching old UI version

## Known Issues

### Platform CDN Cache Issue
- **Status:** ACTIVE BLOCKER
- **Description:** The platform's CDN/proxy is caching an old version of the UI
- **Impact:** External preview URL shows simplified "Hive Trading System" instead of original Flask dashboard
- **Local status:** Works correctly - original dashboard accessible at localhost:8001/api/
- **Resolution:** Waiting for platform cache to expire, or need platform team intervention

## Wallet Setup Status
- **WalletConnect:** Configured with project ID
- **Wallet Address:** NOT CONNECTED - User needs to connect wallet
- **Network:** Configured for Kraken exchange, Base L2 for on-chain

## Prioritized Backlog

### P0 - Critical (Current Blockers)
- [ ] **Platform cache issue** - Need cache invalidation for UI to show correctly
- [ ] Wallet connection setup

### P1 - High Priority
- [ ] Telegram Bot integration for phone notifications
- [ ] WebSocket integration in UI (frontend needs update)
- [ ] Mobile-responsive dashboard

### P2 - Medium Priority
- [ ] Real-time trade streaming display
- [ ] Historical performance charts
- [ ] Voice command support

## Files of Reference
- `/app/backend/server.py` - FastAPI server with WebSocket support
- `/app/agents/ui_agent.py` - Original Flask dashboard with bee agents
- `/app/agents/learning_engine.py` - Adaptive learning system
- `/app/agents/safety_system.py` - Multi-layer validation
- `/app/agents/gas_optimizer.py` - Gas optimization
- `/app/config/settings.yaml` - System configuration

---
*Last Updated: Feb 2026*
*Version: 2.2.0 - WebSocket & UI Update (CDN cache blocked)*
