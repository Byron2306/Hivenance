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

## User Personas
1. **Active Trader** - Wants to monitor and approve trades manually
2. **Passive Investor** - Wants full auto-trade with safety limits

## Core Requirements (Static)
- Trade on Base L2 for minimal gas costs
- Maximum position size: 10% of wallet
- Approval required for trades >$10 (configurable)
- Circuit breaker after 5 consecutive losses
- Maximum 10 trades per hour
- Auto-trade toggle capability

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
- [x] /learning/status.json
- [x] /learning/auto_trade
- [x] /safety/status.json
- [x] /safety/circuit_breaker
- [x] /gas/status.json
- [x] /approvals/pending.json
- [x] /mobile/dashboard.json

### Phase 5: Web UI ✅ (Feb 2026)
- [x] Fixed UI to be accessible in preview
- [x] SIMPLE/GOVERNED mode toggle in UI
- [x] Safety status dashboard
- [x] Learning engine metrics display
- [x] Gas optimizer status
- [x] Worker performance display
- [x] Top performing coins display
- [x] Enable Auto-Trade button
- [x] Refresh button

## Prioritized Backlog

### P0 - Critical (Next Session)
- [ ] Telegram Bot integration for phone notifications
- [ ] SMS authorization via Twilio
- [ ] Mobile-responsive UI dashboard

### P1 - High Priority
- [ ] Real-time profit/loss WebSocket streaming
- [ ] Voice command for trade authorization
- [ ] Push notifications for trade alerts

### P2 - Medium Priority
- [ ] Historical performance charts
- [ ] Backtesting on historical data
- [ ] Multiple wallet support

## Can This System Generate Profit?

### Honest Assessment
**YES, it CAN generate profit IF:**
1. **Gas costs are minimized** ✅ (Base L2: ~$0.001/tx)
2. **High-volatility coins are selected with good timing** - System learns over time
3. **Risk management prevents large drawdowns** ✅ (Circuit breaker, position limits)
4. **Market has sufficient inefficiencies** - Works best in trending markets

**Risk Factors:**
- No trading system guarantees profit
- Small stake sizes mean small absolute profits
- High volatility = high risk both ways
- Market conditions can change

### Expected Performance
- Target win rate: >55% (breakeven at ~50% with proper sizing)
- Target profit factor: >1.2
- Maximum drawdown: 10% before circuit breaker
- Daily loss limit: 5% of wallet

## Next Tasks List
1. Implement Telegram bot for phone authorization
2. Add WebSocket for real-time updates to mobile
3. Create responsive mobile UI dashboard
4. Add historical performance visualization
5. Implement voice command support (optional)

---
*Last Updated: Feb 2026*
*Version: 2.1.0 - UI Fix & Governance Mode Release*
