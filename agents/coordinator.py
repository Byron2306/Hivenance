import time
import logging
import threading
import os
from agents.market_data import MarketData, CoinGeckoData, SentimentData, TrendAnalysis, KrakenMarketData
from agents.strategy import SMACrossoverStrategy, RSIStrategy, MACDStrategy
from agents.execution import BinanceTrader, KrakenTrader
from agents.wallet_monitor import WalletMonitor
from agents.kill_switch import KillSwitchAgent
from agents.swarmguard import SwarmGuard
from agents.coin_selector import CoinSelector
from strategies.volatility_breakout.observation_swarm import ObservationSwarmAgent
from strategies.volatility_breakout.hypothesis_swarm import HypothesisSwarmAgent
from strategies.volatility_breakout.execution_lab import ExecutionLabAgent
from strategies.volatility_breakout.validation_lab import ValidationLabAgent
from strategies.volatility_breakout.shadow_lab import ShadowFlightAgent
from agents.logging_analytics import setup_logging, LoggingAnalyticsAgent
from agents.ui_agent import UIAgent
from agents.network_agent import NetworkAgent
from agents.data_store_agent import DataStoreAgent
from agents.performance_agent import PerformanceAgent
from agents.security_agent import SecurityAgent
from agents.openclaw import OpenClawAgent
from agents.oracle_regime import RegimeOracle
from agents.council import StrategyCouncil
from agents.nurse import NurseAgent
from agents.queen import GovernanceQueen
from agents.dex_margin_oracle import DexMarginOracle
from agents.trade_executors import build_executor_registry
from agents.public_bot_bridge import PublicBotBridge
from agents.pair_protections import PairProtectionEvaluator
from agents.hummingbot_lifecycle import HummingbotExecutorLifecycle
from agents.public_bot_backtesting import PublicBotBacktestBridge
from agents.market_making_advisors import MarketMakingAdvisorSet
from agents.research_architecture import ResearchArchitectureRegistry
from agents.config_agent import ConfigAgent
from agents.event_spine import EventSpineAgent
from agents.evidence_registry import EvidenceRegistryAgent
from agents.ml_research_lab import MLResearchLabAgent
from agents.execution_parity import ExecutionParityAgent
from agents.signal_marketplace import SignalMarketplaceAgent
from agents.phoenix_authority import PhoenixAuthorityGuard
from agents.phase0_governance import phase0_snapshot
from agents.strategy_workers import (
    SMAWorker,
    RSIWorker,
    BreakoutWorker,
    MomentumWorker,
    BollingerWorker,
    SupertrendWorker,
    VolatilityExpansionWorker,
    ExitRiskWorker,
    RSI2Worker,
    ProtectionWorker,
    LatencyTrackerWorker,
)
from typing import Optional, Dict, Any


class SwarmCoordinator:
    def __init__(self, cfg):
        self.cfg = cfg
        self.agents = {}  # Dict of agent instances
        self.agent_health = {}  # Health status
        # Intent store for coordinator-managed trade intents
        self.intents = {}
        self._intent_counter = 0
        self.tasks = []  # Task queue
        self.network = None  # Network agent
        # Rate limiting for tape capture and executions to avoid floods
        self._tape_rate_window = 60  # seconds
        self._tape_rate_limit = 12   # max captures per pair per window
        self._tape_rate = {}         # pair -> (window_start, count)

        self._exec_rate_window = 60  # seconds
        self._exec_rate_limit = 6    # max strategy trades per symbol per window
        self._exec_rate = {}         # symbol -> (window_start, count)
        self._council_cooldowns = {} # (symbol, action) -> cooldown_until_ts
        self._wallet_daily_spend = {}  # yyyy-mm-dd -> notional spent by BUY intents

        self.running = False
        self.threads = []
        self.last_close_time = None
        # CoinGecko caching/backoff to avoid rate limits
        self._cg_cache = {}
        self._cg_last = {}
        self._cg_backoff = {}
        # Track last tape trade id per pair to avoid duplicates
        self._tape_last_id = {}
        # Multi-symbol helpers
        self._exec_by_symbol = {}
        self._cex_exec_by_symbol = {}
        self._regime_oracles = {}
        # Monotonic buzz sequence for ordered event streams
        self._seq = 0
        self._seq_lock = threading.Lock()
        # Heartbeat timing for agent status buzzes
        self._last_agent_hb_ts = 0.0
        self._last_sentiment = None
        self._last_uptrend = None
        self._last_avg_vol = None
        self._last_wallet_balances = None
        self._last_regime = None
        self._last_council = None
        self._last_nurse = None
        self._last_worker_proposals = None
        self._dex_margin_oracle = None
        self._executor_registry = {}
        self._pair_protection_evaluator = PairProtectionEvaluator(self.cfg)
        self._last_market_bee_ts = 0.0
        self._last_paper_eval_ts = 0.0
        self.override_request = {"enabled": False, "reason": ""}
        # Buzz governance staking (queen/council/oracle/kill/security)
        self._buzz_client = None
        self._buzz_actor_last = {}
        self._buzz_actor_amounts = {}
        self._buzz_actor_cooldowns = {}
        self._buzz_actor_active = {}
        self._buzz_settled_intents = set()
        self._buzz_cycles = {}
        self._buzz_cycle_snapshot = {}
        self._buzz_cycle_stakes = {}
        self._buzz_bootstrap_ts = {}
        self._worker_perf_stats = {}
        self._init_buzz_governance()

        # Initialize agents
        self._initialize_agents()

    def _init_buzz_governance(self):
        """Initialize BuzzService client and actor staking settings."""
        try:
            base_url = getattr(self.cfg, "buzz_base_url", "") or ""
            secret = getattr(self.cfg, "buzz_shared_secret", "") or ""
        except Exception:
            base_url = ""
            secret = ""
        if base_url and secret:
            try:
                from buzzservice.client import BuzzServiceClient
                self._buzz_client = BuzzServiceClient(base_url, secret, service_name="coordinator")
            except Exception:
                self._buzz_client = None
        # default stake amounts per actor
        self._buzz_actor_amounts = {
            "COUNCIL": int(getattr(self.cfg, "buzz_stake_council", 10)),
            "QUEEN": int(getattr(self.cfg, "buzz_stake_queen", 20)),
            "ORACLE": int(getattr(self.cfg, "buzz_stake_oracle", 5)),
            "KILL_SWITCH": int(getattr(self.cfg, "buzz_stake_killswitch", 5)),
            "SECURITY": int(getattr(self.cfg, "buzz_stake_security", 5)),
        }
        # default cooldowns per actor (seconds)
        default_cd = int(getattr(self.cfg, "buzz_stake_cooldown_sec", 300))
        self._buzz_actor_cooldowns = {
            "COUNCIL": int(getattr(self.cfg, "buzz_stake_council_cooldown_sec", default_cd)),
            "QUEEN": int(getattr(self.cfg, "buzz_stake_queen_cooldown_sec", default_cd)),
            "ORACLE": int(getattr(self.cfg, "buzz_stake_oracle_cooldown_sec", max(120, default_cd))),
            "KILL_SWITCH": int(getattr(self.cfg, "buzz_stake_killswitch_cooldown_sec", default_cd)),
            "SECURITY": int(getattr(self.cfg, "buzz_stake_security_cooldown_sec", default_cd)),
        }
        self._buzz_actor_rewards = {
            "COUNCIL": float(getattr(self.cfg, "buzz_reward_pct_council", 0.10)),
            "QUEEN": float(getattr(self.cfg, "buzz_reward_pct_queen", 0.15)),
            "ORACLE": float(getattr(self.cfg, "buzz_reward_pct_oracle", 0.05)),
            "KILL_SWITCH": float(getattr(self.cfg, "buzz_reward_pct_killswitch", 0.02)),
            "SECURITY": float(getattr(self.cfg, "buzz_reward_pct_security", 0.02)),
        }
        self._buzz_actor_slash = {
            "COUNCIL": float(getattr(self.cfg, "buzz_slash_pct_council", 0.25)),
            "QUEEN": float(getattr(self.cfg, "buzz_slash_pct_queen", 0.25)),
            "ORACLE": float(getattr(self.cfg, "buzz_slash_pct_oracle", 0.10)),
            "KILL_SWITCH": float(getattr(self.cfg, "buzz_slash_pct_killswitch", 0.05)),
            "SECURITY": float(getattr(self.cfg, "buzz_slash_pct_security", 0.05)),
        }
        # worker cycle staking parameters
        self._buzz_worker_stake_default = int(getattr(self.cfg, "buzz_stake_worker_default", 8) or 8)
        self._buzz_worker_stake_max = int(getattr(self.cfg, "buzz_stake_worker_max", 20) or 20)
        self._buzz_worker_reward_pct = float(getattr(self.cfg, "buzz_stake_worker_reward_pct", 0.08) or 0.08)
        self._buzz_worker_slash_pct = float(getattr(self.cfg, "buzz_stake_worker_slash_pct", 0.20) or 0.20)
        # optional bootstrap funding so stake locks don't 400
        try:
            self._prime_buzz_accounts()
        except Exception:
            pass

    def _prime_buzz_accounts(self) -> None:
        """Seed BUZZ balances for governance + workers (idempotent)."""
        if not self._buzz_client:
            return
        base_amt = int(getattr(self.cfg, "buzz_bootstrap_amount", 200) or 0)
        if base_amt <= 0:
            return
        accounts = []
        for actor in ("COUNCIL", "QUEEN", "ORACLE", "KILL_SWITCH", "SECURITY"):
            accounts.append(f"agent.{actor}")
        # pre-seed worker accounts too
        workers = [
            "WORKER-RSI",
            "WORKER-BREAKOUT",
            "WORKER-MOMENTUM",
            "WORKER-SMA",
            "WORKER-MACD",
            "WORKER-TREND",
            "WORKER-RSI2",
            "WORKER-BOLLINGER",
            "WORKER-SUPERTREND",
        ]
        for w in workers:
            accounts.append(f"agent.{w}")
        for acct in accounts:
            try:
                rid = f"bootstrap-{acct}"
                self._buzz_client.admin_credit(account=acct, amount=base_amt, reason="bootstrap", request_id=rid)
            except Exception:
                continue

    def _ensure_buzz_balance(self, account: str, min_amount: int) -> None:
        """Best-effort top-up to avoid stake lock failures."""
        if not self._buzz_client or not account or min_amount <= 0:
            return
        now = time.time()
        last = float(self._buzz_bootstrap_ts.get(account, 0.0))
        # avoid spamming credit calls
        if now - last < 60:
            return
        self._buzz_bootstrap_ts[account] = now
        try:
            rid = f"topup-{account}"
            self._buzz_client.admin_credit(account=account, amount=min_amount, reason="auto_topup", request_id=rid)
        except Exception:
            pass

    def _initialize_agents(self):
        # Market Data Agent
        self.agents["market_data"] = None  # Will be set in initialize
        self.agents["coingecko"] = CoinGeckoData()
        self.agents["sentiment"] = SentimentData()
        self.agents["trend"] = TrendAnalysis()

        # Strategy Agent
        self.agents["strategy"] = self._create_strategy(self.cfg)
        # Phase 2: Regime + Council + Nurse agents (governance pipeline)
        try:
            self.agents["oracle"] = RegimeOracle(
                symbol=self.cfg.symbol,
                timeframes=getattr(self.cfg, "regime_timeframes", ["1m", "5m", "1h"]),
                min_duration_sec=getattr(self.cfg, "regime_min_duration_sec", 300),
                confirm_bars=getattr(self.cfg, "regime_confirmations", 3),
                confidence_threshold=getattr(self.cfg, "regime_confidence_threshold", 0.15),
            )
        except Exception:
            self.agents["oracle"] = None
        try:
            self.agents["council"] = StrategyCouncil(coordinator=self)
        except Exception:
            self.agents["council"] = None
        try:
            self.agents["nurse"] = NurseAgent(coordinator=self, review_interval_sec=getattr(self.cfg, "nurse_review_interval_sec", 120))
        except Exception:
            self.agents["nurse"] = None
        # Governance queen helper (not exposed as agent; coordinator remains QUEEN)
        try:
            self.governance = GovernanceQueen(min_svs=getattr(self.cfg, "svs_min_threshold", 0.35))
        except Exception:
            self.governance = None
        # Strategy workers
        try:
            self.strategy_workers = [
                SMAWorker(fast=self.cfg.sma_fast, slow=self.cfg.sma_slow),
                RSIWorker(window=self.cfg.rsi_window, oversold=self.cfg.rsi_oversold, overbought=self.cfg.rsi_overbought),
                BreakoutWorker(lookback=max(10, int(self.cfg.lookback / 10)) if self.cfg.lookback else 20),
                MomentumWorker(),
                BollingerWorker(
                    window=int(getattr(self.cfg, "bollinger_window", 20) or 20),
                    num_std=float(getattr(self.cfg, "bollinger_num_std", 2.0) or 2.0),
                ),
                SupertrendWorker(
                    atr_window=int(getattr(self.cfg, "supertrend_atr_window", 10) or 10),
                    multiplier=float(getattr(self.cfg, "supertrend_multiplier", 3.0) or 3.0),
                ),
                RSI2Worker(window=2, oversold=10, overbought=90),
                ProtectionWorker(
                    warn_drawdown_pct=float(getattr(self.cfg, "protection_warn_drawdown_pct", 0.035) or 0.035),
                    block_drawdown_pct=float(getattr(self.cfg, "protection_block_drawdown_pct", 0.05) or 0.05),
                ),
                LatencyTrackerWorker(
                    warn_latency_ms=int(getattr(self.cfg, "latency_warn_ms", 1500) or 1500),
                    block_latency_ms=int(getattr(self.cfg, "latency_block_ms", 5000) or 5000),
                ),
            ]
            if bool(getattr(self.cfg, "volatility_harvest_enabled", False)):
                self.strategy_workers.append(VolatilityExpansionWorker(
                    min_expansion=float(getattr(self.cfg, "volatility_harvest_min_expansion", 1.15) or 1.15),
                    min_volume_surge=float(getattr(self.cfg, "volatility_harvest_min_volume_surge", 0.85) or 0.85),
                    min_return=float(getattr(self.cfg, "volatility_harvest_min_return_pct", 0.002) or 0.002),
                    max_drawdown=float(getattr(self.cfg, "volatility_harvest_max_drawdown_pct", 0.08) or 0.08),
                ))
            if bool(getattr(self.cfg, "exit_manager_enabled", True)):
                self.strategy_workers.append(ExitRiskWorker(
                    hard_stop_pct=float(getattr(self.cfg, "exit_hard_stop_pct", 0.025) or 0.025),
                    take_profit_pct=float(getattr(self.cfg, "exit_take_profit_pct", 0.04) or 0.04),
                    trailing_window=int(getattr(self.cfg, "exit_trailing_window", 12) or 12),
                ))
            self.agents["worker_sma"] = self.strategy_workers[0]
            self.agents["worker_rsi"] = self.strategy_workers[1]
            self.agents["worker_breakout"] = self.strategy_workers[2]
            self.agents["worker_momentum"] = self.strategy_workers[3]
            for w in self.strategy_workers[4:]:
                self.agents[w.name.lower().replace("-", "_")] = w
        except Exception:
            self.strategy_workers = []
            logging.exception("Failed to initialize strategy workers")

        # Execution Agent
        self.agents["execution"] = None  # Will be set in initialize

        # Wallet Monitor Agent
        self.agents["wallet"] = None  # Will be set in initialize

        # Logging & Analytics Agent
        # Pass coordinator reference so logging/analytics can publish snapshots
        self.agents["logging"] = LoggingAnalyticsAgent(coordinator=self)

        # Kill Switch Agent (optional)
        if self.cfg.kill_switch_enabled:
            # map legacy cfg values into the new KillSwitchAgent thresholds
            self.agents["kill_switch"] = KillSwitchAgent(
                coordinator=self,
                daily_loss_throttle_pct=getattr(self.cfg, 'daily_loss_throttle_pct', -0.25),
                daily_loss_halt_pct=getattr(self.cfg, 'daily_loss_halt_pct', -0.50),
                rejects_threshold_5m=getattr(self.cfg, 'rejects_threshold_5m', 20),
                slippage_threshold=getattr(self.cfg, 'slippage_threshold', 0.02),
                market_stale_sec=getattr(self.cfg, 'market_stale_sec', 300.0),
                wallet_stale_sec=getattr(self.cfg, 'wallet_stale_sec', 300.0),
                throttle_clear_sec=getattr(self.cfg, 'throttle_clear_sec', 120),
                grace_sec=getattr(self.cfg, 'kill_switch_grace_sec', 120),
                enforce_stale=getattr(self.cfg, 'kill_switch_enforce_stale', True),
                equity_floor_usd=getattr(self.cfg, 'killswitch_equity_floor_usd', 25.0)
            )
            logging.info("Kill Switch Agent enabled.")
        else:
            self.agents["kill_switch"] = None

        # UI Agent (optional)
        if self.cfg.ui_enabled:
            self.agents["ui"] = UIAgent(self, host=self.cfg.ui_host, port=self.cfg.ui_port)
            logging.info("UI Agent enabled.")
        else:
            self.agents["ui"] = None

        # Network Agent (optional) - deferred until explicitly enabled via UI
        self.network = None
        # store network config for later enabling from UI
        self._network_cfg = {
            "enabled": self.cfg.network_enabled,
            "host": self.cfg.redis_host,
            "port": self.cfg.redis_port,
            "db": self.cfg.redis_db,
            "password": self.cfg.redis_password,
        }

        # Data Store Agent (optional)
        if self.cfg.data_store_enabled:
            self.agents["data_store"] = DataStoreAgent(db_path=self.cfg.db_path, coordinator=self)
            self._load_worker_perf_from_store()
            logging.info("Data Store Agent enabled.")
        else:
            self.agents["data_store"] = None

        # Performance Agent (optional)
        if self.cfg.performance_enabled:
            self.agents["performance"] = PerformanceAgent(coordinator=self)
            logging.info("Performance Agent enabled.")
        else:
            self.agents["performance"] = None

        # SwarmGuard policy gate (optional)
        try:
            self.agents["swarmguard"] = SwarmGuard(self.cfg, coordinator=self)
        except Exception:
            self.agents["swarmguard"] = None
        try:
            self._dex_margin_oracle = DexMarginOracle(self.cfg, coordinator=self)
            self.agents["dex_margin_oracle"] = self._dex_margin_oracle
        except Exception:
            self._dex_margin_oracle = None
        try:
            self._executor_registry = build_executor_registry(self.cfg, coordinator=self)
            self.agents["executor_registry"] = self._executor_registry
        except Exception:
            self._executor_registry = {}
            self.agents["executor_registry"] = {}
        try:
            self.agents["public_bot_bridge"] = PublicBotBridge(self.cfg)
        except Exception:
            self.agents["public_bot_bridge"] = None
        try:
            self.agents["hummingbot_lifecycle"] = HummingbotExecutorLifecycle(self.cfg, coordinator=self)
        except Exception:
            self.agents["hummingbot_lifecycle"] = None
        try:
            self.agents["public_bot_backtests"] = PublicBotBacktestBridge(self.cfg, coordinator=self)
        except Exception:
            self.agents["public_bot_backtests"] = None
        try:
            self.agents["market_making_advisors"] = MarketMakingAdvisorSet(self.cfg)
        except Exception:
            self.agents["market_making_advisors"] = None
        self.agents["phoenix_authority"] = PhoenixAuthorityGuard()
        try:
            self.agents["research_architecture"] = ResearchArchitectureRegistry(self.cfg)
        except Exception:
            self.agents["research_architecture"] = None
        try:
            self.agents["config_agent"] = ConfigAgent(
                config_path=getattr(self.cfg, "settings_path", "config/settings.yaml"),
                snapshot_dir=getattr(self.cfg, "config_snapshot_dir", "data/config_snapshots"),
                audit_log_path=getattr(self.cfg, "config_audit_log_path", "logs/config_audit.jsonl"),
            )
        except Exception:
            self.agents["config_agent"] = None
        try:
            self.agents["event_spine"] = EventSpineAgent()
        except Exception:
            self.agents["event_spine"] = None
        try:
            self.agents["evidence_registry"] = EvidenceRegistryAgent(self.cfg)
        except Exception:
            self.agents["evidence_registry"] = None
        try:
            self.agents["ml_research_lab"] = MLResearchLabAgent(self.cfg)
        except Exception:
            self.agents["ml_research_lab"] = None
        try:
            self.agents["execution_parity"] = ExecutionParityAgent(self.cfg)
        except Exception:
            self.agents["execution_parity"] = None
        try:
            self.agents["signal_marketplace"] = SignalMarketplaceAgent(self.cfg)
        except Exception:
            self.agents["signal_marketplace"] = None

        # Security Agent (optional)
        if self.cfg.security_enabled:
            self.agents["security"] = SecurityAgent(coordinator=self, key_file=self.cfg.encryption_key_file)
            logging.info("Security Agent enabled.")
        else:
            self.agents["security"] = None

        # OpenClaw Agent (custom local agent)
        try:
            agent = OpenClawAgent(
                coordinator=self,
                cfg={
                    "heartbeat_sec": getattr(self.cfg, "openclaw_heartbeat_sec", 5),
                    "openclaw_chat_endpoint": getattr(self.cfg, "openclaw_chat_endpoint", ""),
                    "openclaw_chat_token": getattr(self.cfg, "openclaw_chat_token", ""),
                    "openclaw_chat_format": getattr(self.cfg, "openclaw_chat_format", "hf_space"),
                },
            )
            self.agents["openclaw"] = agent
            try:
                agent.start()
                logging.info("OpenClaw Agent initialized and started.")
            except Exception:
                logging.exception("OpenClaw Agent failed to start")
        except Exception:
            self.agents["openclaw"] = None

        # Set initial health
        for name in self.agents:
            self.agent_health[name] = "initialized"

        # Auto-enable network if configured
        if self.cfg.network_enabled:
            try:
                if self.enable_network(host=self.cfg.redis_host, port=self.cfg.redis_port, db=self.cfg.redis_db, password=self.cfg.redis_password):
                    self.agent_health["network"] = "active"
                else:
                    self.agent_health["network"] = "inactive"
            except Exception as e:
                logging.warning(f"Auto network enable failed: {e}")
                self.agent_health["network"] = "inactive"

        # Seed data_cache with safe defaults so UI and other agents have values to read at startup
        if not hasattr(self, 'data_cache'):
            self.data_cache = {}
        try:
            now_ms = int(time.time() * 1000)
            self.data_cache.setdefault('latest_price', 0.0)
            self.data_cache.setdefault('buzz.analytics.snapshot', {
                'buzz': {'type': 'buzz.analytics.snapshot', 'source': 'ANALYTICS', 'ts': now_ms},
                'payload': {
                    'window_sec': 300,
                    'symbol': getattr(self.cfg, 'symbol', 'N/A'),
                    'trades': 0,
                    'filled': 0,
                    'rejected': 0,
                    'avg_slippage_pct': 0.0,
                    'p95_latency_ms': 0,
                    'market_stale_events': 0,
                    'wallet_stale_events': 0,
                    'equity_usd_est': 0.0,
                    'equity_change_pct': 0.0,
                    'daily_pnl_pct': 0.0,
                    'drawdown_pct': 0.0,
                }
            })
            self.data_cache.setdefault('buzz.performance.snapshot', {'buzz':{'type':'buzz.performance.snapshot','source':'PERFORMANCE','ts':now_ms}, 'payload': {'symbol':getattr(self.cfg,'symbol','N/A'),'window':'0s','equity_usd_est':0.0,'realized_pnl_usd':0.0,'unrealized_pnl_usd':0.0,'pnl_pct':0.0,'max_drawdown_pct':0.0,'win_rate':0.0,'trades':0,'avg_fee_usd':0.0}})
        except Exception:
            pass

    def _create_strategy(self, cfg):
        # Return a StrategyAgent wrapper that emits structured signals while remaining
        # backward-compatible with older code that expects a simple 'BUY'/'SELL'/'HOLD' string.
        try:
            from agents.strategy import StrategyAgent
        except Exception:
            # Fallback to simple SMACrossoverStrategy
            if cfg.strategy_type == "rsi":
                return RSIStrategy(window=cfg.rsi_window, oversold=cfg.rsi_oversold, overbought=cfg.rsi_overbought)
            if cfg.strategy_type == "macd":
                return MACDStrategy(fast=cfg.macd_fast, slow=cfg.macd_slow, signal=cfg.macd_signal)
            return SMACrossoverStrategy(fast=cfg.sma_fast, slow=cfg.sma_slow)

        if cfg.strategy_type == "sma_crossover":
            return StrategyAgent(fast=cfg.sma_fast, slow=cfg.sma_slow, tf=cfg.interval, coordinator=self, cooldown_sec=getattr(cfg,'strategy_cooldown',120))
        elif cfg.strategy_type == "rsi":
            return StrategyAgent(fast=10, slow=30, tf=cfg.interval, coordinator=self)
        elif cfg.strategy_type == "macd":
            return StrategyAgent(fast=cfg.macd_fast, slow=cfg.macd_slow, tf=cfg.interval, coordinator=self)
        else:
            return StrategyAgent(fast=cfg.sma_fast, slow=cfg.sma_slow, tf=cfg.interval, coordinator=self)

    def initialize(self, client):
        # store client for coin selection and symbol switching
        self._client = client
        self._last_coin_select_ts = 0
        try:
            self._coin_selector = CoinSelector(self.cfg, coordinator=self)
        except Exception:
            self._coin_selector = None
        # Initialize market data agent
        if client:
            try:
                if self.cfg.exchange.lower() == "kraken":
                    self.agents["market_data"] = KrakenMarketData(client, self.cfg.symbol, self.cfg.interval)
                    logging.info("Kraken Market Data Agent initialized.")
                else:
                    self.agents["market_data"] = MarketData(client, self.cfg.symbol, self.cfg.interval)
                    logging.info("Market Data Agent initialized.")
            except Exception as e:
                logging.warning(f"Market Data Agent failed to initialize: {e}")
                self.agents["market_data"] = None
        else:
            logging.warning("Market Data Agent skipped (no client).")
            self.agents["market_data"] = None

        # Phase 1 public-market observation swarm. It is deliberately separate
        # from the execution agent and can run with a public, unauthenticated client.
        try:
            self.agents["observation_swarm"] = ObservationSwarmAgent(self.cfg, client, coordinator=self)
            logging.info("Phase-1 Observation Swarm initialized (execution_wired=false).")
        except Exception as exc:
            logging.warning(f"Observation Swarm failed to initialize: {exc}")
            self.agents["observation_swarm"] = None

        # Phase 2 hypothesis competition. It drives the observer on a single
        # schedule and remains disconnected from the execution agent.
        try:
            self.agents["hypothesis_swarm"] = HypothesisSwarmAgent(
                self.cfg, self.agents.get("observation_swarm"), coordinator=self
            )
            logging.info("Phase-2 Hypothesis Swarm initialized (research_only, execution_wired=false).")
        except Exception as exc:
            logging.warning(f"Hypothesis Swarm failed to initialize: {exc}")
            self.agents["hypothesis_swarm"] = None

        # Phase 3 execution-aware simulation lab. It consumes only persisted
        # forecasts and public observations; no private exchange interface is passed.
        try:
            self.agents["execution_lab"] = ExecutionLabAgent(
                self.cfg,
                self.agents.get("hypothesis_swarm"),
                self.agents.get("data_store"),
                coordinator=self,
            )
            logging.info("Phase-3 Execution Lab initialized (simulation_only, execution_wired=false).")
        except Exception as exc:
            logging.warning(f"Execution Lab failed to initialize: {exc}")
            self.agents["execution_lab"] = None

        # Phase 4 adversarial validation. It consumes only Phase-3 evidence and
        # may produce a review recommendation, never execution authority.
        try:
            self.agents["validation_lab"] = ValidationLabAgent(
                self.cfg,
                self.agents.get("execution_lab"),
                self.agents.get("data_store"),
                coordinator=self,
            )
            logging.info("Phase-4 Validation Lab initialized (review_only, execution_wired=false).")
        except Exception as exc:
            logging.warning(f"Validation Lab failed to initialize: {exc}")
            self.agents["validation_lab"] = None

        # Phase 5 public shadow flight. It consumes a human-approved frozen
        # Phase-4 champion and generates venue-ready but never-transmitted intents.
        try:
            self.agents["shadow_flight"] = ShadowFlightAgent(
                self.cfg,
                self.agents.get("validation_lab"),
                self.agents.get("data_store"),
                coordinator=self,
            )
            logging.info("Phase-5 Shadow Flight initialized (public_shadow_only, transmission absent).")
        except Exception as exc:
            logging.warning(f"Shadow Flight failed to initialize: {exc}")
            self.agents["shadow_flight"] = None

        # Initialize execution agent (CEX or on-chain DEX)
        if getattr(self.cfg, "onchain_enabled", False):
            try:
                from agents.execution import DexExecutionAgent
                self.agents["execution"] = DexExecutionAgent(self.cfg, coordinator=self)
                logging.info("DEX Execution Agent initialized (on-chain).")
            except Exception as e:
                logging.warning(f"DEX Execution Agent failed to initialize: {e}")
                self.agents["execution"] = None
        else:
            # CEX execution path
            if client:
                try:
                    if self.cfg.exchange.lower() == "kraken":
                        trader = KrakenTrader(client, self.cfg.symbol, self.cfg.dry_run, self.cfg.max_position_base)
                        logging.info("Kraken low-level trader created.")
                    else:
                        trader = BinanceTrader(client, self.cfg.symbol, self.cfg.dry_run, self.cfg.max_position_base)
                        logging.info("Binance low-level trader created.")
                    try:
                        from agents.execution import ExecutionAgent
                        self.agents["execution"] = ExecutionAgent(
                            trader,
                            coordinator=self,
                            dry_run=self.cfg.dry_run,
                            min_notional=getattr(self.cfg, "min_trade_usd", 1.0),
                            spread_threshold_pct=getattr(self.cfg, "spread_guard_pct", 0.0015),
                        )
                        logging.info("Execution Agent wrapper initialized.")
                    except Exception:
                        # fallback to raw trader
                        self.agents["execution"] = trader
                        logging.info("Execution Agent wrapper unavailable; using raw trader.")
                except Exception as e:
                    logging.warning(f"Execution Agent failed to initialize: {e}")
                    self.agents["execution"] = None
            else:
                logging.warning("Execution Agent skipped (no client).")
                self.agents["execution"] = None

        # Initialize wallet monitor (optional)
        if self.cfg.web3_rpc_url and self.cfg.watch_address:
            try:
                self.agents["wallet"] = WalletMonitor(
                    self.cfg.web3_rpc_url,
                    self.cfg.watch_address,
                    self.cfg.erc20_token_address,
                    self.cfg.etherscan_api_key,
                    exchange_client=client,
                    execution_agent=self.agents.get("execution"),
                    coordinator=self,
                    poll_seconds=getattr(self.cfg, 'wallet_poll_seconds', 5),
                    extra_token_addresses=getattr(self.cfg, 'onchain_token_addresses', None),
                    multichain_watch=getattr(self.cfg, 'multichain_watch_chains', None) if getattr(self.cfg, 'multichain_watch_enabled', False) else None,
                )
                logging.info("Wallet monitor enabled.")
            except Exception as e:
                logging.warning(f"Wallet monitor disabled (error): {e}")
                self.agents["wallet"] = None

        # Mark healthy agents
        for name in ["market_data", "execution", "wallet", "observation_swarm", "hypothesis_swarm", "execution_lab", "validation_lab", "shadow_flight"]:
            if self.agents.get(name):
                self.agent_health[name] = "active"

    def distribute_task(self, task: Dict[str, Any]):
        """Distribute task to appropriate agent."""
        agent_name = task.get("agent")
        if agent_name in self.agents and self.agents[agent_name]:
            # Simulate task execution
            logging.info(f"Task distributed to {agent_name}: {task}")
            # In real: self.agents[agent_name].execute_task(task)
        else:
            logging.warning(f"Agent {agent_name} not available for task: {task}")

    def share_data(self, key: str, data: Any):
        """Share data across agents."""
        out = data
        event_spine_alerts = []
        if key.startswith('buzz.') and isinstance(data, dict):
            if 'buzz' not in data or 'payload' not in data:
                try:
                    src = data.get('source') if isinstance(data, dict) else None
                except Exception:
                    src = None
                if not src:
                    parts = key.split('.')
                    src = parts[1].upper() if len(parts) > 1 else 'SYSTEM'
                out = {
                    'buzz': {
                        'type': key,
                        'source': src,
                        'ts': int(time.time() * 1000),
                    },
                    'payload': data,
                }
            # Ensure an ordered sequence id exists
            try:
                if 'seq' not in out.get('buzz', {}):
                    with self._seq_lock:
                        self._seq += 1
                        out['buzz']['seq'] = self._seq
            except Exception:
                pass
        elif key.startswith('buzz.') and isinstance(out, dict) and 'buzz' in out:
            # Attach seq if missing
            try:
                if 'seq' not in out.get('buzz', {}):
                    with self._seq_lock:
                        self._seq += 1
                        out['buzz']['seq'] = self._seq
            except Exception:
                pass
        try:
            event_spine = self.agents.get("event_spine") if hasattr(self, "agents") else None
            if key.startswith("buzz.") and isinstance(out, dict) and event_spine and hasattr(event_spine, "normalize"):
                out, event_spine_alerts = event_spine.normalize(key, out)
        except Exception:
            logging.exception("event_spine.normalize failed")
        # Optional BUZZ staking for governance actors on select events
        try:
            if key.startswith('buzz.') and isinstance(out, dict):
                self._maybe_buzz_stake(out)
        except Exception:
            pass
        # Always keep a local cache copy so UI and local consumers can read
        # the latest shared buzz messages even when a Network agent is
        # configured and data is forwarded externally.
        if not hasattr(self, 'data_cache'):
            self.data_cache = {}
        try:
            self.data_cache[key] = out
        except Exception:
            # best-effort cache write
            pass
        # Debug: persist a small snapshot of the shared cache so we can
        # inspect buzz traffic from outside the process.
        try:
            import json
            os.makedirs('logs', exist_ok=True)
            # write only last 200 keys to keep file small
            snapshot = {k: self.data_cache[k] for k in list(self.data_cache.keys())[-200:]}
            with open('logs/shared_cache.json', 'w', encoding='utf-8') as f:
                json.dump(snapshot, f, default=str)
        except Exception:
            pass
        # Forward to network if present
        if self.network:
            try:
                self.network.share_data(key, out)
            except Exception:
                logging.exception('share_data publish failed')
        logging.debug(f"Data shared: {key} = {out}")
        # If this is a buzz event, forward to logging analytics and kill switch agents for ingestion
        try:
            if key.startswith('buzz.') and isinstance(out, dict):
                # deliver to logging agent
                logging_agent = self.agents.get('logging')
                if logging_agent and hasattr(logging_agent, 'log_event'):
                    try:
                        logging_agent.log_event(out)
                    except Exception:
                        logging.exception('logging_agent.log_event failed')
                # deliver to kill switch agent
                ks = self.agents.get('kill_switch')
                if ks and hasattr(ks, 'handle_event'):
                    try:
                        ks.handle_event(out)
                    except Exception:
                        logging.exception('kill_switch.handle_event failed')
                # deliver to security agent
                sec = self.agents.get('security')
                if sec and hasattr(sec, 'handle_event'):
                    try:
                        sec.handle_event(out)
                    except Exception:
                        logging.exception('security.handle_event failed')
                # deliver to data store agent for durable persistence
                ds = self.agents.get('data_store')
                if ds and hasattr(ds, 'handle_event'):
                    try:
                        ds.handle_event(out)
                    except Exception:
                        logging.exception('data_store.handle_event failed')
                for alert in event_spine_alerts or []:
                    self._record_event_spine_alert(alert)
        except Exception:
            logging.exception('share_data forward failed')

    def _record_event_spine_alert(self, alert: Dict[str, Any]) -> None:
        """Record an event-spine alert without re-entering share_data."""
        if not isinstance(alert, dict):
            return
        buzz = alert.get("buzz") or {}
        key = buzz.get("type") or "buzz.system.alert"
        if not hasattr(self, "data_cache"):
            self.data_cache = {}
        try:
            self.data_cache[key] = alert
        except Exception:
            pass
        try:
            logging_agent = self.agents.get("logging")
            if logging_agent and hasattr(logging_agent, "log_event"):
                logging_agent.log_event(alert)
        except Exception:
            logging.exception("logging_agent.log_event alert failed")
        try:
            ds = self.agents.get("data_store")
            if ds and hasattr(ds, "handle_event"):
                ds.handle_event(alert)
            if ds and hasattr(ds, "store_security_audit"):
                ds.store_security_audit(alert.get("payload") or {})
        except Exception:
            logging.exception("data_store event spine alert failed")

    def get_shared_data(self, key: str) -> Any:
        if self.network:
            return self.network.get_shared_data(key)
        else:
            return getattr(self, 'data_cache', {}).get(key)

    def _maybe_buzz_stake(self, evt: Dict[str, Any]) -> None:
        """Attach BUZZ stake receipts for governance actors if configured."""
        if not self._buzz_client or not evt:
            return
        buzz = evt.get("buzz") or {}
        typ = str(buzz.get("type") or "")
        source = str(buzz.get("source") or "").upper()
        payload = evt.get("payload") or {}

        actor = None
        if typ == "buzz.council.decision":
            actor = "COUNCIL"
        elif typ == "buzz.governance.decision":
            actor = "QUEEN"
        elif typ == "buzz.regime.snapshot":
            actor = "ORACLE"
        elif typ == "buzz.kill.trigger":
            actor = "KILL_SWITCH"
        elif typ == "buzz.security.policy":
            actor = "SECURITY"
        elif typ == "buzz.council.pack":
            actor = "COUNCIL"
        elif source in ("COUNCIL", "QUEEN", "ORACLE", "KILL_SWITCH", "SECURITY"):
            actor = source

        if not actor:
            return
        amt = int(self._buzz_actor_amounts.get(actor, 0) or 0)
        if amt <= 0:
            return
        now = time.time()
        cooldown = int(self._buzz_actor_cooldowns.get(actor, 300))
        last = float(self._buzz_actor_last.get(actor, 0))
        if now - last < cooldown:
            return
        self._buzz_actor_last[actor] = now

        account = f"agent.{actor}"
        reason = typ or f"buzz.{actor.lower()}"
        # ensure account has at least stake amount
        try:
            self._ensure_buzz_balance(account, amt)
        except Exception:
            pass
        # Optional cycle staking context
        stake_context = {}
        if typ == "buzz.council.pack" and isinstance(payload, dict):
            try:
                proposals = payload.get("proposals") or []
                # pick highest signal_strength as "favorite"
                fav = None
                for p in proposals:
                    if not fav or float(p.get("signal_strength") or 0) > float(fav.get("signal_strength") or 0):
                        fav = p
                if fav:
                    stake_context = {
                        "kind": "council_cycle",
                        "strategy": fav.get("strategy"),
                        "action": fav.get("action"),
                        "symbol": payload.get("symbol"),
                        "signal_strength": fav.get("signal_strength"),
                    }
                    reason = f"cycle:council_favorite:{fav.get('strategy')}"
            except Exception:
                pass
        elif typ == "buzz.governance.decision" and isinstance(payload, dict):
            stake_context = {
                "kind": "queen_cycle",
                "action": payload.get("action"),
                "strategy": payload.get("strategy"),
                "symbol": payload.get("symbol") or payload.get("pair"),
                "svs": payload.get("svs"),
            }
            reason = f"cycle:queen:{payload.get('action')}"
        elif typ == "buzz.regime.snapshot" and isinstance(payload, dict):
            stake_context = {
                "kind": "oracle_cycle",
                "regime": payload.get("regime"),
                "confidence": payload.get("confidence"),
                "symbol": payload.get("symbol"),
            }
            reason = f"cycle:oracle:{payload.get('regime')}"
        elif typ == "buzz.kill.check" and isinstance(payload, dict):
            stake_context = {
                "kind": "killswitch_cycle",
                "risk_state": payload.get("risk_state"),
                "reason": payload.get("reason"),
            }
            reason = f"cycle:killswitch:{payload.get('risk_state')}"
        elif typ == "buzz.security.policy" and isinstance(payload, dict):
            stake_context = {
                "kind": "security_cycle",
                "armed": payload.get("armed"),
                "paused": payload.get("paused"),
                "dry_run": payload.get("dry_run"),
            }
            reason = f"cycle:security:{'armed' if payload.get('armed') else 'unarmed'}"
        request_id = f"{actor.lower()}-{int(now*1000)}"
        try:
            # Release any prior active stake for this actor (cycle rollover)
            try:
                prev = self._buzz_actor_active.get(actor)
                if prev and prev.get("amount"):
                    self._buzz_client.release(
                        account=prev.get("account"),
                        amount=int(prev.get("amount")),
                        reason="cycle_rollover",
                        request_id=f"roll-{actor.lower()}-{int(now*1000)}",
                    )
            except Exception:
                pass
            receipt = self._buzz_client.lock(account=account, amount=amt, reason=reason, request_id=request_id)
        except Exception:
            return
        try:
            self._buzz_actor_active[actor] = {
                "account": account,
                "amount": amt,
                "ts": now,
                "receipt": receipt,
                "reason": reason,
            }
            if isinstance(payload, dict):
                payload.setdefault("buzz_stake", {})
                payload["buzz_stake"] = {
                    "account": account,
                    "amount": amt,
                    "reason": reason,
                    "receipt": receipt,
                    "context": stake_context,
                }
                evt["payload"] = payload
            # track for cycle stake strip
            try:
                self._buzz_cycle_stakes[actor] = {
                    "actor": actor,
                    "account": account,
                    "amount": amt,
                    "reason": reason,
                    "ts": int(now * 1000),
                    "context": stake_context,
                }
                # attach to active cycle (if any)
                try:
                    sym = stake_context.get("symbol")
                    if sym and sym in self._buzz_cycles:
                        cyc = self._buzz_cycles.get(sym) or {}
                        if isinstance(cyc.get("stakes"), dict):
                            cyc["stakes"][actor] = self._buzz_cycle_stakes[actor]
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            pass

    def _settle_governance_buzz(self, intent_id: str) -> None:
        """Release/reward or slash governance stakes after a trade outcome."""
        if not self._buzz_client:
            return
        if not intent_id:
            return
        if intent_id in self._buzz_settled_intents:
            return
        self._buzz_settled_intents.add(intent_id)

        # Determine outcome from logging metrics
        last_result = None
        try:
            log_agent = self.agents.get("logging")
            if log_agent and hasattr(log_agent, "metrics"):
                last_result = (log_agent.metrics or {}).get("last_trade_result")
        except Exception:
            last_result = None
        is_win = True if last_result == "win" else False

        # Nurse signals (optional): if loss streak high, add extra slash bonus
        extra_slash = 0.0
        try:
            nurse = self.agents.get("nurse")
            if nurse and hasattr(nurse, "_last_summary"):
                streak = int((nurse._last_summary or {}).get("worker_loss_streak", 0))
                threshold = int(getattr(self.cfg, "buzz_loss_streak_threshold", 3))
                if streak >= threshold:
                    extra_slash = float(getattr(self.cfg, "buzz_loss_streak_slash_bonus_pct", 0.05))
        except Exception:
            extra_slash = 0.0

        # Settle active stakes
        for actor, stake in list(self._buzz_actor_active.items()):
            try:
                account = stake.get("account")
                amt = int(stake.get("amount") or 0)
                if not account or amt <= 0:
                    continue
                if is_win:
                    # release full stake
                    try:
                        self._buzz_client.release(account=account, amount=amt, reason="trade_win", request_id=f"rel-{actor.lower()}-{int(time.time()*1000)}")
                    except Exception:
                        pass
                    # reward bonus
                    reward_pct = float(self._buzz_actor_rewards.get(actor, 0.0))
                    reward_amt = int(max(0, round(amt * reward_pct)))
                    if reward_amt > 0:
                        try:
                            self._buzz_client.admin_credit(account=account, amount=reward_amt, reason="trade_win_reward", request_id=f"rew-{actor.lower()}-{int(time.time()*1000)}")
                        except Exception:
                            pass
                else:
                    # slash portion of stake
                    slash_pct = float(self._buzz_actor_slash.get(actor, 0.0)) + float(extra_slash)
                    slash_amt = int(max(0, round(amt * slash_pct)))
                    if slash_amt > 0:
                        try:
                            self._buzz_client.slash(account=account, amount=slash_amt, reason="trade_loss_slash", request_id=f"sl-{actor.lower()}-{int(time.time()*1000)}")
                        except Exception:
                            pass
                    # release remaining stake
                    remain = max(0, amt - slash_amt)
                    if remain > 0:
                        try:
                            self._buzz_client.release(account=account, amount=remain, reason="trade_loss_release", request_id=f"rl-{actor.lower()}-{int(time.time()*1000)}")
                        except Exception:
                            pass
                # emit settlement buzz (best-effort)
                try:
                    self.share_data("buzz.governance.settlement", {
                        "buzz": {"type": "buzz.governance.settlement", "source": actor, "ts": int(time.time() * 1000)},
                        "payload": {
                            "actor": actor,
                            "account": account,
                            "amount": amt,
                            "outcome": "win" if is_win else "loss",
                            "extra_slash_pct": extra_slash,
                        }
                    })
                except Exception:
                    pass
            except Exception:
                continue

    def _update_cycle(self, symbol: str, latest_price: float, proposals: list, queen_decision: dict | None = None) -> None:
        """Track a per-symbol BUZZ cycle and emit cycle snapshots/results."""
        try:
            if not symbol or latest_price is None:
                return
            now = time.time()
            cycle_len = int(getattr(self.cfg, "buzz_cycle_length_sec", 120))
            move_thresh = float(getattr(self.cfg, "buzz_cycle_move_threshold_pct", 0.001))
            cycle = self._buzz_cycles.get(symbol)

            def _finalize(cyc, end_price):
                try:
                    start = float(cyc.get("start_price") or 0)
                except Exception:
                    start = 0.0
                pct = 0.0
                if start > 0:
                    pct = (end_price - start) / start
                if abs(pct) < move_thresh:
                    outcome = "HOLD"
                else:
                    outcome = "BUY" if pct > 0 else "SELL"

                scores = []
                for name, p in (cyc.get("proposals") or {}).items():
                    action = str((p or {}).get("action") or "HOLD").upper()
                    score = 1 if action == outcome else 0
                    strength = float((p or {}).get("signal_strength") or 0)
                    scores.append({"strategy": name, "action": action, "score": score, "strength": strength})
                # include queen as a competitor
                q = cyc.get("queen") or {}
                if q:
                    qa = str(q.get("action") or "HOLD").upper()
                    qs = 1 if qa == outcome else 0
                    scores.append({"strategy": "QUEEN", "action": qa, "score": qs, "strength": float(q.get("svs") or 0)})

                scores_sorted = sorted(scores, key=lambda x: (x.get("score", 0), x.get("strength", 0)), reverse=True)
                winner = scores_sorted[0]["strategy"] if scores_sorted else None
                result = {
                    "symbol": symbol,
                    "start_ts": cyc.get("start_ts"),
                    "end_ts": int(now * 1000),
                    "start_price": cyc.get("start_price"),
                    "end_price": end_price,
                    "pct_change": pct,
                    "outcome": outcome,
                    "scores": scores_sorted,
                    "winner": winner,
                }
                # settle cycle stakes (workers + governance) into BUZZ ledger
                payouts = []
                if self._buzz_client:
                    rank_map = {s.get("strategy"): i for i, s in enumerate(scores_sorted)}
                    for key, stake in (cyc.get("stakes") or {}).items():
                        try:
                            ctx = stake.get("context") or {}
                            if "cycle" not in str(ctx.get("kind", "")):
                                continue
                            acct = stake.get("account")
                            actor = stake.get("actor") or ""
                            amt = int(stake.get("amount") or 0)
                            if not acct or amt <= 0:
                                continue
                            # determine prediction
                            pred = None
                            if ctx.get("action"):
                                pred = str(ctx.get("action") or "").upper()
                            elif ctx.get("strategy"):
                                strat = ctx.get("strategy")
                                if strat in (cyc.get("proposals") or {}):
                                    pred = str((cyc["proposals"][strat] or {}).get("action") or "HOLD").upper()
                            elif ctx.get("regime"):
                                reg = str(ctx.get("regime") or "").upper()
                                if reg in ("RANGING", "RANGE", "CHOP_RANGE", "CHAOTIC"):
                                    pred = "HOLD"
                            is_win = bool(pred and pred == outcome)
                            kind = str(ctx.get("kind") or "")
                            # pick reward/slash
                            if kind.startswith("worker"):
                                reward_pct = float(self._buzz_worker_reward_pct)
                                slash_pct = float(self._buzz_worker_slash_pct)
                                rank = rank_map.get(ctx.get("strategy"))
                                if rank == 1:
                                    slash_pct *= 0.5
                                elif rank == 2:
                                    slash_pct *= 0.75
                            else:
                                reward_pct = float(self._buzz_actor_rewards.get(actor, 0.05))
                                slash_pct = float(self._buzz_actor_slash.get(actor, 0.10))
                            if is_win:
                                try:
                                    self._buzz_client.release(account=acct, amount=amt, reason="cycle_win_release", request_id=f"cyc-rel-{key}-{int(time.time()*1000)}")
                                except Exception:
                                    pass
                                reward_amt = int(max(0, round(amt * reward_pct)))
                                if reward_amt > 0:
                                    try:
                                        self._buzz_client.admin_credit(account=acct, amount=reward_amt, reason="cycle_win_reward", request_id=f"cyc-rew-{key}-{int(time.time()*1000)}")
                                    except Exception:
                                        pass
                                payouts.append({"actor": actor or key, "account": acct, "amount": amt, "reward": reward_amt, "slash": 0, "outcome": "win"})
                            else:
                                slash_amt = int(max(0, round(amt * slash_pct)))
                                if slash_amt > 0:
                                    try:
                                        self._buzz_client.slash(account=acct, amount=slash_amt, reason="cycle_loss_slash", request_id=f"cyc-sla-{key}-{int(time.time()*1000)}")
                                    except Exception:
                                        pass
                                remain = max(0, amt - slash_amt)
                                if remain > 0:
                                    try:
                                        self._buzz_client.release(account=acct, amount=remain, reason="cycle_loss_release", request_id=f"cyc-rls-{key}-{int(time.time()*1000)}")
                                    except Exception:
                                        pass
                                payouts.append({"actor": actor or key, "account": acct, "amount": amt, "reward": 0, "slash": slash_amt, "outcome": "loss"})
                        except Exception:
                            continue
                if payouts:
                    result["payouts"] = payouts
                    result["payout_summary"] = {
                        "total_staked": sum([p.get("amount", 0) for p in payouts]),
                        "total_reward": sum([p.get("reward", 0) for p in payouts]),
                        "total_slash": sum([p.get("slash", 0) for p in payouts]),
                    }
                return result

            # finalize if needed
            if cycle and now >= cycle.get("end_ts", 0):
                result = _finalize(cycle, float(latest_price))
                self._update_worker_perf_from_cycle(result)
                self._buzz_cycle_snapshot = {"type": "cycle_result", **result}
                try:
                    self.share_data("buzz.cycle.result", {
                        "buzz": {"type": "buzz.cycle.result", "source": "CYCLE", "ts": int(now * 1000)},
                        "payload": self._buzz_cycle_snapshot,
                    })
                except Exception:
                    pass
                cycle = None

            if not cycle:
                cycle = {
                    "symbol": symbol,
                    "start_ts": int(now * 1000),
                    "end_ts": now + cycle_len,
                    "start_price": float(latest_price),
                    "proposals": {},
                    "queen": {},
                    "stakes": {},
                    "worker_stakes": {},
                }
                self._buzz_cycle_stakes = cycle["stakes"]
                self._buzz_cycles[symbol] = cycle
            else:
                # keep global stake view pointing at current cycle
                try:
                    if isinstance(cycle.get("stakes"), dict):
                        self._buzz_cycle_stakes = cycle["stakes"]
                except Exception:
                    pass

            # update proposals
            try:
                for p in proposals or []:
                    name = p.get("strategy") or p.get("worker") or "WORKER"
                    cycle["proposals"][name] = {
                        "action": p.get("action") or p.get("side") or "HOLD",
                        "signal_strength": p.get("signal_strength") or p.get("edge") or 0,
                    }
            except Exception:
                pass
            # stake workers once per cycle
            try:
                if self._buzz_client:
                    for p in proposals or []:
                        name = p.get("strategy") or p.get("worker") or "WORKER"
                        if name in cycle.get("worker_stakes", {}):
                            continue
                        strength = 0.0
                        try:
                            strength = float(p.get("signal_strength") or p.get("edge") or 0.0)
                        except Exception:
                            strength = 0.0
                        base = int(self._buzz_worker_stake_default or 1)
                        max_amt = int(self._buzz_worker_stake_max or base)
                        # scale stake by strength (0..1) with a floor
                        mult = max(0.0, min(1.0, abs(strength)))
                        amt = int(max(1, min(max_amt, round(base * (0.6 + (0.8 * mult))))))
                        account = f"agent.{name}"
                        reason = f"cycle:worker:{name}"
                        req_id = f"cycle-worker-{symbol}-{cycle.get('start_ts')}-{name}"
                        try:
                            self._ensure_buzz_balance(account, amt)
                        except Exception:
                            pass
                        try:
                            receipt = self._buzz_client.lock(account=account, amount=amt, reason=reason, request_id=req_id)
                        except Exception:
                            receipt = {}
                        ctx = {"kind": "worker_cycle", "strategy": name, "action": p.get("action") or p.get("side") or "HOLD"}
                        stake_rec = {
                            "actor": name,
                            "account": account,
                            "amount": amt,
                            "reason": reason,
                            "context": ctx,
                            "receipt": receipt,
                        }
                        cycle.setdefault("worker_stakes", {})[name] = stake_rec
                        cycle.setdefault("stakes", {})[f"worker:{name}"] = stake_rec
                        self._buzz_cycle_stakes[f"worker:{name}"] = stake_rec
            except Exception:
                pass
            # update queen decision
            if queen_decision:
                try:
                    cycle["queen"] = {
                        "action": queen_decision.get("action"),
                        "strategy": queen_decision.get("strategy"),
                        "svs": queen_decision.get("svs"),
                    }
                except Exception:
                    pass

            # publish cycle snapshot
            remaining = max(0, int(cycle.get("end_ts", now) - now))
            stakes = list(self._buzz_cycle_stakes.values())
            snap = {
                "symbol": symbol,
                "start_ts": cycle.get("start_ts"),
                "end_ts": int(cycle.get("end_ts", now) * 1000),
                "time_left_sec": remaining,
                "start_price": cycle.get("start_price"),
                "latest_price": float(latest_price),
                "proposals": cycle.get("proposals", {}),
                "queen": cycle.get("queen", {}),
                "stakes": stakes,
            }
            self._buzz_cycle_snapshot = {"type": "cycle_snapshot", **snap}
            try:
                self.share_data("buzz.cycle.snapshot", {
                    "buzz": {"type": "buzz.cycle.snapshot", "source": "CYCLE", "ts": int(now * 1000)},
                    "payload": self._buzz_cycle_snapshot,
                })
            except Exception:
                pass
        except Exception:
            pass

    def _update_worker_perf_from_cycle(self, result: Dict[str, Any]) -> None:
        """Update lightweight worker stats from BUZZ cycle outcomes."""
        try:
            for row in result.get("scores") or []:
                name = row.get("strategy")
                if not name or not str(name).startswith("WORKER-"):
                    continue
                stat = self._worker_perf_stats.setdefault(name, {
                    "total": 0,
                    "wins": 0,
                    "losses": 0,
                    "recent": [],
                })
                score = 1 if int(row.get("score") or 0) > 0 else 0
                stat["total"] = int(stat.get("total") or 0) + 1
                if score:
                    stat["wins"] = int(stat.get("wins") or 0) + 1
                else:
                    stat["losses"] = int(stat.get("losses") or 0) + 1
                recent = list(stat.get("recent") or [])
                recent.append(score)
                stat["recent"] = recent[-50:]
                stat["updated_ts"] = time.time()
                self._persist_worker_perf(name, stat)
        except Exception:
            pass

    def _load_worker_perf_from_store(self) -> None:
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        if not ds or not hasattr(ds, "get_worker_performance"):
            return
        try:
            rows = ds.get_worker_performance() or {}
            for name, stat in rows.items():
                if not name:
                    continue
                recent = stat.get("recent") or []
                if isinstance(recent, str):
                    try:
                        import json
                        recent = json.loads(recent or "[]")
                    except Exception:
                        recent = []
                self._worker_perf_stats[name] = {
                    "total": int(stat.get("total") or 0),
                    "wins": int(stat.get("wins") or 0),
                    "losses": int(stat.get("losses") or 0),
                    "recent": list(recent)[-50:],
                    "updated_ts": float(stat.get("updated_ts") or time.time()),
                }
        except Exception:
            logging.exception("Failed to load worker performance stats")

    def _persist_worker_perf(self, name: str, stat: Dict[str, Any]) -> None:
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        if ds and hasattr(ds, "upsert_worker_performance"):
            try:
                ds.upsert_worker_performance(name, stat)
            except Exception:
                pass

    def apply_public_bot_backtest_metrics(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Import external metrics without mutating worker weights or live readiness."""
        evidence = self._record_public_bot_evidence(payload or {})
        return {
            "ok": bool(evidence),
            "updates": {},
            "evidence": evidence,
            "authority": "research_import_only",
            "worker_weights_mutated": False,
            "promotion_mutated": False,
            "next_required_phase": 2,
        }

    def _record_public_bot_evidence(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        registry = self.agents.get("evidence_registry") if hasattr(self, "agents") else None
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        if not registry or not hasattr(registry, "from_public_bot"):
            return {}
        try:
            record = registry.from_public_bot(payload or {})
            if ds and hasattr(ds, "upsert_evidence_record"):
                ds.upsert_evidence_record(record)
            self.share_data("buzz.evidence.recorded", {
                "buzz": {"type": "buzz.evidence.recorded", "source": "EVIDENCE_REGISTRY", "ts": int(time.time() * 1000)},
                "payload": {
                    "evidence_id": record.get("evidence_id"),
                    "source": record.get("source"),
                    "engine": record.get("engine"),
                    "run_id": record.get("run_id"),
                    "symbol": record.get("symbol"),
                    "verdict": record.get("verdict"),
                    "promotion_stage": record.get("promotion_stage"),
                    "gates": record.get("gates"),
                    "metrics": record.get("metrics"),
                },
            })
            return record
        except Exception:
            logging.exception("Failed to record public bot evidence")
            return {}

    def _extract_public_bot_worker_metrics(self, payload: Dict[str, Any], metrics: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        workers = metrics.get("worker_performance") or metrics.get("workers") or metrics.get("strategies")
        if isinstance(workers, dict):
            return {str(k): dict(v or {}) for k, v in workers.items()}
        if isinstance(workers, list):
            out = {}
            for row in workers:
                if isinstance(row, dict):
                    name = row.get("worker") or row.get("strategy") or row.get("name")
                    if name:
                        out[str(name)] = row
            if out:
                return out
        proposal_workers = self._public_bot_proposal_workers(payload)
        if not proposal_workers:
            return {}
        shared = {
            "trades": metrics.get("trades") or metrics.get("total_trades") or 1,
            "wins": metrics.get("wins"),
            "win_rate": metrics.get("win_rate"),
            "net_profit_pct": metrics.get("net_profit_pct") or metrics.get("profit_total_pct"),
            "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        }
        return {name: dict(shared) for name in proposal_workers}

    def _public_bot_proposal_workers(self, payload: Dict[str, Any]) -> list:
        path = (((payload or {}).get("files") or {}).get("proposals_json"))
        if not path:
            export_path = (payload or {}).get("export_path")
            path = os.path.join(export_path, "proposals.json") if export_path else None
        if not path:
            return []
        try:
            import json
            with open(path, "r", encoding="utf-8") as f:
                proposals = json.load(f)
            names = []
            for p in proposals if isinstance(proposals, list) else []:
                name = p.get("strategy") or p.get("worker")
                if name and name not in names:
                    names.append(name)
            return names
        except Exception:
            return []

    def _apply_public_bot_promotion_evidence(self, payload: Dict[str, Any], metrics: Dict[str, Any], evidence: Optional[Dict[str, Any]] = None) -> None:
        """Compatibility record only. Legacy integrations cannot promote live stages."""
        symbol = payload.get("symbol") or metrics.get("symbol")
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        if not symbol or not ds or not hasattr(ds, "upsert_promotion_record"):
            return
        verdict = (evidence or {}).get("verdict") or "missing"
        ds.upsert_promotion_record(symbol, {
            "symbol": symbol,
            "stage": "research_import",
            "eligible": False,
            "reason": "PHOENIX_PHASE2_REQUIRED",
            "updated_ts": time.time(),
            "source": "public_bot_backtest",
            "run_id": payload.get("run_id"),
            "evidence_id": (evidence or {}).get("evidence_id"),
            "evidence_verdict": verdict,
            "execution_authority": "none",
            "promotion_authority": "none",
            "next_required_phase": 2,
        })

    def _perf_by_worker(self) -> Dict[str, Dict[str, Any]]:
        out = {}
        try:
            for name, stat in (self._worker_perf_stats or {}).items():
                total = max(1, int(stat.get("total") or 0))
                wins = int(stat.get("wins") or 0)
                recent = list(stat.get("recent") or [])
                recent_total = max(1, len(recent))
                recent_wins = sum(1 for x in recent if x)
                win_rate = wins / total
                recent_win_rate = recent_wins / recent_total
                recent_losses = recent_total - recent_wins
                out[name] = {
                    "win_rate": win_rate,
                    "recent_win_rate": recent_win_rate,
                    "avg_r_multiple": recent_win_rate - 0.5,
                    "drawdown": min(1.0, recent_losses / recent_total),
                    "recent_penalties": max(0, recent_losses - recent_wins),
                    "samples": total,
                }
        except Exception:
            return {}
        return out

    def _apply_council_risk_hints(
        self,
        symbol: str,
        sig: str,
        position_size: float,
        latest_price: float,
        base_free: float,
        quote_free: float,
        council_decision: Optional[Dict[str, Any]],
    ) -> tuple:
        hints = (council_decision or {}).get("risk_hints") or {}
        if not hints or sig not in ("BUY", "SELL"):
            return position_size, None
        now = time.time()
        reason = None
        key = (symbol, sig)
        cooldown_until = float(self._council_cooldowns.get(key) or 0.0)
        if cooldown_until > now:
            return 0.0, f"COUNCIL_COOLDOWN({int(cooldown_until - now)}s)"
        if sig == "BUY" and hints.get("entry_allowed") is False:
            return 0.0, "COUNCIL_ENTRY_BLOCK"
        try:
            max_position_pct = hints.get("max_position_pct")
            if max_position_pct is not None and latest_price:
                equity = float(quote_free or 0.0) + (float(base_free or 0.0) * float(latest_price or 0.0))
                cap_usd = equity * max(0.0, float(max_position_pct))
                cap_qty = cap_usd / float(latest_price)
                if sig == "BUY":
                    capped = min(float(position_size or 0.0), cap_qty)
                    if capped < float(position_size or 0.0):
                        reason = f"COUNCIL_SIZE_CAP({float(max_position_pct):.3f})"
                    position_size = capped
                elif sig == "SELL":
                    position_size = min(float(position_size or 0.0), float(base_free or 0.0))
        except Exception:
            pass
        return position_size, reason

    def _mark_council_cooldown(self, symbol: str, sig: str, council_decision: Optional[Dict[str, Any]]) -> None:
        try:
            hints = (council_decision or {}).get("risk_hints") or {}
            cooldown = int(hints.get("cooldown_secs") or 0)
            if symbol and sig in ("BUY", "SELL") and cooldown > 0:
                self._council_cooldowns[(symbol, sig)] = time.time() + cooldown
        except Exception:
            pass

    def set_override_request(self, enabled: bool, reason: str = ""):
        try:
            self.override_request = {"enabled": bool(enabled), "reason": reason or ""}
        except Exception:
            pass

    def get_override_request(self) -> Dict[str, Any]:
        return dict(self.override_request or {"enabled": False, "reason": ""})

    def update_strategy(self, new_strategy_type: str):
        """Update strategy in real-time."""
        self.cfg.strategy_type = new_strategy_type
        self.agents["strategy"] = self._create_strategy(self.cfg)
        logging.info(f"Strategy updated to {new_strategy_type}")

    def enable_network(self, host: Optional[str] = None, port: Optional[int] = None,
                       db: Optional[int] = None, password: Optional[str] = None) -> bool:
        """Enable or reconfigure the Network (Redis) agent at runtime.

        If no parameters are provided, uses stored config from startup. Returns True
        if connected successfully, False otherwise.
        """
        cfg = getattr(self, '_network_cfg', None) or {}
        host = host or cfg.get('host', 'localhost')
        port = port or cfg.get('port', 6379)
        db = db if db is not None else cfg.get('db', 0)
        password = password if password is not None else cfg.get('password')

        # Try primary host first, then fallback to localhost/127.0.0.1 if resolution fails
        hosts_to_try = [host]
        if host not in ("localhost", "127.0.0.1"):
            hosts_to_try.extend(["localhost", "127.0.0.1"])

        for h in hosts_to_try:
            try:
                self.network = NetworkAgent(host=h, port=port, db=db, password=password)
                if self.network.is_connected():
                    logging.info(f"Network Agent connected to Redis at {h}:{port}")
                    return True
                else:
                    logging.warning(f"Network Agent failed to connect to Redis at {h}:{port}.")
                    self.network = None
            except Exception as e:
                logging.warning(f"Network Agent enable failed for {h}:{port}: {e}")
                self.network = None

        return False

    # -------------------------
    # Execution event handler (called by ExecutionAgent._emit)
    # -------------------------
    def on_trade_execution(self, evt: Dict[str, Any]) -> None:
        try:
            p = evt.get('payload') if isinstance(evt, dict) else evt
            intent_id = p.get('intent_id')
            status = p.get('status')
            client_order_id = p.get('client_order_id')
            order_id = p.get('order_id')

            if not intent_id:
                logging.info(f"Execution event without intent_id: {p}")
                return

            intent = self.intents.get(intent_id)
            if not intent:
                logging.info(f"Unknown intent_id in execution event: {intent_id}")
                return

            # update stored intent
            intent['last_update_ts'] = time.time()
            intent['last_status'] = status
            if client_order_id:
                intent['client_order_id'] = client_order_id
            if order_id:
                intent['order_id'] = order_id

            # Terminal handling
            if status in ("FILLED", "REJECTED", "CANCELED", "EXPIRED", "ERROR", "PRECHECK_FAILED"):
                intent['state'] = 'DONE'
                intent['final_status'] = status
                logging.info(f"Intent {intent_id} finished with status {status}")
                # Write to logging/data_store if present
                try:
                    trade = {
                        'intent_id': intent_id,
                        'symbol': intent.get('symbol'),
                        'side': intent.get('action'),
                        'quantity': intent.get('qty'),
                        'price': intent.get('price'),
                        'status': status,
                        'order_id': intent.get('order_id')
                    }
                    if self.agents.get('logging'):
                        self.agents['logging'].log_trade(trade)
                        self.agents['logging'].update_metrics(trade)
                    if self.agents.get('data_store'):
                        self.agents['data_store'].store_trade(trade)
                    # Inform performance agent of the execution so it can update PnL
                    try:
                        perf = self.agents.get('performance')
                        if perf and hasattr(perf, 'process_execution'):
                            try:
                                perf.process_execution({'payload': trade})
                            except Exception:
                                logging.exception('performance.process_execution failed')
                    except Exception:
                        logging.exception('Failed to notify performance agent')
                    # Settle governance BUZZ stakes on terminal trade outcome
                    try:
                        self._settle_governance_buzz(intent_id)
                    except Exception:
                        logging.exception('governance buzz settlement failed')
                except Exception:
                    logging.exception('Failed to persist intent final state')
        except Exception:
            logging.exception('on_trade_execution failed')

    def monitor_health(self):
        """Check agent health."""
        for name in self.agents:
            if self.agents[name]:
                self.agent_health[name] = "active"
            else:
                self.agent_health[name] = "inactive"
        # Network and Data Store health
        if self.network and self.network.is_connected():
            self.agent_health["network"] = "active"
        else:
            self.agent_health["network"] = "inactive"
        logging.debug(f"Agent health: {self.agent_health}")

    def _maybe_emit_agent_heartbeats(self):
        """Emit lightweight heartbeat buzzes so the UI shows messages for all agents."""
        try:
            now = time.time()
            interval = getattr(self.cfg, 'agent_heartbeat_sec', 30)
            if (now - self._last_agent_hb_ts) < interval:
                return
            self._last_agent_hb_ts = now
            ts_ms = int(now * 1000)

            def emit(source: str, payload: Dict[str, Any], typ: str = 'buzz.agent.heartbeat'):
                evt = {'buzz': {'type': typ, 'source': source, 'ts': ts_ms}, 'payload': payload}
                try:
                    # use a generic key; raw_events will store each emit
                    self.share_data(typ, evt)
                except Exception:
                    pass

            # Market data heartbeat
            try:
                lp = self.get_shared_data('latest_price')
                if isinstance(lp, dict) and 'payload' in lp:
                    lp = lp.get('payload')
                emit('MARKET_DATA', {
                    'agent': 'market_data',
                    'symbol': getattr(self.cfg, 'symbol', None),
                    'price': lp,
                    'interval': getattr(self.cfg, 'interval', None),
                    'venue': getattr(self.cfg, 'exchange', None),
                })
            except Exception:
                pass

            # CoinGecko heartbeat (cached)
            try:
                base_sym = None
                if self.agents.get('execution'):
                    base_sym = getattr(self.agents['execution'], 'base_asset', None)
                base_sym = base_sym or getattr(self.cfg, 'symbol', '').split('/')[0]
                cg = self._cg_cache.get(base_sym) if base_sym else None
                if cg:
                    emit('COINGECKO', {
                        'agent': 'coingecko',
                        'symbol': base_sym,
                        'price_usd': cg.get('usd'),
                        'market_cap': cg.get('market_cap'),
                        'volume_24h': cg.get('volume_24h'),
                        'change_24h': cg.get('change_24h'),
                    })
            except Exception:
                pass

            # Sentiment / Trend heartbeat
            try:
                emit('SENTIMENT', {
                    'agent': 'sentiment',
                    'symbol': getattr(self.cfg, 'symbol', None),
                    'sentiment': self._last_sentiment,
                })
            except Exception:
                pass
            try:
                emit('TREND', {
                    'agent': 'trend',
                    'symbol': getattr(self.cfg, 'symbol', None),
                    'uptrend': self._last_uptrend,
                    'avg_volume': self._last_avg_vol,
                })
            except Exception:
                pass

            # Execution heartbeat
            try:
                ex = self.agents.get('execution')
                if ex:
                    emit('EXECUTION', {
                        'agent': 'execution',
                        'dry_run': getattr(self.cfg, 'dry_run', True),
                        'base_asset': getattr(ex, 'base_asset', None),
                        'quote_asset': getattr(ex, 'quote_asset', None),
                    })
            except Exception:
                pass

            # Wallet heartbeat
            try:
                if self.agents.get('wallet'):
                    emit('WALLET', {
                        'agent': 'wallet',
                        'balances': self._last_wallet_balances or {},
                    })
            except Exception:
                pass

            # Logging heartbeat
            try:
                lg = self.agents.get('logging')
                if lg and hasattr(lg, 'get_metrics'):
                    emit('LOGGING', {
                        'agent': 'logging',
                        'metrics': lg.get_metrics() or {},
                    })
            except Exception:
                pass

            # Performance heartbeat
            try:
                perf = self.agents.get('performance')
                if perf and hasattr(perf, 'get_current_metrics'):
                    emit('PERFORMANCE', {
                        'agent': 'performance',
                        'metrics': perf.get_current_metrics() or {},
                    })
            except Exception:
                pass

            # Data store heartbeat
            try:
                ds = self.agents.get('data_store')
                if ds:
                    emit('DATA_STORE', {
                        'agent': 'data_store',
                        'db_path': getattr(ds, 'db_path', None),
                    })
            except Exception:
                pass

            # Oracle / Council / Nurse heartbeats
            try:
                if self.agents.get('oracle'):
                    emit('ORACLE', {
                        'agent': 'oracle',
                        'regime': (self._last_regime or {}).get('regime'),
                        'confidence': (self._last_regime or {}).get('confidence'),
                    })
            except Exception:
                pass
            try:
                if self.agents.get('council'):
                    emit('COUNCIL', {
                        'agent': 'council',
                        'proposal_count': (self._last_council or {}).get('count', 0),
                    })
            except Exception:
                pass
            try:
                if self.agents.get('nurse'):
                    emit('NURSE', {
                        'agent': 'nurse',
                        'summary': self._last_nurse or {},
                    })
            except Exception:
                pass

            # Worker heartbeats (latest proposal summaries)
            try:
                if self._last_worker_proposals:
                    for p in self._last_worker_proposals:
                        emit(p.get('strategy', 'WORKER'), {
                            'agent': p.get('strategy', '').lower(),
                            'action': p.get('action'),
                            'strength': p.get('signal_strength'),
                            'notes': p.get('notes'),
                        })
            except Exception:
                pass

            # Phase-1 Observation Swarm heartbeat
            try:
                observer = self.agents.get('observation_swarm')
                if observer and hasattr(observer, 'status'):
                    emit('OBSERVATION_SWARM', observer.status())
            except Exception:
                pass

            # Phase-2 Hypothesis Swarm heartbeat
            try:
                hypothesis = self.agents.get('hypothesis_swarm')
                if hypothesis and hasattr(hypothesis, 'status'):
                    emit('HYPOTHESIS_SWARM', hypothesis.status())
            except Exception:
                pass

            # UI heartbeat
            try:
                if self.agents.get('ui'):
                    emit('UI', {'agent': 'ui', 'status': 'running'})
            except Exception:
                pass

            # Coordinator heartbeat
            try:
                emit('COORDINATOR', {
                    'agent': 'coordinator',
                    'symbol': getattr(self.cfg, 'symbol', None),
                    'interval': getattr(self.cfg, 'interval', None),
                    'dry_run': getattr(self.cfg, 'dry_run', True),
                    'exchange': getattr(self.cfg, 'exchange', None),
                })
            except Exception:
                pass

            # Network heartbeat
            try:
                if self.network:
                    emit('NETWORK', {'agent': 'network', 'connected': self.network.is_connected()})
            except Exception:
                pass
        except Exception:
            logging.exception('Agent heartbeat emission failed')

    def start_background_tasks(self):
        """Start background threads for monitoring."""
        self.running = True
        # Health monitoring thread
        health_thread = threading.Thread(target=self._health_monitor_loop)
        health_thread.daemon = True
        health_thread.start()
        self.threads.append(health_thread)

        shadow_flight = self.agents.get("shadow_flight")
        validation_lab = self.agents.get("validation_lab")
        execution_lab = self.agents.get("execution_lab")
        hypothesis = self.agents.get("hypothesis_swarm")
        observer = self.agents.get("observation_swarm")
        if shadow_flight and bool(getattr(self.cfg, "phase5_shadow_enabled", True)) and hasattr(shadow_flight, "start"):
            try:
                shadow_flight.start()
            except Exception:
                logging.exception("Shadow Flight failed to start")
        elif validation_lab and bool(getattr(self.cfg, "phase4_validation_enabled", True)) and hasattr(validation_lab, "start"):
            try:
                validation_lab.start()
            except Exception:
                logging.exception("Validation Lab failed to start")
        elif execution_lab and bool(getattr(self.cfg, "phase3_execution_lab_enabled", True)) and hasattr(execution_lab, "start"):
            try:
                execution_lab.start()
            except Exception:
                logging.exception("Execution Lab failed to start")
        elif hypothesis and bool(getattr(self.cfg, "phase2_hypotheses_enabled", True)) and hasattr(hypothesis, "start"):
            try:
                hypothesis.start()
            except Exception:
                logging.exception("Hypothesis Swarm failed to start")
        elif observer and hasattr(observer, "start"):
            try:
                observer.start()
            except Exception:
                logging.exception("Observation Swarm failed to start")

        # Start UI if enabled
        if self.agents.get("ui"):
            self.agents["ui"].start()

    def _health_monitor_loop(self):
        report_counter = 0
        eval_counter = 0
        while self.running:
            self.monitor_health()
            report_counter += 1
            eval_counter += 1
            if report_counter >= 10:  # Every 10 minutes
                if self.agents.get("logging"):
                    try:
                        self.agents["logging"].generate_report()
                    except Exception:
                        pass
                report_counter = 0
            if eval_counter >= 5:  # Every 5 minutes
                if self.agents.get("performance") and self.agents.get("data_store") and hasattr(self.agents.get("data_store"), 'get_recent_trades'):
                    try:
                        trades = self.agents["data_store"].get_recent_trades(100)
                        self.agents["performance"].evaluate_strategy_performance(trades, self.cfg.strategy_type)
                    except Exception:
                        pass
                eval_counter = 0
            time.sleep(60)

    def reload_config(self, new_cfg):
        """Reload configuration and reinitialize agents."""
        logging.info("Reloading configuration...")
        self.cfg = new_cfg

        # Stop current agents
        self.running = False
        shadow_flight = self.agents.get("shadow_flight") if hasattr(self, "agents") else None
        if shadow_flight and hasattr(shadow_flight, "stop"):
            try:
                shadow_flight.stop(timeout=5)
            except Exception:
                logging.exception("Shadow Flight failed to stop during reload")
        validation_lab = self.agents.get("validation_lab") if hasattr(self, "agents") else None
        if validation_lab and hasattr(validation_lab, "stop"):
            try:
                validation_lab.stop(timeout=5)
            except Exception:
                logging.exception("Validation Lab failed to stop during reload")
        execution_lab = self.agents.get("execution_lab") if hasattr(self, "agents") else None
        if execution_lab and hasattr(execution_lab, "stop"):
            try:
                execution_lab.stop(timeout=5)
            except Exception:
                logging.exception("Execution Lab failed to stop during reload")
        hypothesis = self.agents.get("hypothesis_swarm") if hasattr(self, "agents") else None
        if hypothesis and hasattr(hypothesis, "stop"):
            try:
                hypothesis.stop(timeout=5)
            except Exception:
                logging.exception("Hypothesis Swarm failed to stop during reload")
        observer = self.agents.get("observation_swarm") if hasattr(self, "agents") else None
        if observer and hasattr(observer, "stop"):
            try:
                observer.stop(timeout=5)
            except Exception:
                logging.exception("Observation Swarm failed to stop during reload")
        for t in self.threads:
            t.join(timeout=5)

        # Reinitialize agents
        self.agents = {}
        self.agent_health = {}
        self.tasks = []
        self.network = None
        self.threads = []
        self.last_close_time = None

        self._initialize_agents()

        # Create new client if API keys changed
        client = None
        if getattr(self.cfg, "exchange", "binance").lower() == "kraken":
            try:
                import ccxt
                if self.cfg.kraken_api_key and self.cfg.kraken_api_secret:
                    client = ccxt.kraken({
                        "apiKey": self.cfg.kraken_api_key,
                        "secret": self.cfg.kraken_api_secret,
                        "enableRateLimit": True
                    })
                    logging.info("Kraken client reinitialized successfully")
            except Exception as e:
                logging.warning(f"Failed to reinitialize Kraken client: {e}")
        else:
            if self.cfg.binance_api_key and self.cfg.binance_api_secret:
                try:
                    from binance.client import Client
                    client = Client(self.cfg.binance_api_key, self.cfg.binance_api_secret)
                    if self.cfg.binance_testnet:
                        client.API_URL = "https://testnet.binance.vision/api"
                    logging.info("Binance client reinitialized successfully")
                except Exception as e:
                    logging.warning(f"Failed to reinitialize Binance client: {e}")

        # Always reinitialize so non-exchange agents (wallet/UI/data store) come back up.
        # Initialize handles None client internally.
        self.initialize(client)

        logging.info("Configuration reloaded successfully")

    def _get_cg_data(self, base_sym: str):
        """Return cached CoinGecko data for base_sym, respecting a minimum interval and
        applying exponential backoff on failures to avoid rate-limiting the API.
        Expected returned dict keys: 'usd', 'market_cap', 'volume_24h', 'change_24h'
        """
        now = time.time()
        interval = getattr(self.cfg, 'coingecko_poll_seconds', 30)
        backoff = self._cg_backoff.get(base_sym, 0)
        last = self._cg_last.get(base_sym, 0)
        cached = self._cg_cache.get(base_sym)

        effective_interval = max(5, interval + backoff)
        if cached is not None and (now - last) < effective_interval:
            return cached

        # Try to fetch fresh data
        try:
            data = self.agents['coingecko'].spot_price_usd(base_sym)
            # Expected spot_price_usd may return {'usd': price, ...}
            if not data:
                raise ValueError('empty coingecko response')

            # Normalize fields - agents/coingecko implementation may differ
            cg = {
                'usd': data.get('usd') if isinstance(data, dict) else None,
                'market_cap': None,
                'volume_24h': None,
                'change_24h': None
            }
            # try to augment with separate calls if provided (but avoid flooding)
            try:
                mc = getattr(self.agents['coingecko'], 'market_cap_usd', None)
                if callable(mc):
                    cg['market_cap'] = mc(base_sym)
            except Exception:
                cg['market_cap'] = cg.get('market_cap')
            try:
                vol = getattr(self.agents['coingecko'], 'volume_24h_usd', None)
                if callable(vol):
                    cg['volume_24h'] = vol(base_sym)
            except Exception:
                cg['volume_24h'] = cg.get('volume_24h')
            try:
                ch = getattr(self.agents['coingecko'], 'price_change_24h', None)
                if callable(ch):
                    cg['change_24h'] = ch(base_sym)
            except Exception:
                cg['change_24h'] = cg.get('change_24h')

            # success: reset backoff and store cache
            self._cg_backoff[base_sym] = 0
            self._cg_cache[base_sym] = cg
            self._cg_last[base_sym] = now
            return cg
        except Exception as e:
            # failure: increase backoff and keep previous cache if available
            prev = self._cg_backoff.get(base_sym, 0)
            # increase by doubling and add small jitter
            new_backoff = min(prev * 2 + 5 if prev else 10, 300)
            self._cg_backoff[base_sym] = new_backoff
            self._cg_last[base_sym] = now
            logging.warning(f"CoinGecko fetch failed for {base_sym}: {e} - backing off {new_backoff}s")
            return self._cg_cache.get(base_sym)

    def run_loop(self):
        self.start_background_tasks()
        last_close_time = None

        while self.running:
            try:
                # Emit periodic agent heartbeats so UI has messages for all agents
                try:
                    self._maybe_emit_agent_heartbeats()
                except Exception:
                    pass

                # Track system performance
                if self.agents.get("performance"):
                    start_op = time.time()
                    self.agents["performance"].track_system_metrics()
                    self.agents["performance"].track_response_time("system_metrics", start_op)

                # Skip trading loop if market data agent is not available
                if not self.agents.get("market_data"):
                    logging.info("Market Data Agent not available, skipping trading loop.")
                    time.sleep(self.cfg.poll_seconds)
                    continue

                # Skip trading loop if execution agent is not available
                if not self.agents.get("execution"):
                    logging.info("Execution Agent not available, skipping trading loop.")
                    time.sleep(self.cfg.poll_seconds)
                    continue

                # Multi-symbol mode: pick the best actionable symbol and switch
                if getattr(self.cfg, "multi_symbol_enabled", False):
                    try:
                        best_symbol = self._select_best_symbol()
                        if best_symbol and best_symbol != self.cfg.symbol:
                            self._switch_symbol(best_symbol)
                    except Exception:
                        pass

                # Fetch closes and volumes; handle failures gracefully
                try:
                    close_times, closes = self.agents["market_data"].fetch_closes(self.cfg.lookback)
                except Exception:
                    close_times, closes = [], []

                try:
                    volumes = self.agents["market_data"].fetch_volumes(self.cfg.lookback)
                except Exception:
                    volumes = []
                if not close_times:
                    logging.warning("No candles returned; retrying.")
                    time.sleep(self.cfg.poll_seconds)
                    continue

                latest_close_time = close_times[-1]
                latest_price = closes[-1]
                self.share_data("latest_price", latest_price)
                # Publish market data buzz so downstream agents and UI get real-time updates.
                try:
                    orderbook_snapshot = None
                    if (
                        bool(getattr(self.cfg, "orderbook_capture_enabled", True))
                        and self.agents.get("market_data")
                        and hasattr(self.agents["market_data"], "fetch_orderbook")
                    ):
                        orderbook_snapshot = self.agents["market_data"].fetch_orderbook(limit=int(getattr(self.cfg, "orderbook_capture_depth", 5) or 5))
                        if isinstance(orderbook_snapshot, dict):
                            orderbook_snapshot["venue"] = getattr(self.cfg, "exchange", None)
                            orderbook_snapshot["ts"] = int(time.time() * 1000)
                            self.share_data("buzz.market.orderbook", {
                                "buzz": {"type": "buzz.market.orderbook", "source": "MARKET_DATA", "ts": int(time.time() * 1000)},
                                "payload": orderbook_snapshot,
                            })
                except Exception:
                    orderbook_snapshot = None

                try:
                    self.share_data('buzz.market.data', {
                        'buzz': {'type': 'buzz.market.data', 'source': 'MARKET_DATA', 'ts': int(time.time() * 1000)},
                        'payload': {
                            'symbol': self.cfg.symbol,
                            'price': latest_price,
                            'interval': self.cfg.interval,
                            'venue': getattr(self.cfg, 'exchange', None),
                            'bid': (orderbook_snapshot or {}).get("bid") if isinstance(orderbook_snapshot, dict) else None,
                            'ask': (orderbook_snapshot or {}).get("ask") if isinstance(orderbook_snapshot, dict) else None,
                            'spread_pct': (orderbook_snapshot or {}).get("spread_pct") if isinstance(orderbook_snapshot, dict) else None,
                            'top_of_book_depth_usd': (orderbook_snapshot or {}).get("top_of_book_depth_usd") if isinstance(orderbook_snapshot, dict) else None,
                            'ts': int(time.time() * 1000),
                        }
                    })
                except Exception:
                    pass

                # Only act once per new candle close (prevents over-trading on same candle)
                if self.last_close_time == latest_close_time:
                    time.sleep(self.cfg.poll_seconds)
                    continue
                self.last_close_time = latest_close_time

                # Phase 3 coin selection (periodic)
                try:
                    self._maybe_select_coin(volumes)
                except Exception:
                    pass

                # Fetch balances using timeout wrapper to avoid blocking on exchange throttle/network
                try:
                    bal = None
                    if self.agents.get("execution"):
                        bal = self._call_with_timeout(self.agents["execution"].balances, timeout=5)
                    if bal and isinstance(bal, (list, tuple)) and len(bal) >= 2:
                        base_free, quote_free = bal[0], bal[1]
                    else:
                        base_free, quote_free = 0.0, 0.0
                except Exception:
                    base_free, quote_free = 0.0, 0.0

                # Regime Oracle snapshot
                regime_snapshot = None
                try:
                    if self.agents.get("oracle"):
                        regime_snapshot = self.agents["oracle"].update(self.agents.get("market_data"), self.agents.get("execution"))
                        self._last_regime = regime_snapshot
                        self.share_data("buzz.regime.snapshot", {
                            "buzz": {"type": "buzz.regime.snapshot", "source": "ORACLE", "ts": int(time.time() * 1000)},
                            "payload": regime_snapshot,
                        })
                except Exception:
                    regime_snapshot = None

                # Collect strategy proposals via Council
                proposals = []
                council_pack = None
                try:
                    if self.agents.get("council") and self.strategy_workers:
                        proposals, council_pack = self.agents["council"].collect(
                            self.strategy_workers,
                            closes,
                            volumes,
                            latest_price,
                            self.cfg.symbol,
                            regime_snapshot=regime_snapshot,
                            perf_by_worker=self._perf_by_worker(),
                        )
                        self._last_council = council_pack
                        self._last_worker_proposals = proposals
                        self._record_signal_marketplace_round(
                            proposals,
                            symbol=self.cfg.symbol,
                            context={"source": "single_symbol_council", "latest_price": latest_price},
                        )
                except Exception:
                    proposals = []

                council_decision = None
                try:
                    council_decision = (council_pack or {}).get("decision")
                except Exception:
                    council_decision = None

                decision = None
                # OpenClaw autonomy override: allow the autonomous agent to drive decisions
                if getattr(self.cfg, "openclaw_autonomy_enabled", False):
                    try:
                        openclaw = self.agents.get("openclaw")
                        if openclaw and hasattr(openclaw, "decide"):
                            autonomy_decision = openclaw.decide(
                                council_decision=council_decision,
                                proposals=proposals,
                                regime_snapshot=regime_snapshot,
                                cfg=self.cfg,
                            )
                            if autonomy_decision:
                                approved = bool(autonomy_decision.get("approved"))
                                decision = {
                                    "approved": approved,
                                    "action": autonomy_decision.get("action") or "HOLD",
                                    "strategy": autonomy_decision.get("strategy") or "OPENCLAW",
                                    "position_size": None,
                                    "rationale": autonomy_decision.get("rationale") or "OPENCLAW_AUTONOMY",
                                    "signal_id": autonomy_decision.get("signal_id"),
                                    "svs": autonomy_decision.get("score"),
                                    "ts": int(time.time() * 1000),
                                    "autonomy": True,
                                }
                                self.share_data("buzz.governance.decision", {
                                    "buzz": {"type": "buzz.governance.decision", "source": "AUTONOMOUS", "ts": int(time.time() * 1000)},
                                    "payload": decision,
                                })
                    except Exception as e:
                        logging.exception("Error during OpenClaw autonomy decision", exc_info=e)

                # Governance decision (Queen)
                if decision is None:
                    try:
                        if self.governance:
                            exec_quality = {}
                            try:
                                client = getattr(self.agents.get("execution"), "client", None)
                                if client and hasattr(client, "fetch_ticker"):
                                    t = client.fetch_ticker(self.cfg.symbol)
                                    bid = t.get("bid")
                                    ask = t.get("ask")
                                    if bid and ask and bid > 0:
                                        exec_quality["spread_pct"] = (ask - bid) / bid
                            except Exception:
                                # Best-effort: spread data is optional for governance decisions
                                pass
                                logging.exception("Error fetching ticker for execution quality")
                            try:
                                exec_agent = self.agents.get("execution")
                                if exec_agent and hasattr(exec_agent, "health_snapshot"):
                                    hs = exec_agent.health_snapshot() or {}
                                    if "order_unconfirmed_ms" in hs:
                                        exec_quality["order_unconfirmed_ms"] = hs.get("order_unconfirmed_ms")
                                    if "api_failures_60s" in hs:
                                        exec_quality["api_failures_60s"] = hs.get("api_failures_60s")
                                    for k in (
                                        "quote_output_ratio",
                                        "min_output_ratio",
                                        "price_impact_pct",
                                        "gas_drag_pct",
                                        "gas_usd",
                                        "route_from_usd",
                                        "route_to_usd",
                                    ):
                                        if k in hs:
                                            exec_quality[k] = hs.get(k)
                            except Exception:
                                # Best-effort: health metrics are optional for governance decisions
                                pass
                                logging.exception("Error getting execution agent health snapshot")
                            try:
                                if self._dex_margin_oracle and bool(getattr(self.cfg, "dex_margin_oracle_enabled", True)):
                                    quote_usd = float(getattr(self.cfg, "quote_order_size", 1.0) or 1.0)
                                    exec_quality.update(self._dex_margin_oracle.exec_quality_for_symbol(self.cfg.symbol, amount_usd=quote_usd))
                                    self.share_data("buzz.dex.margin", {
                                        "buzz": {"type": "buzz.dex.margin", "source": "DEX_MARGIN_ORACLE", "ts": int(time.time() * 1000)},
                                        "payload": self._dex_margin_oracle.analyze_symbol(self.cfg.symbol, amount_usd=quote_usd),
                                    })
                            except Exception:
                                pass
                            perf_metrics = {}
                            try:
                                if self.agents.get("logging"):
                                    perf_metrics = self.agents["logging"].get_metrics() or {}
                            except Exception as e:
                                # Default to empty metrics if logging agent is unavailable or fails.
                                # Governance can still make decisions without performance metrics.
                                logging.debug(f"Failed to retrieve performance metrics: {e}")
                                perf_metrics = {}
                            portfolio = {
                                "base_free": base_free,
                                "quote_free": quote_free,
                                "latest_price": latest_price,
                            }
                            decision = self.governance.decide(regime_snapshot or {}, proposals, portfolio, exec_quality, perf_metrics, self.cfg)
                            if decision:
                                decision["symbol"] = self.cfg.symbol
                                self.share_data("buzz.governance.decision", {
                                    "buzz": {"type": "buzz.governance.decision", "source": "QUEEN", "ts": int(time.time() * 1000)},
                                    "payload": decision,
                                })
                    except Exception:
                        decision = None

                # Cycle snapshot/update (2 min per symbol by default)
                try:
                    self._update_cycle(self.cfg.symbol, latest_price, proposals, decision)
                except Exception:
                    pass

                # Nurse review (periodic)
                try:
                    if self.agents.get("nurse"):
                        self._last_nurse = self.agents["nurse"].review()
                except Exception:
                    pass

                # Inject nurse risk metrics into council decision (best-effort)
                try:
                    if council_decision and self._last_nurse:
                        metrics = (self._last_nurse.get("risk_metrics") or {})
                        if metrics:
                            council_decision.setdefault("risk", {}).setdefault("metrics", {}).update(metrics)
                except Exception:
                    pass

                sig = (decision or {}).get("action") or "HOLD"
                signal_id = (decision or {}).get("signal_id")
                decision_strategy = (decision or {}).get("strategy") or getattr(self.cfg, "strategy_type", None)
                decision_reason = (decision or {}).get("rationale") or ""
                # Fallback to legacy strategy if governance is disabled
                if not getattr(self.cfg, "governance_authoritative", True):
                    try:
                        sig = self.agents["strategy"].signal(closes)
                        signal_id = getattr(self.agents.get("strategy"), "_last_emitted", {}).get("signal_id")
                        decision_strategy = getattr(self.cfg, "strategy_type", None)
                        decision_reason = "LEGACY_STRATEGY"
                    except Exception:
                        pass

                # Ratio-based suggestion gate: rebalance based on wallet allocation
                try:
                    ratio_enabled = bool(getattr(self.cfg, "ratio_gate_enabled", True))
                    target_ratio = float(getattr(self.cfg, "target_base_ratio", 0.5) or 0.5)
                    ratio_band = float(getattr(self.cfg, "target_ratio_band", 0.1) or 0.1)
                    ratio_trade_override = bool(getattr(self.cfg, "ratio_gate_trade_override_enabled", False))
                    can_rebalance = ratio_trade_override or sig in ("BUY", "SELL")
                    if ratio_enabled and can_rebalance and latest_price is not None:
                        base_val = float(base_free or 0.0) * float(latest_price or 0.0)
                        quote_val = float(quote_free or 0.0)
                        total_val = base_val + quote_val
                        if total_val > 0:
                            base_ratio = base_val / total_val
                            if base_ratio < (target_ratio - ratio_band):
                                desired = "BUY"
                            elif base_ratio > (target_ratio + ratio_band):
                                desired = "SELL"
                            else:
                                desired = "HOLD"
                            if desired != "HOLD" and sig != desired:
                                decision_reason = (decision_reason or "RATIO_GATE") + f" | RATIO_GATE({base_ratio:.2f}->{desired})"
                                sig = desired
                except Exception:
                    pass

                # Manual override toggle (from UI)
                try:
                    ov = self.get_override_request()
                    if ov and ov.get("enabled") and decision is not None:
                        decision["override_attempt"] = True
                        decision["override_reason"] = ov.get("reason", "")
                        if (not self.cfg.dry_run) and sig in ("BUY", "SELL"):
                            decision["override_used_in_live_mode"] = True
                            decision_reason = (decision_reason or "OVERRIDE") + " | OVERRIDE_LIVE"
                        else:
                            decision_reason = (decision_reason or "OVERRIDE") + " | OVERRIDE_REQUEST"
                except Exception:
                    pass
                policy_snapshot = {
                    "cooldown_sec": getattr(self.cfg, "strategy_cooldown", None),
                    "max_notional_usd": getattr(self.cfg, "max_notional", None),
                    "spread_guard_pct": getattr(self.cfg, "spread_guard_pct", None),
                    "governance": "authoritative",
                    "council_risk_hints": (council_decision or {}).get("risk_hints") if council_decision else None,
                }

                # Position size and risk (use StrategyAgent as sizing helper)
                try:
                    position_size = self.agents["strategy"].position_size(quote_free, latest_price, self.cfg.risk_pct)
                    risk_metrics = self.agents["strategy"].risk_assessment(closes)
                except Exception:
                    position_size = 0.0
                    risk_metrics = {}
                # Override with governance sizing only when a positive size is provided
                if decision and decision.get("position_size") is not None:
                    try:
                        gov_size = float(decision.get("position_size") or 0.0)
                        if gov_size > 0:
                            position_size = gov_size
                    except Exception:
                        pass

                # Action-aware sizing: use base balance for SELL, quote balance for BUY
                try:
                    if sig == "SELL":
                        # size as a fraction of base holdings
                        base_size = float(base_free or 0.0) * float(getattr(self.cfg, "risk_pct", 0.01) or 0.01)
                        # if base_size too small but we have enough to meet min_trade_usd, use that
                        min_usd = float(getattr(self.cfg, "min_trade_usd", 0.0) or 0.0)
                        if latest_price and min_usd:
                            min_base = float(min_usd) / float(latest_price)
                            if base_free and base_free >= min_base:
                                base_size = max(base_size, min_base)
                        position_size = max(0.0, min(float(base_free or 0.0), base_size))
                    elif sig == "BUY":
                        # if risk-based size is below min but fixed quote_order_size is available, use it
                        min_usd = float(getattr(self.cfg, "min_trade_usd", 0.0) or 0.0)
                        quote_order = float(getattr(self.cfg, "quote_order_size", 0.0) or 0.0)
                        if latest_price and min_usd and quote_order and quote_free and quote_free >= quote_order:
                            notional = float(position_size or 0.0) * float(latest_price or 0.0)
                            if notional < min_usd:
                                position_size = float(quote_order) / float(latest_price)
                except Exception:
                    pass

                # Apply Council risk hints before SwarmGuard and final notional checks.
                try:
                    hinted_size, hint_reason = self._apply_council_risk_hints(
                        self.cfg.symbol,
                        sig,
                        float(position_size or 0.0),
                        float(latest_price or 0.0),
                        float(base_free or 0.0),
                        float(quote_free or 0.0),
                        council_decision,
                    )
                    if hinted_size != position_size:
                        position_size = hinted_size
                    if hint_reason:
                        decision_reason = (decision_reason or "COUNCIL_RISK") + f" | {hint_reason}"
                except Exception:
                    pass

                # SwarmGuard phase 1: liquidity/fee/regime gating
                guard_veto_reason = None
                try:
                    if getattr(self.cfg, "swarmguard_enabled", False):
                        sg = self.agents.get("swarmguard")
                        orderbook = None
                        try:
                            client = getattr(self.agents.get("execution"), "client", None)
                            if client and hasattr(client, "fetch_order_book"):
                                orderbook = client.fetch_order_book(self.cfg.symbol, limit=5)
                        except Exception:
                            orderbook = None
                        verdict = sg.evaluate(
                            decision or {},
                            position_size,
                            latest_price,
                            volumes,
                            orderbook,
                            exec_quality,
                            regime_snapshot,
                            base_free,
                            quote_free,
                            proposals,
                            council_decision,
                        ) if sg else None
                        if verdict:
                            try:
                                payload = {
                                    "decision": verdict.get("decision"),
                                    "reason": verdict.get("reason"),
                                    "position_size": verdict.get("position_size"),
                                    "action": sig,
                                    "strategy": decision_strategy,
                                    "symbol": self.cfg.symbol,
                                    "ts": int(time.time()*1000),
                                }
                                if verdict.get("rulebook"):
                                    payload["rulebook"] = verdict.get("rulebook")
                                if verdict.get("risk") is not None:
                                    payload["risk"] = verdict.get("risk")
                                if verdict.get("evidence") is not None:
                                    payload["evidence"] = verdict.get("evidence")
                                if verdict.get("risk"):
                                    payload["risk"] = verdict.get("risk")
                                if verdict.get("evidence"):
                                    payload["evidence"] = verdict.get("evidence")
                                sg.emit(payload)
                            except Exception:
                                pass
                            if verdict.get("decision") == "VETO":
                                guard_veto_reason = verdict.get("reason") or "SWARMGUARD_VETO"
                                position_size = 0.0
                            elif verdict.get("decision") == "THROTTLE":
                                try:
                                    position_size = float(verdict.get("position_size") or position_size)
                                    decision_reason = (decision_reason or "SWARMGUARD") + f" | {verdict.get('reason')}"
                                except Exception:
                                    pass
                except Exception:
                    pass

                # Capital allocator: keep reserve/core/experimental buckets conservative.
                try:
                    adjusted_size, cap_reason = self._apply_capital_policy(self.cfg.symbol, sig, float(position_size or 0.0), float(latest_price or 0.0))
                    if adjusted_size != position_size:
                        position_size = adjusted_size
                        decision_reason = (decision_reason or "CAPITAL_POLICY") + f" | {cap_reason}"
                except Exception:
                    pass

                # Clamp position sizing to configured min/max USD notional
                try:
                    min_usd = float(getattr(self.cfg, "min_trade_usd", 0.0) or 0.0)
                    max_usd = float(getattr(self.cfg, "max_trade_usd", 0.0) or 0.0)
                    notional = float(position_size or 0.0) * float(latest_price or 0.0)
                    if min_usd and notional < min_usd:
                        if sig == "SELL" and getattr(self.cfg, "swarmguard_small_trade_bypass", False):
                            # Allow small sells to proceed even if below min_usd, but do NOT upsize to full balance
                            if base_free and latest_price:
                                min_base = float(min_usd) / float(latest_price)
                                target = float(position_size or 0.0)
                                if target <= 0:
                                    target = min_base
                                position_size = max(0.0, min(float(base_free), target))
                                decision_reason = (decision_reason or "SMALL_SELL_BYPASS") + f" (min_usd={min_usd})"
                            else:
                                position_size = 0.0
                                decision_reason = (decision_reason or "SIZE_BELOW_MIN") + f" (min_usd={min_usd})"
                        elif sig == "BUY" and getattr(self.cfg, "swarmguard_small_trade_bypass", False):
                            # Allow small buys to proceed even if below min_usd, but do NOT upsize to full balance
                            if quote_free and latest_price:
                                max_qty = float(quote_free) / float(latest_price)
                                min_base = float(min_usd) / float(latest_price)
                                target = float(position_size or 0.0)
                                if target <= 0:
                                    target = min_base
                                position_size = max(0.0, min(max_qty, target))
                                decision_reason = (decision_reason or "SMALL_BUY_BYPASS") + f" (min_usd={min_usd})"
                            else:
                                position_size = 0.0
                                decision_reason = (decision_reason or "SIZE_BELOW_MIN") + f" (min_usd={min_usd})"
                        else:
                            position_size = 0.0
                            decision_reason = (decision_reason or "SIZE_BELOW_MIN") + f" (min_usd={min_usd})"
                    elif max_usd and notional > max_usd and latest_price:
                        position_size = float(max_usd) / float(latest_price)
                        decision_reason = (decision_reason or "SIZE_CLAMPED") + f" (max_usd={max_usd})"
                except Exception:
                    pass

                base_sym = self.agents["execution"].base_asset
                cg_data = None
                cg_price = None
                market_cap = None
                vol_24h = None
                change_24h = None
                if self.agents.get("coingecko"):
                    try:
                        cg_data = self._get_cg_data(base_sym)
                        if cg_data:
                            cg_price = cg_data.get('usd')
                            market_cap = cg_data.get('market_cap')
                            vol_24h = cg_data.get('volume_24h')
                            change_24h = cg_data.get('change_24h')
                    except Exception:
                        cg_data = None
                cg_note = f" | CoinGecko {base_sym}/USD={cg_price:.2f}" if cg_price else ""
                sentiment = self.agents["sentiment"].get_sentiment(base_sym) if self.agents.get("sentiment") else None
                uptrend = self.agents["trend"].is_uptrend(closes) if self.agents.get("trend") else None
                avg_vol = self.agents["trend"].average_volume(volumes) if self.agents.get("trend") else None
                # store last sentiment/trend for heartbeat messages
                self._last_sentiment = sentiment
                self._last_uptrend = uptrend
                self._last_avg_vol = avg_vol
                # Store market data snapshot
                if self.agents.get("data_store") and cg_data:
                    market_snapshot = {
                        "price": cg_price,
                        "volume": vol_24h,
                        "change_24h": change_24h,
                        "market_cap": market_cap,
                        "sentiment": sentiment,
                        "uptrend": uptrend
                    }
                    self.agents["data_store"].store_market_data(base_sym, market_snapshot)
                avg_vol = self.agents["market_data"].average_volume(volumes)
                try:
                    self._maybe_publish_market_bee_snapshot()
                except Exception:
                    pass

                # Optional wallet readout (guarded to avoid blocking when RPC is unresponsive)
                wallet_note = ""
                new_txs = []
                if self.agents.get("wallet"):
                    try:
                        eth_bal = self._call_with_timeout(self.agents["wallet"].eth_balance, timeout=3)
                    except Exception:
                        eth_bal = None
                    try:
                        tok_bal = self._call_with_timeout(self.agents["wallet"].erc20_balance, timeout=3)
                    except Exception:
                        tok_bal = None

                    if eth_bal is not None:
                        try:
                            if tok_bal is not None:
                                wallet_note = f" | Wallet ETH={eth_bal:.4f}, {self.agents['wallet'].token_symbol}={tok_bal:.4f}"
                                # Store wallet balances
                                if self.agents.get("data_store"):
                                    self.agents["data_store"].store_wallet_balance(self.cfg.watch_address, "ETH", eth_bal)
                                    self.agents["data_store"].store_wallet_balance(self.cfg.watch_address, self.agents['wallet'].token_symbol, tok_bal)
                            else:
                                wallet_note = f" | Wallet ETH={eth_bal:.4f}"
                                if self.agents.get("data_store"):
                                    self.agents["data_store"].store_wallet_balance(self.cfg.watch_address, "ETH", eth_bal)
                        except Exception:
                            # ignore storage errors
                            pass

                    try:
                        new_txs = self._call_with_timeout(self.agents["wallet"].detect_new_transactions, timeout=3) or []
                    except Exception:
                        new_txs = []

                if new_txs:
                    for tx in new_txs:
                        logging.info(f"New wallet transaction: {tx.get('hash')} - {tx.get('value')} wei from {tx.get('from')} to {tx.get('to')}")
                try:
                    self._last_wallet_balances = {
                        "eth": eth_bal,
                        "token": tok_bal,
                        "token_symbol": getattr(self.agents.get("wallet"), "token_symbol", None) if self.agents.get("wallet") else None,
                    }
                except Exception:
                    pass

                # Build safe formatted values
                market_cap_str = f"{market_cap:.0f}" if isinstance(market_cap, (int, float)) else "N/A"
                vol24_str = f"{vol_24h:.0f}" if isinstance(vol_24h, (int, float)) else "N/A"
                change24_str = f"{change_24h:.2f}" if isinstance(change_24h, (int, float)) else "N/A"
                sentiment_str = f"{sentiment:.2f}" if isinstance(sentiment, (int, float)) else "N/A"
                uptrend_str = str(uptrend) if uptrend is not None else "N/A"
                avg_vol_str = f"{avg_vol:.0f}" if isinstance(avg_vol, (int, float)) else "N/A"

                logging.info(
                    f"Candle closed @ {latest_close_time} | price={latest_price:.2f} "
                    f"| signal={sig} | Position Size: {position_size:.6f} | Risk: {risk_metrics} | Binance bal: {self.agents['execution'].base_asset}={base_free:.6f} {self.agents['execution'].quote_asset}={quote_free:.2f}"
                    f"{cg_note} | Market Cap: {market_cap_str} | 24h Vol: {vol24_str} | 24h Change: {change24_str}% | Sentiment: {sentiment_str} | Uptrend: {uptrend_str} | Avg Vol: {avg_vol_str}"
                    f"{wallet_note}"
                )

                # Kill Switch gating: keep data flowing but block execution when HALT/THROTTLE.
                ks = self.agents.get("kill_switch")
                ks_state = {}
                ks_mode = None
                allow_exec = True
                try:
                    if ks and hasattr(ks, "get_state"):
                        ks_state = ks.get_state() or {}
                        ks_mode = ks_state.get("state")
                        if ks_mode == "HALT":
                            allow_exec = False
                        elif ks_mode == "THROTTLE":
                            # Allow very small trades to pass during THROTTLE
                            bypass_notional = getattr(self.cfg, "throttle_bypass_notional", None)
                            if bypass_notional is None:
                                bypass_notional = getattr(self.cfg, "max_notional", 0.0)
                            try:
                                notional = float(position_size or 0.0) * float(latest_price or 0.0)
                            except Exception:
                                notional = 0.0
                            if bypass_notional and notional <= float(bypass_notional):
                                allow_exec = True
                            else:
                                allow_exec = False
                except Exception:
                    allow_exec = True

                # Simple risk controls / position caps
                if sig == "BUY":
                    if guard_veto_reason:
                        try:
                            self.share_data('buzz.coordinator.decision', {
                                "symbol": self.cfg.symbol,
                                "action": "BUY",
                                "decision": "VETO",
                                "reason": guard_veto_reason,
                                "signal_id": signal_id,
                                "strategy": decision_strategy,
                                "policy_snapshot": policy_snapshot,
                            })
                        except Exception:
                            pass
                        continue
                    if position_size <= 0:
                        try:
                            self.share_data('buzz.coordinator.decision', {
                                "symbol": self.cfg.symbol,
                                "action": "BUY",
                                "decision": "VETO",
                                "reason": decision_reason or "SIZE_BELOW_MIN",
                                "signal_id": signal_id,
                                "strategy": decision_strategy,
                                "policy_snapshot": policy_snapshot,
                            })
                        except Exception:
                            pass
                        continue
                    if not allow_exec:
                        logging.warning(f"Kill switch {ks_mode} - vetoing BUY execution but continuing data feed.")
                        try:
                            self.share_data('buzz.coordinator.decision', {
                                "symbol": self.cfg.symbol,
                                "action": "BUY",
                                "decision": "VETO",
                                "reason": f"KILL_SWITCH_{ks_mode}",
                                "signal_id": signal_id,
                                "strategy": decision_strategy,
                                "policy_snapshot": policy_snapshot,
                            })
                        except Exception:
                            pass
                        continue
                    # Coordinator now manages intent creation and delegates execution to ExecutionAgent.
                    # Preliminary fraud/feasibility checks
                    if self.agents.get("security") and self.agents.get("data_store"):
                        recent_trades = self.agents["data_store"].get_recent_trades(20)
                        trade_check = {"symbol": self.cfg.symbol, "side": "BUY", "quantity": position_size, "price": latest_price}
                        fraud = self.agents["security"].detect_fraud(trade_check, recent_trades)
                        if fraud:
                            logging.error(f"Fraud detected, vetoing BUY: {fraud}")
                            continue

                    # Enforce security arming: do not create intents if unarmed
                    sec = self.agents.get('security')
                    if sec and not getattr(sec, 'is_armed', lambda: False)():
                        logging.warning('Trading is unarmed - vetoing BUY intent')
                        try:
                            self.share_data('buzz.coordinator.decision', {
                                "symbol": self.cfg.symbol,
                                "action": "BUY",
                                "decision": "VETO",
                                "reason": "UNARMED",
                                "signal_id": signal_id,
                                "strategy": decision_strategy,
                                "policy_snapshot": policy_snapshot,
                            })
                        except Exception:
                            pass
                        continue

                    if getattr(self.cfg, "max_position_base", 0):
                        buy_qty = min(position_size, self.cfg.max_position_base - base_free)
                    else:
                        buy_qty = position_size
                    if buy_qty <= 0:
                        logging.info("BUY skipped: already at/above max base position cap.")
                        continue
                    if quote_free < buy_qty * latest_price:
                        logging.info("BUY skipped: insufficient quote balance.")
                        continue
                    spend_ok, spend_reason = self._wallet_spend_allowed(buy_qty * latest_price)
                    if not spend_ok:
                        try:
                            self.share_data('buzz.coordinator.decision', {
                                "symbol": self.cfg.symbol,
                                "action": "BUY",
                                "decision": "VETO",
                                "reason": spend_reason or "WALLET_SPEND_CAP",
                                "signal_id": signal_id,
                                "strategy": decision_strategy,
                                "policy_snapshot": policy_snapshot,
                            })
                        except Exception:
                            pass
                        continue

                    # Create intent and client_order_id
                    self._intent_counter += 1
                    intent_id = f"intent-{int(time.time())}-{self.cfg.symbol}-{self._intent_counter}"
                    client_order_id = f"{intent_id}-A"

                    # store intent minimal record
                    self.intents[intent_id] = {
                        "symbol": self.cfg.symbol,
                        "action": "BUY",
                        "qty": buy_qty,
                        "price": latest_price,
                        "client_order_id": client_order_id,
                        "state": "SENT",
                        "created_ts": time.time()
                    }

                    # Emit coordinator decision into shared store for UI/debug
                    try:
                        self.share_data('buzz.coordinator.decision', {
                            "intent_id": intent_id,
                            "symbol": self.cfg.symbol,
                            "action": "BUY",
                            "decision": "APPROVE",
                            "reason": decision_reason or "POLICY_OK",
                            "signal_id": signal_id,
                            "strategy": decision_strategy,
                            "policy_snapshot": policy_snapshot,
                        })
                    except Exception:
                        pass
                    self._mark_council_cooldown(self.cfg.symbol, "BUY", council_decision)

                    # Call execution agent with idempotency ids
                    try:
                        exec_agent = self.agents.get("execution")
                        if exec_agent:
                            # ExecutionAgent wrapper supports client_order_id + intent_id kwargs
                            res = self._call_with_timeout(getattr(exec_agent, 'buy_market_quote'), 15, buy_qty * latest_price, client_order_id=client_order_id, intent_id=intent_id, ts=int(time.time()*1000))
                            if res is None and getattr(self.cfg, "onchain_enabled", False) and getattr(self.cfg, "onchain_fallback_to_cex", False):
                                err = None
                                try:
                                    if hasattr(exec_agent, "get_last_error"):
                                        err = exec_agent.get_last_error()
                                except Exception:
                                    err = None
                                if err and err.get("class") in ("GAS_TOO_HIGH", "SWAP_FAILED"):
                                    cex_exec = self._get_cex_exec_for_symbol(self.cfg.symbol)
                                    if cex_exec:
                                        # Re-evaluate balances on CEX so we don't overshoot
                                        fb_base, fb_quote = 0.0, 0.0
                                        try:
                                            fb_bal = self._call_with_timeout(cex_exec.balances, timeout=5)
                                            if fb_bal and isinstance(fb_bal, (list, tuple)) and len(fb_bal) >= 2:
                                                fb_base, fb_quote = fb_bal[0], fb_bal[1]
                                        except Exception:
                                            pass
                                        fb_buy_qty = position_size
                                        if self.cfg.max_position_base:
                                            fb_buy_qty = min(fb_buy_qty, self.cfg.max_position_base - fb_base)
                                        if fb_buy_qty > 0 and fb_quote >= fb_buy_qty * latest_price:
                                            logging.warning("On-chain BUY blocked by gas; falling back to CEX execution.")
                                            self._call_with_timeout(getattr(cex_exec, 'buy_market_quote'), 15, fb_buy_qty * latest_price, client_order_id=client_order_id, intent_id=intent_id, ts=int(time.time()*1000))
                            # record trade for swarmguard cooldowns
                            try:
                                sg = self.agents.get("swarmguard")
                                if sg and hasattr(sg, "record_trade"):
                                    sg.record_trade()
                            except Exception:
                                pass
                            try:
                                self._record_wallet_spend(buy_qty * latest_price)
                            except Exception:
                                pass
                    except Exception:
                        logging.exception("Execution call failed for BUY")

                elif sig == "SELL":
                    if guard_veto_reason:
                        try:
                            self.share_data('buzz.coordinator.decision', {
                                "symbol": self.cfg.symbol,
                                "action": "SELL",
                                "decision": "VETO",
                                "reason": guard_veto_reason,
                                "signal_id": signal_id,
                                "strategy": decision_strategy,
                                "policy_snapshot": policy_snapshot,
                            })
                        except Exception:
                            pass
                        continue
                    if position_size <= 0:
                        try:
                            self.share_data('buzz.coordinator.decision', {
                                "symbol": self.cfg.symbol,
                                "action": "SELL",
                                "decision": "VETO",
                                "reason": decision_reason or "SIZE_BELOW_MIN",
                                "signal_id": signal_id,
                                "strategy": decision_strategy,
                                "policy_snapshot": policy_snapshot,
                            })
                        except Exception:
                            pass
                        continue
                    if not allow_exec:
                        logging.warning(f"Kill switch {ks_mode} - vetoing SELL execution but continuing data feed.")
                        try:
                            self.share_data('buzz.coordinator.decision', {
                                "symbol": self.cfg.symbol,
                                "action": "SELL",
                                "decision": "VETO",
                                "reason": f"KILL_SWITCH_{ks_mode}",
                                "signal_id": signal_id,
                                "strategy": decision_strategy,
                                "policy_snapshot": policy_snapshot,
                            })
                        except Exception:
                            pass
                        continue
                    # Fraud detection
                    if self.agents.get("security") and self.agents.get("data_store"):
                        recent_trades = self.agents["data_store"].get_recent_trades(20)
                        trade_check = {"symbol": self.cfg.symbol, "side": "SELL", "quantity": min(position_size, base_free), "price": latest_price}
                        fraud = self.agents["security"].detect_fraud(trade_check, recent_trades)
                        if fraud:
                            logging.error(f"Fraud detected, skipping SELL: {fraud}")
                            continue
                    if base_free <= 0:
                        logging.info("SELL skipped: no base balance.")
                    else:
                        # Coordinator-managed SELL intent
                        # Enforce security arming: do not create intents if unarmed
                        sec = self.agents.get('security')
                        if sec and not getattr(sec, 'is_armed', lambda: False)():
                            logging.warning('Trading is unarmed - vetoing SELL intent')
                            try:
                                self.share_data('buzz.coordinator.decision', {
                                    "symbol": self.cfg.symbol,
                                    "action": "SELL",
                                    "decision": "VETO",
                                    "reason": "UNARMED",
                                    "signal_id": signal_id,
                                    "strategy": decision_strategy,
                                    "policy_snapshot": policy_snapshot,
                                })
                            except Exception:
                                pass
                            continue

                        sell_qty = min(position_size, base_free)
                        if sell_qty <= 0:
                            continue
                        self._intent_counter += 1
                        intent_id = f"intent-{int(time.time())}-{self.cfg.symbol}-{self._intent_counter}"
                        client_order_id = f"{intent_id}-A"
                        self.intents[intent_id] = {
                            "symbol": self.cfg.symbol,
                            "action": "SELL",
                            "qty": sell_qty,
                            "price": latest_price,
                            "client_order_id": client_order_id,
                            "state": "SENT",
                            "created_ts": time.time()
                        }
                        try:
                            self.share_data('buzz.coordinator.decision', {
                                "intent_id": intent_id,
                                "symbol": self.cfg.symbol,
                                "action": "SELL",
                                "decision": "APPROVE",
                            "reason": decision_reason or "POLICY_OK",
                                "signal_id": signal_id,
                                "strategy": decision_strategy,
                                "policy_snapshot": policy_snapshot,
                            })
                        except Exception:
                            pass
                        self._mark_council_cooldown(self.cfg.symbol, "SELL", council_decision)
                        try:
                            exec_agent = self.agents.get("execution")
                            if exec_agent:
                                res = self._call_with_timeout(getattr(exec_agent, 'sell_market_base'), 15, sell_qty, client_order_id=client_order_id, intent_id=intent_id, ts=int(time.time()*1000))
                                if res is None and getattr(self.cfg, "onchain_enabled", False) and getattr(self.cfg, "onchain_fallback_to_cex", False):
                                    err = None
                                    try:
                                        if hasattr(exec_agent, "get_last_error"):
                                            err = exec_agent.get_last_error()
                                    except Exception:
                                        err = None
                                    if err and err.get("class") in ("GAS_TOO_HIGH", "SWAP_FAILED"):
                                        cex_exec = self._get_cex_exec_for_symbol(self.cfg.symbol)
                                        if cex_exec:
                                            fb_base = 0.0
                                            try:
                                                fb_bal = self._call_with_timeout(cex_exec.balances, timeout=5)
                                                if fb_bal and isinstance(fb_bal, (list, tuple)) and len(fb_bal) >= 2:
                                                    fb_base = fb_bal[0]
                                            except Exception:
                                                pass
                                            fb_sell_qty = min(position_size, fb_base) if fb_base else 0.0
                                            if fb_sell_qty > 0:
                                                logging.warning("On-chain SELL blocked by gas; falling back to CEX execution.")
                                                self._call_with_timeout(getattr(cex_exec, 'sell_market_base'), 15, fb_sell_qty, client_order_id=client_order_id, intent_id=intent_id, ts=int(time.time()*1000))
                                try:
                                    sg = self.agents.get("swarmguard")
                                    if sg and hasattr(sg, "record_trade"):
                                        sg.record_trade()
                                except Exception:
                                    pass
                        except Exception:
                            logging.exception("Execution call failed for SELL")

                # HOLD: do nothing

                # Check Kill Switch after trade
                if self.agents.get("kill_switch") and self.agents.get("logging"):
                    metrics = self.agents["logging"].get_metrics()
                    triggered, reason = self.agents["kill_switch"].check_kill_switch(metrics)
                    if triggered:
                        try:
                            self.agents["kill_switch"].alert(reason)
                        except Exception:
                            pass
                        logging.error(f"Kill switch triggered: {reason}. Trading halted but data feed continues.")

                # Capture external market tape (large stablecoin prints on Kraken)
                try:
                    self._capture_kraken_tape()
                except Exception as e:
                    logging.debug(f"Tape capture skipped: {e}")

            except Exception as e:
                # Robust error reporting: prefer logging but fall back to stderr if logging unavailable
                try:
                    logging.exception(f"Loop error: {e}")
                except Exception:
                    import traceback, sys
                    traceback.print_exc(file=sys.stderr)

            time.sleep(self.cfg.poll_seconds)

    def _call_with_timeout(self, fn, timeout: float = 3.0, *args, **kwargs):
        """Call a blocking function in a thread with a timeout. Returns None on timeout or exception."""
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(fn, *args, **kwargs)
                try:
                    return future.result(timeout=timeout)
                except concurrent.futures.TimeoutError:
                    logging.warning(f"Timed out calling {getattr(fn, '__name__', str(fn))}")
                    return None
                except Exception as e:
                    logging.warning(f"Exception calling {getattr(fn, '__name__', str(fn))}: {e}")
                    return None
        except Exception as e:
            logging.warning(f"_call_with_timeout helper failure: {e}")
            return None

    def _capture_kraken_tape(self, notional_threshold: float = 2000.0):
        """Poll Kraken trades for stable pairs and store large prints as 'tape' trades."""
        if self.cfg.exchange != "kraken":
            return
        if not (self.agents.get("data_store") and self.agents.get("execution")):
            return

        exec_agent = self.agents.get("execution")
        client = getattr(exec_agent, "client", None)  # ccxt.kraken
        if not client or not hasattr(client, "fetch_trades"):
            return
        pairs = ["USDT/USD", "USDC/USD", "DAI/USD", "USDT/EUR", "USDC/EUR"]
        for pair in pairs:
            try:
                trades = client.fetch_trades(pair, limit=20)
            except Exception:
                continue
            # process trades for this pair
            try:
                last_id = self._tape_last_id.get(pair)
                for t in trades:
                    tid = t.get("id") or t.get("trade_id")
                    if last_id and tid == last_id:
                        break
                    amount = float(t.get("amount") or 0)
                    price = float(t.get("price") or 0)
                    notional = amount * price
                    if notional < notional_threshold:
                        continue
                    ts = t.get("timestamp") or t.get("datetime")
                    if isinstance(ts, (int, float)):
                        from datetime import datetime
                        ts_iso = datetime.fromtimestamp(ts / 1000).isoformat()
                    else:
                        ts_iso = ts or ""
                    sentiment_score = None
                    try:
                        sent = self.agents.get("sentiment")
                        if sent and hasattr(sent, "get_sentiment"):
                            base = pair.split("/")[0]
                            sentiment_score = sent.get_sentiment(base)
                    except Exception:
                        sentiment_score = None
                    trade = {
                        "timestamp": ts_iso,
                        "symbol": pair,
                        "side": (t.get("side") or "").upper(),
                        "quantity": amount,
                        "price": price,
                        "notional": notional,
                        "volume": amount,
                        "order_id": tid,
                        "status": "tape",
                        "venue": "kraken",
                        "sentiment": sentiment_score,
                    }
                    try:
                        win = int(time.time() // self._tape_rate_window)
                        w, cnt = self._tape_rate.get(pair, (win, 0))
                        if w != win:
                            w, cnt = win, 0
                        if cnt >= self._tape_rate_limit:
                            continue
                        self._tape_rate[pair] = (w, cnt + 1)
                    except Exception:
                        pass
                    try:
                        self.agents["data_store"].store_trade(trade)
                        log_agent = self.agents.get("logging")
                        if log_agent:
                            try:
                                log_agent.log_trade(trade)
                            except Exception:
                                pass
                            try:
                                log_agent.update_metrics(trade)
                            except Exception:
                                pass
                        logging.info(f"Tape trade captured {pair} {amount} @ {price} (${notional:,.0f})")
                    except Exception:
                        pass
                if trades:
                    self._tape_last_id[pair] = trades[0].get("id") or trades[0].get("trade_id")
            except Exception:
                continue

    def _maybe_select_coin(self, volumes: Optional[list] = None):
        """Phase 3: select small-cap candidates and optionally switch symbol."""
        try:
            if not getattr(self.cfg, "coin_selection_enabled", False):
                return
            now = time.time()
            interval = int(getattr(self.cfg, "coin_selection_interval_sec", 600) or 600)
            if (now - getattr(self, "_last_coin_select_ts", 0)) < interval:
                return
            self._last_coin_select_ts = now
            selector = getattr(self, "_coin_selector", None)
            if not selector:
                return
            client = getattr(self, "_client", None)
            onchain_harvest = bool(getattr(self.cfg, "volatility_harvest_enabled", False)) and bool(getattr(self.cfg, "onchain_enabled", False))
            if not client and not onchain_harvest:
                return
            candidates = selector.select_candidates(client)
            if candidates:
                # publish selection buzz
                try:
                    self.share_data("buzz.coin.selection", {
                        "buzz": {"type": "buzz.coin.selection", "source": "SWARMGUARD", "ts": int(time.time()*1000)},
                        "payload": {
                            "top": candidates,
                            "symbol": candidates[0].get("symbol"),
                        }
                    })
                except Exception:
                    pass
                # auto-switch symbol if enabled
                if getattr(self.cfg, "coin_selection_auto_switch", True) and not getattr(self.cfg, "multi_symbol_enabled", False):
                    top_symbol = candidates[0].get("symbol")
                    if top_symbol and top_symbol != getattr(self.cfg, "symbol", ""):
                        # For on-chain mode, enforce allowlist
                        if getattr(self.cfg, "onchain_enabled", False):
                            allowed = getattr(self.cfg, "onchain_allowed_pairs", []) or []
                            if allowed and top_symbol not in allowed:
                                return
                        self._switch_symbol(top_symbol)
        except Exception:
            return

    def _maybe_publish_market_bee_snapshot(self) -> Optional[Dict[str, Any]]:
        if not bool(getattr(self.cfg, "market_bee_enabled", True)):
            return None
        if not self._dex_margin_oracle:
            return None
        now = time.time()
        interval = int(getattr(self.cfg, "market_bee_snapshot_interval_sec", 300) or 300)
        if now - float(getattr(self, "_last_market_bee_ts", 0.0) or 0.0) < interval:
            cached = self.get_shared_data("buzz.market.bee")
            if isinstance(cached, dict):
                return cached.get("payload") or cached
            return None
        self._last_market_bee_ts = now
        amount_usd = float(getattr(self.cfg, "dex_probe_amount_usd", getattr(self.cfg, "quote_order_size", 1.0)) or 1.0)
        top_n = int(getattr(self.cfg, "market_bee_top_n", 4) or 4)
        snapshot = self._dex_margin_oracle.market_bee_snapshot(top_n=top_n, amount_usd=amount_usd)
        self.share_data("buzz.market.bee", {
            "buzz": {"type": "buzz.market.bee", "source": "MARKET_BEE", "ts": int(time.time() * 1000)},
            "payload": snapshot,
        })
        try:
            self._update_paper_promotion_and_positions(snapshot)
        except Exception:
            pass
        return snapshot

    def executor_statuses(self) -> Dict[str, Any]:
        out = {}
        for key, executor in (self._executor_registry or {}).items():
            try:
                out[key] = executor.status()
            except Exception:
                out[key] = {"name": key, "enabled": False, "reason": "status_error"}
        out["watch_only"] = {
            "MAGIC": "Arbitrum",
            "BEAM": "BNB",
        }
        return out

    def worker_plane_snapshot(self) -> Dict[str, Any]:
        proposals = []
        for p in (self._last_worker_proposals or []):
            try:
                proposals.append({
                    "worker": p.get("worker") or p.get("strategy") or p.get("source"),
                    "signal": p.get("signal"),
                    "confidence": p.get("confidence"),
                    "reason": p.get("reason"),
                    "metadata": p.get("metadata") or {},
                })
            except Exception:
                continue
        return {
            "perf_by_worker": self._perf_by_worker(),
            "perf_storage": "sqlite_worker_performance",
            "last_regime": self._last_regime or {},
            "last_council": self._last_council or {},
            "last_worker_proposals": proposals[-50:],
            "cooldowns": dict(getattr(self, "_council_cooldowns", {}) or {}),
        }

    def integration_control_values(self) -> Dict[str, Any]:
        keys = [
            "dry_run",
            "live_mode",
            "profile_path",
            "profile_name",
            "profile_reason",
            "exchange",
            "symbol",
            "interval",
            "quote_order_size",
            "max_notional",
            "min_trade_usd",
            "max_trade_usd",
            "multi_symbol_enabled",
            "multi_symbols",
            "coin_selection_enabled",
            "coin_selection_auto_switch",
            "coin_selection_top_n",
            "coin_selection_include",
            "coin_selection_exclude",
            "coin_selection_quote_assets",
            "wallet_safety_enabled",
            "wallet_max_daily_spend_usd",
            "wallet_max_token_exposure_pct",
            "watch_address",
            "erc20_token_address",
            "onchain_enabled",
            "dex_provider",
            "onchain_chain_id",
            "onchain_prefer_l2",
            "onchain_l2_chain_id",
            "onchain_allowed_pairs",
            "dex_min_roundtrip_ratio",
            "dex_min_liquidity_usd",
            "dex_max_price_impact_pct",
            "market_bee_enabled",
            "market_bee_top_n",
            "orderbook_capture_enabled",
            "orderbook_capture_depth",
            "ml_research_lab_enabled",
            "ml_model_families_enabled",
            "local_crypto_bot_implementations_enabled",
            "execution_parity_max_latency_ms",
            "execution_parity_max_slippage_pct",
            "execution_parity_min_fill_ratio",
            "execution_parity_max_queue_position_risk",
            "signal_marketplace_min_originality",
            "signal_marketplace_max_drawdown",
            "signal_marketplace_min_stability",
            "signal_marketplace_min_realized_samples",
            "signal_marketplace_reward_scale",
            "signal_marketplace_weight_strength",
            "signal_marketplace_weight_realized_outcome",
            "signal_marketplace_weight_originality",
            "signal_marketplace_weight_stability",
            "signal_marketplace_weight_win_rate",
            "signal_marketplace_weight_drawdown_penalty",
            "pair_max_drawdown_pct",
            "pairlist_min_volume_24h_usd",
            "pairlist_max_spread_pct",
            "pairlist_max_abs_change_24h_pct",
            "pairlist_min_age_sec",
            "hummingbot_v2_default_executor",
            "hummingbot_v2_twap_duration_sec",
            "hummingbot_v2_twap_interval_sec",
            "hummingbot_v2_grid_width_pct",
            "hummingbot_v2_dca_steps",
            "hummingbot_v2_dca_step_pct",
            "hummingbot_v2_leverage",
            "hummingbot_sidecar_live_enabled",
            "hummingbot_sidecar_command",
            "hummingbot_sidecar_config_dir",
            "market_making_advisors_enabled",
            "market_making_quote_placement_enabled",
            "public_bot_metrics_auto_promote",
            "pmm_simple_min_liquidity_usd",
            "pmm_simple_max_spread_pct",
            "pmm_simple_min_quote_spread_pct",
            "pmm_dynamic_min_volume_24h_usd",
            "pmm_dynamic_max_spread_pct",
            "pmm_dynamic_max_abs_change_24h_pct",
            "pmm_dynamic_min_quote_spread_pct",
        ]
        return {key: getattr(self.cfg, key, None) for key in keys}

    def update_integration_controls(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        numeric_fields = {
            "quote_order_size": float,
            "max_notional": float,
            "min_trade_usd": float,
            "max_trade_usd": float,
            "coin_selection_top_n": int,
            "wallet_max_daily_spend_usd": float,
            "wallet_max_token_exposure_pct": float,
            "onchain_chain_id": int,
            "onchain_l2_chain_id": int,
            "dex_min_roundtrip_ratio": float,
            "dex_min_liquidity_usd": float,
            "dex_max_price_impact_pct": float,
            "market_bee_top_n": int,
            "orderbook_capture_depth": int,
            "execution_parity_max_latency_ms": int,
            "execution_parity_max_slippage_pct": float,
            "execution_parity_min_fill_ratio": float,
            "execution_parity_max_queue_position_risk": float,
            "signal_marketplace_min_originality": float,
            "signal_marketplace_max_drawdown": float,
            "signal_marketplace_min_stability": float,
            "signal_marketplace_min_realized_samples": int,
            "signal_marketplace_reward_scale": float,
            "signal_marketplace_weight_strength": float,
            "signal_marketplace_weight_realized_outcome": float,
            "signal_marketplace_weight_originality": float,
            "signal_marketplace_weight_stability": float,
            "signal_marketplace_weight_win_rate": float,
            "signal_marketplace_weight_drawdown_penalty": float,
            "pair_max_drawdown_pct": float,
            "pairlist_min_volume_24h_usd": float,
            "pairlist_max_spread_pct": float,
            "pairlist_max_abs_change_24h_pct": float,
            "pairlist_min_age_sec": int,
            "hummingbot_v2_twap_duration_sec": int,
            "hummingbot_v2_twap_interval_sec": int,
            "hummingbot_v2_grid_width_pct": float,
            "hummingbot_v2_dca_steps": int,
            "hummingbot_v2_dca_step_pct": float,
            "hummingbot_v2_leverage": int,
            "pmm_simple_min_liquidity_usd": float,
            "pmm_simple_max_spread_pct": float,
            "pmm_simple_min_quote_spread_pct": float,
            "pmm_dynamic_min_volume_24h_usd": float,
            "pmm_dynamic_max_spread_pct": float,
            "pmm_dynamic_max_abs_change_24h_pct": float,
            "pmm_dynamic_min_quote_spread_pct": float,
        }
        text_fields = {
            "exchange",
            "symbol",
            "interval",
            "watch_address",
            "erc20_token_address",
            "dex_provider",
            "hummingbot_v2_default_executor",
            "hummingbot_sidecar_command",
            "hummingbot_sidecar_config_dir",
        }
        list_fields = {
            "multi_symbols",
            "coin_selection_include",
            "coin_selection_exclude",
            "coin_selection_quote_assets",
            "onchain_allowed_pairs",
            "ml_model_families_enabled",
        }
        bool_fields = {
            "dry_run",
            "live_mode",
            "multi_symbol_enabled",
            "coin_selection_enabled",
            "coin_selection_auto_switch",
            "wallet_safety_enabled",
            "onchain_enabled",
            "onchain_prefer_l2",
            "market_bee_enabled",
            "orderbook_capture_enabled",
            "ml_research_lab_enabled",
            "local_crypto_bot_implementations_enabled",
            "hummingbot_sidecar_live_enabled",
            "market_making_advisors_enabled",
            "market_making_quote_placement_enabled",
            "public_bot_metrics_auto_promote",
        }
        updates = {}
        errors = {}
        protected_false_only = {
            "live_mode", "onchain_enabled", "coin_selection_auto_switch",
            "hummingbot_sidecar_live_enabled", "market_making_quote_placement_enabled",
            "public_bot_metrics_auto_promote",
        }
        for key, caster in numeric_fields.items():
            if key not in payload or payload.get(key) in (None, ""):
                continue
            try:
                value = caster(payload.get(key))
                if key.endswith("_pct") and value < 0:
                    raise ValueError("must be non-negative")
                if key in ("quote_order_size", "max_notional", "min_trade_usd", "max_trade_usd", "wallet_max_daily_spend_usd") and value < 0:
                    raise ValueError("must be non-negative")
                if key in ("coin_selection_top_n", "market_bee_top_n") and value < 1:
                    raise ValueError("must be at least 1")
                if key in ("onchain_chain_id", "onchain_l2_chain_id") and value < 1:
                    raise ValueError("must be a valid chain id")
                if key in ("hummingbot_v2_dca_steps", "hummingbot_v2_leverage") and value < 1:
                    raise ValueError("must be at least 1")
                if key == "hummingbot_v2_leverage" and value != 1:
                    raise ValueError("phoenix_research_requires_leverage_1")
                setattr(self.cfg, key, value)
                updates[key] = value
            except Exception as e:
                errors[key] = str(e)
        for key in text_fields:
            if key not in payload:
                continue
            value = str(payload.get(key) or "")
            if key == "exchange":
                value = value.lower()
                if value not in ("kraken", "binance"):
                    errors[key] = "unsupported_exchange"
                    continue
            if key == "symbol":
                value = value.strip().upper()
            if key == "interval":
                value = value.strip()
            if key == "dex_provider":
                value = value.strip().lower() or "1inch"
            if key == "hummingbot_v2_default_executor":
                value = value.replace("_executor", "").lower()
            if key == "hummingbot_v2_default_executor" and value and value not in ("position", "twap", "grid", "dca", "xemm", "arbitrage"):
                errors[key] = "unsupported_executor"
                continue
            setattr(self.cfg, key, value)
            updates[key] = value
        for key in list_fields:
            if key not in payload:
                continue
            raw = payload.get(key)
            if isinstance(raw, list):
                value = [str(v).strip().upper() for v in raw if str(v).strip()]
            else:
                value = [part.strip().upper() for part in str(raw or "").replace("\n", ",").split(",") if part.strip()]
            setattr(self.cfg, key, value)
            updates[key] = value
        for key in bool_fields:
            if key not in payload:
                continue
            raw = payload.get(key)
            value = raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "yes", "on")
            if key == "dry_run" and not bool(value):
                errors[key] = "phoenix_authority_locked_use_phase6_operator"
                continue
            if key in protected_false_only and bool(value):
                errors[key] = "phoenix_authority_locked_use_dedicated_operator"
                continue
            setattr(self.cfg, key, bool(value))
            updates[key] = bool(value)
        return {
            "ok": not errors,
            "updates": updates,
            "errors": errors,
            "controls": self.integration_control_values(),
        }

    def hummingbot_v2_plan(self, executor_type: str = "position", intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        executor = (self._executor_registry or {}).get("hummingbot_v2")
        if not executor or not hasattr(executor, "plan"):
            return {"ok": False, "executor_type": executor_type, "reason": "hummingbot_v2_executor_unavailable"}
        intent = dict(intent or {})
        intent.setdefault("symbol", getattr(self.cfg, "symbol", "ETH/USDT"))
        intent.setdefault("notional_usd", getattr(self.cfg, "quote_order_size", 0.0))
        return executor.plan(executor_type, intent)

    def hummingbot_lifecycle_action(self, action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        lifecycle = self.agents.get("hummingbot_lifecycle") if hasattr(self, "agents") else None
        if not lifecycle:
            return {"ok": False, "error": "hummingbot_lifecycle_unavailable"}
        payload = payload or {}
        action = str(action or "monitor").lower()
        if action in {"create", "retry", "close"}:
            return {
                "ok": False,
                "error": "phoenix_authority_locked",
                "action": action,
                "allowed_actions": ["monitor", "list", "stop"],
                "next_required_phase": 3,
            }
        if action == "monitor":
            return lifecycle.monitor(payload.get("executor_id"))
        if action == "stop":
            return lifecycle.stop(payload.get("executor_id"), reason=payload.get("reason") or "operator_stop")
        if action == "list":
            return {"ok": True, "executors": lifecycle.list(limit=int(payload.get("limit") or 100))}
        return {"ok": False, "error": "unsupported_lifecycle_action", "action": action}

    def public_bot_backtest_export(self, engine: str = "freqtrade", symbol: Optional[str] = None, days: int = 30) -> Dict[str, Any]:
        bridge = self.agents.get("public_bot_backtests") if hasattr(self, "agents") else None
        if not bridge:
            return {"ok": False, "error": "public_bot_backtest_bridge_unavailable"}
        return bridge.export(engine=engine, symbol=symbol, days=days)

    def public_bot_backtest_ingest(self, run_id: str, metrics: Optional[Dict[str, Any]] = None, metrics_path: Optional[str] = None) -> Dict[str, Any]:
        bridge = self.agents.get("public_bot_backtests") if hasattr(self, "agents") else None
        if not bridge:
            return {"ok": False, "error": "public_bot_backtest_bridge_unavailable"}
        return bridge.ingest(run_id=run_id, metrics=metrics, metrics_path=metrics_path)

    def public_bot_backtest_apply(self, run_id: str) -> Dict[str, Any]:
        bridge = self.agents.get("public_bot_backtests") if hasattr(self, "agents") else None
        if not bridge:
            return {"ok": False, "error": "public_bot_backtest_bridge_unavailable"}
        if not run_id:
            runs = bridge.list_runs(limit=10) or {}
            for candidate in runs.values():
                if candidate.get("status") == "INGESTED":
                    run_id = candidate.get("run_id")
                    break
            if not run_id and runs:
                run_id = next(iter(runs.values())).get("run_id")
        run = (bridge.list_runs(run_id=run_id) or {}).get(run_id)
        if not run:
            return {"ok": False, "error": "run_not_found", "run_id": run_id}
        applied = self.apply_public_bot_backtest_metrics(run)
        run["worker_updates"] = applied
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        if ds and hasattr(ds, "upsert_public_bot_backtest"):
            ds.upsert_public_bot_backtest(run_id, run)
        return {"ok": bool(applied.get("ok")), "run_id": run_id, "worker_updates": applied}

    def evidence_snapshot(self, symbol: Optional[str] = None, run_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        registry = self.agents.get("evidence_registry") if hasattr(self, "agents") else None
        records = ds.get_evidence_records(symbol=symbol, run_id=run_id, limit=limit) if ds and hasattr(ds, "get_evidence_records") else {}
        return {
            "ok": True,
            "status": registry.status() if registry and hasattr(registry, "status") else {},
            "records": records,
        }

    def ml_candidate_snapshot(self, family: Optional[str] = None, symbol: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        lab = self.agents.get("ml_research_lab") if hasattr(self, "agents") else None
        candidates = ds.get_ml_model_candidates(family=family, symbol=symbol, limit=limit) if ds and hasattr(ds, "get_ml_model_candidates") else {}
        return {
            "ok": True,
            "status": lab.status() if lab and hasattr(lab, "status") else {},
            "candidates": candidates,
            "blueprints": lab.default_blueprints(symbol=symbol) if lab and hasattr(lab, "default_blueprints") else [],
        }

    def execution_parity_snapshot(self, symbol: Optional[str] = None, run_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        parity = self.agents.get("execution_parity") if hasattr(self, "agents") else None
        diagnostics = ds.get_execution_parity_diagnostics(symbol=symbol, run_id=run_id, limit=limit) if ds and hasattr(ds, "get_execution_parity_diagnostics") else {}
        return {
            "ok": True,
            "status": parity.status() if parity and hasattr(parity, "status") else {},
            "diagnostics": diagnostics,
        }

    def signal_marketplace_snapshot(self, symbol: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        marketplace = self.agents.get("signal_marketplace") if hasattr(self, "agents") else None
        rounds = ds.get_signal_marketplace_rounds(symbol=symbol, limit=limit) if ds and hasattr(ds, "get_signal_marketplace_rounds") else {}
        return {
            "ok": True,
            "status": marketplace.status() if marketplace and hasattr(marketplace, "status") else {},
            "rounds": rounds,
        }

    def propose_ml_candidate(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        lab = self.agents.get("ml_research_lab") if hasattr(self, "agents") else None
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        if not lab or not hasattr(lab, "propose"):
            return {"ok": False, "error": "ml_research_lab_unavailable"}
        try:
            features = payload.get("features")
            if isinstance(features, str):
                features = [part.strip() for part in features.replace("\n", ",").split(",") if part.strip()]
            metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
            metrics = dict(metrics or {})
            evidence_id = metrics.get("layer3_evidence_id") or metrics.get("evidence_id")
            run_validation = bool(payload.get("run_validation") or payload.get("validate") or payload.get("validation_runner"))
            evidence = {}
            if run_validation:
                evidence = self._resolve_layer3_evidence(
                    evidence_id=str(evidence_id or payload.get("evidence_id") or payload.get("layer3_evidence_id") or ""),
                    symbol=payload.get("symbol") or getattr(self.cfg, "symbol", "ETH/USD"),
                )
                if not evidence:
                    return {"ok": False, "error": "layer3_evidence_not_found", "evidence_id": evidence_id}
                validation_report = payload.get("validation_report") if isinstance(payload.get("validation_report"), dict) else {}
                runner_metrics = lab.validation_runner(
                    evidence,
                    features=features if isinstance(features, list) else None,
                    report=validation_report,
                ) if hasattr(lab, "validation_runner") else {}
                metrics.update(runner_metrics)
            else:
                metrics["layer3_evidence_verified"] = self._evidence_id_exists(str(evidence_id or ""))
            candidate = lab.propose(
                payload.get("family") or "freqai",
                symbol=payload.get("symbol") or getattr(self.cfg, "symbol", "ETH/USD"),
                objective=payload.get("objective"),
                features=features if isinstance(features, list) else None,
                metrics=metrics,
            )
            if ds and hasattr(ds, "upsert_ml_model_candidate"):
                ds.upsert_ml_model_candidate(candidate)
            try:
                self.share_data("buzz.ml.candidate", {
                    "buzz": {"type": "buzz.ml.candidate", "source": "ML_RESEARCH_LAB", "ts": int(time.time() * 1000)},
                    "payload": {
                        "candidate_id": candidate.get("candidate_id"),
                        "family": candidate.get("family"),
                        "symbol": candidate.get("symbol"),
                        "objective": candidate.get("objective"),
                        "verdict": candidate.get("verdict"),
                        "status": candidate.get("status"),
                        "model_card_path": candidate.get("model_card_path"),
                    },
                })
            except Exception:
                pass
            return {"ok": True, "candidate": candidate}
        except Exception as e:
            logging.exception("Failed to propose ML candidate")
            return {"ok": False, "error": str(e)}

    def _evidence_id_exists(self, evidence_id: str) -> bool:
        if not evidence_id:
            return False
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        if not ds or not hasattr(ds, "get_evidence_records"):
            return False
        try:
            return evidence_id in (ds.get_evidence_records(limit=500) or {})
        except Exception:
            return False

    def _resolve_layer3_evidence(self, evidence_id: str = "", symbol: str = "") -> Dict[str, Any]:
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        if not ds or not hasattr(ds, "get_evidence_records"):
            return {}
        try:
            if evidence_id:
                records = ds.get_evidence_records(limit=500) or {}
                if evidence_id in records:
                    return records.get(evidence_id) or {}
            if symbol:
                records = ds.get_evidence_records(symbol=symbol, limit=1) or {}
                if records:
                    return next(iter(records.values())) or {}
        except Exception:
            return {}
        return {}

    def quote_quality_advice(self, row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        advisors = self.agents.get("market_making_advisors") if hasattr(self, "agents") else None
        if not advisors:
            return {"ok": False, "error": "market_making_advisors_unavailable"}
        if row:
            return {"ok": True, "advice": advisors.advise(row)}
        rows = []
        try:
            snapshot = self.get_shared_data("buzz.market.bee") or {}
            payload = snapshot.get("payload") if isinstance(snapshot, dict) else {}
            rows = payload.get("rows") or payload.get("candidates") or []
        except Exception:
            rows = []
        return {"ok": True, "advice": advisors.advise_many(rows, limit=25), "status": advisors.status()}

    def observation_snapshot(self, symbol: Optional[str] = None, limit: int = 100, compact: bool = False) -> Dict[str, Any]:
        observer = self.agents.get("observation_swarm") if hasattr(self, "agents") else None
        latest = observer.latest_snapshot() if observer and hasattr(observer, "latest_snapshot") else {}
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        history = []
        runs = []
        universe = {"cohorts": {}, "symbols": {}}
        readiness = {
            "phase": 1, "ready_for_phase2_review": False,
            "execution_eligible": False, "reasons": ["data_store_unavailable"],
        }
        if ds:
            try:
                runs = ds.get_observation_runs(limit=min(25, int(limit or 100))) if hasattr(ds, "get_observation_runs") else []
            except Exception:
                runs = []
            if not compact:
                try:
                    history = ds.get_observation_snapshots(symbol=symbol, limit=limit) if hasattr(ds, "get_observation_snapshots") else []
                except Exception:
                    history = []
            if not compact:
                try:
                    universe = ds.get_observation_universe(days=7.0, limit_per_cohort=6) if hasattr(ds, "get_observation_universe") else universe
                except Exception:
                    universe = {"cohorts": {}, "symbols": {}}
            try:
                readiness = ds.get_observation_readiness(
                    required_days=7.0,
                    min_mean_quality=float(getattr(self.cfg, "phase1_observation_min_data_quality", 0.99) or 0.99),
                    min_success_ratio=float(getattr(self.cfg, "phase1_observation_min_success_ratio", 0.90) or 0.90),
                ) if hasattr(ds, "get_observation_readiness") else readiness
            except Exception:
                pass
        if not latest and runs:
            latest = dict((runs[0].get("payload") or {}))
        if compact and isinstance(latest, dict):
            history = list(latest.get("candidates") or [])
        status_payload = (
            observer.status() if observer and hasattr(observer, "status") else {"status": "UNAVAILABLE"}
        )
        if status_payload.get("status") == "UNAVAILABLE" and latest:
            latest_run = latest.get("run") if isinstance(latest.get("run"), dict) else {}
            status_payload = {
                "phase": 1,
                "mode": "observation_only",
                "enabled": bool(getattr(self.cfg, "phase1_observation_enabled", True)),
                "status": str(latest.get("status") or "PERSISTED"),
                "run_count": len(runs),
                "last_error": None,
                "thread_alive": False,
                "execution_wired": False,
                "orders_submitted": 0,
                "symbols_attempted": latest_run.get("symbols_attempted"),
                "symbols_successful": latest_run.get("symbols_successful"),
                "symbols_eligible": latest_run.get("symbols_eligible"),
                "mean_data_quality": latest_run.get("mean_data_quality"),
                "source": "persisted_observation_runs",
            }
        rows = [row for row in history if isinstance(row, dict)]
        eligible_rows = [row for row in rows if row.get("observation_eligible")]
        near_eligible_rows = [
            row for row in rows
            if not row.get("observation_eligible")
            and float(((row.get("values") or {}).get("tradable_opportunity_score") or 0.0)) >= 0.45
        ]
        strict_focus = eligible_rows[: min(8, len(eligible_rows))]
        bench_focus = near_eligible_rows[: min(8, len(near_eligible_rows))]
        avg_spread = (
            round(sum(float(row.get("spread_bps") or 0.0) for row in rows if row.get("spread_bps") is not None) / max(1, len([row for row in rows if row.get("spread_bps") is not None])), 4)
            if rows else None
        )
        avg_depth = (
            round(sum(float(row.get("depth_usd_25bps") or 0.0) for row in rows if row.get("depth_usd_25bps") is not None) / max(1, len([row for row in rows if row.get("depth_usd_25bps") is not None])), 2)
            if rows else None
        )
        avg_freshness = (
            round(sum(float(row.get("freshness_sec") or 0.0) for row in rows if row.get("freshness_sec") is not None) / max(1, len([row for row in rows if row.get("freshness_sec") is not None])), 3)
            if rows else None
        )
        regime_counts: Dict[str, int] = {}
        rejection_counts: Dict[str, int] = {}
        for row in rows:
            values = row.get("values") if isinstance(row.get("values"), dict) else {}
            regime_inputs = values.get("regime_inputs") if isinstance(values.get("regime_inputs"), dict) else {}
            regime = regime_inputs.get("regime_hint")
            if regime:
                regime_counts[str(regime)] = regime_counts.get(str(regime), 0) + 1
            for reason in row.get("rejection_reasons") or []:
                rejection_counts[str(reason)] = rejection_counts.get(str(reason), 0) + 1
        top_symbol = eligible_rows[0] if eligible_rows else (rows[0] if rows else None)
        summary = {
            "phase": 1,
            "top_symbol": {
                "symbol": top_symbol.get("symbol"),
                "data_quality": top_symbol.get("data_quality"),
                "spread_bps": top_symbol.get("spread_bps"),
                "depth_usd_25bps": top_symbol.get("depth_usd_25bps"),
                "freshness_sec": top_symbol.get("freshness_sec"),
                "score": top_symbol.get("score"),
            } if top_symbol else None,
            "avg_spread_bps": avg_spread,
            "avg_depth_usd_25bps": avg_depth,
            "avg_freshness_sec": avg_freshness,
            "eligible_count": len(eligible_rows),
            "near_eligible_count": len(near_eligible_rows),
            "history_count": len(rows),
            "strict_eligible_symbols": [
                {
                    "symbol": row.get("symbol"),
                    "score": row.get("score"),
                    "spread_bps": row.get("spread_bps"),
                    "depth_usd_25bps": row.get("depth_usd_25bps"),
                    "tradable_opportunity_score": ((row.get("values") or {}).get("tradable_opportunity_score")),
                }
                for row in strict_focus
            ],
            "research_bench_symbols": [
                {
                    "symbol": row.get("symbol"),
                    "score": row.get("score"),
                    "tradable_opportunity_score": ((row.get("values") or {}).get("tradable_opportunity_score")),
                    "rejection_reasons": list(row.get("rejection_reasons") or []),
                }
                for row in bench_focus
            ],
            "rejection_hotspots": [
                {"reason": reason, "count": count}
                for reason, count in sorted(rejection_counts.items(), key=lambda item: (-item[1], item[0]))[:6]
            ],
            "universe_cohorts": universe.get("cohorts") or {},
            "near_eligible_symbols": [
                {
                    "symbol": row.get("symbol"),
                    "score": row.get("score"),
                    "tradable_opportunity_score": ((row.get("values") or {}).get("tradable_opportunity_score")),
                    "rejection_reasons": list(row.get("rejection_reasons") or []),
                }
                for row in near_eligible_rows[:6]
            ],
            "regime_mix": [
                {"regime": regime, "count": count}
                for regime, count in sorted(regime_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
            ],
            "why_now": [
                (
                    f"{len(eligible_rows)} of {len(rows)} recent observations are research-eligible."
                    if rows else
                    "No recent observation evidence available yet."
                ),
                (
                    f"{len(near_eligible_rows)} additional symbols look research-useful but are missing one or two gates."
                    if near_eligible_rows else
                    "No near-eligible expansion set has formed yet."
                ),
                (
                    f"Average spread is {avg_spread:.2f} bps with {avg_depth:,.0f} USD depth inside 25 bps."
                    if avg_spread is not None and avg_depth is not None else
                    "Spread/depth averages are still collecting."
                ),
                (
                    f"Current top symbol is {top_symbol.get('symbol')}."
                    if top_symbol else
                    "No top symbol has emerged yet."
                ),
                (
                    "Compact dashboard snapshot is active to keep the page responsive."
                    if compact else
                    "Full observation detail is active."
                ),
            ],
        }
        return {
            "phase": 1,
            "mode": "observation_only",
            "execution_wired": False,
            "orders_submitted": 0,
            "status": status_payload,
            "latest": latest,
            "history": history,
            "runs": runs,
            "universe": universe,
            "readiness": readiness,
            "summary": summary,
        }

    def hypothesis_snapshot(
        self,
        model_id: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 250,
        compact: bool = False,
    ) -> Dict[str, Any]:
        hypothesis = self.agents.get("hypothesis_swarm") if hasattr(self, "agents") else None
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        latest = hypothesis.latest_snapshot() if hypothesis and hasattr(hypothesis, "latest_snapshot") else {}
        runs = forecasts = outcomes = []
        scorecard = {"phase": 2, "models": [], "execution_eligible": False}
        readiness = {
            "phase": 2, "ready_for_phase3_review": False,
            "execution_eligible": False, "reasons": ["data_store_unavailable"],
        }
        settlement = {"examined": 0, "settled": 0, "pending": 0, "execution_wired": False, "orders_submitted": 0}
        if ds:
            try:
                runs = ds.get_hypothesis_runs(limit=min(50, int(limit or 250))) if hasattr(ds, "get_hypothesis_runs") else []
            except Exception:
                runs = []
            if not compact:
                try:
                    settlement = ds.settle_mature_hypothesis_forecasts(
                        tolerance_sec=float(getattr(self.cfg, "phase2_settlement_tolerance_sec", 600) or 600)
                    ) if hasattr(ds, "settle_mature_hypothesis_forecasts") else settlement
                except Exception:
                    pass
                try:
                    forecasts = ds.get_hypothesis_forecasts(model_id=model_id, symbol=symbol, limit=limit) if hasattr(ds, "get_hypothesis_forecasts") else []
                except Exception:
                    forecasts = []
            if not compact:
                try:
                    outcomes = ds.get_hypothesis_outcomes(model_id=model_id, limit=limit) if hasattr(ds, "get_hypothesis_outcomes") else []
                except Exception:
                    outcomes = []
                try:
                    scorecard = ds.get_hypothesis_scorecard() if hasattr(ds, "get_hypothesis_scorecard") else scorecard
                except Exception:
                    pass
            try:
                readiness = ds.get_phase2_readiness(
                    min_forecasts=int(getattr(self.cfg, "phase2_readiness_min_forecasts", 300) or 300),
                    min_settled_non_abstain=int(getattr(self.cfg, "phase2_readiness_min_settled_non_abstain", 100) or 100),
                    min_distinct_days=int(getattr(self.cfg, "phase2_readiness_min_distinct_days", 14) or 14),
                ) if hasattr(ds, "get_phase2_readiness") else readiness
            except Exception:
                pass
        if not latest and runs:
            latest = dict((runs[0].get("payload") or {}))
        if compact and isinstance(latest, dict):
            forecasts = list(latest.get("forecasts") or [])
        status_payload = (
            hypothesis.status() if hypothesis and hasattr(hypothesis, "status") else {"status": "UNAVAILABLE"}
        )
        if status_payload.get("status") == "UNAVAILABLE" and latest:
            status_payload = {
                "phase": 2,
                "mode": "hypothesis_research_only",
                "enabled": bool(getattr(self.cfg, "phase2_hypotheses_enabled", True)),
                "status": str(latest.get("status") or "PERSISTED"),
                "run_count": len(runs),
                "last_error": None,
                "thread_alive": False,
                "horizons_seconds": list(latest.get("horizons_seconds") or []),
                "primary_models": list(((latest.get("run") or {}).get("primary_models") or [])),
                "federated_models": list(((latest.get("run") or {}).get("federated_models") or [])),
                "baseline_models": list(((latest.get("run") or {}).get("baseline_models") or [])),
                "federation": latest.get("federation") or {},
                "execution_wired": False,
                "orders_submitted": 0,
                "source": "persisted_hypothesis_runs",
            }
        leaderboard = sorted(
            [row for row in scorecard.get("models", []) if isinstance(row, dict)],
            key=lambda item: (
                float(item.get("mean_net_bps") if item.get("mean_net_bps") is not None else -10**9),
                int(item.get("settled_trades") or 0),
            ),
            reverse=True,
        )
        symbol_focus: list[Dict[str, Any]] = []
        forecast_rows = [row for row in forecasts if isinstance(row, dict)]
        if forecast_rows:
            grouped: Dict[str, Dict[str, Any]] = {}
            for row in forecast_rows:
                if row.get("abstain"):
                    continue
                symbol_key = str(row.get("symbol") or "UNKNOWN")
                bucket = grouped.setdefault(symbol_key, {
                    "symbol": symbol_key,
                    "forecast_count": 0,
                    "avg_expected_net_bps": 0.0,
                    "avg_probability_positive_net": 0.0,
                    "top_models": set(),
                    "regime_hints": set(),
                })
                bucket["forecast_count"] += 1
                net_bps = row.get("expected_net_bps")
                if net_bps is not None:
                    bucket["avg_expected_net_bps"] += float(net_bps)
                prob = row.get("probability_positive_net")
                if prob is not None:
                    bucket["avg_probability_positive_net"] += float(prob)
                model_name = row.get("model_id")
                if model_name:
                    bucket["top_models"].add(str(model_name))
                inputs = row.get("inputs") if isinstance(row.get("inputs"), dict) else {}
                regime = inputs.get("regime_hint") or inputs.get("regime_inputs", {}).get("regime_hint")
                if regime:
                    bucket["regime_hints"].add(str(regime))
            for bucket in grouped.values():
                count = max(1, int(bucket["forecast_count"]))
                bucket["avg_expected_net_bps"] = round(float(bucket["avg_expected_net_bps"]) / count, 4)
                bucket["avg_probability_positive_net"] = round(float(bucket["avg_probability_positive_net"]) / count, 4)
                bucket["top_models"] = sorted(bucket["top_models"])[:3]
                bucket["regime_hints"] = sorted(bucket["regime_hints"])[:2]
                bucket["explanation"] = (
                    f"{bucket['forecast_count']} non-abstain forecasts, "
                    f"{bucket['avg_expected_net_bps']:.2f} bps average expected net, "
                    f"{bucket['avg_probability_positive_net'] * 100:.1f}% average P(Net+)."
                )
                symbol_focus.append(bucket)
            symbol_focus.sort(
                key=lambda item: (
                    float(item.get("avg_expected_net_bps") or -10**9),
                    float(item.get("avg_probability_positive_net") or 0.0),
                    int(item.get("forecast_count") or 0),
                ),
                reverse=True,
            )

        champion_model = next(
            (row for row in leaderboard if row.get("model_id") == scorecard.get("champion_by_mean_net_bps")),
            leaderboard[0] if leaderboard else None,
        )
        champion_research_model = next(
            (row for row in leaderboard if row.get("model_id") == scorecard.get("champion_research_model_by_mean_net_bps")),
            None,
        )
        expectancy_breakdown = scorecard.get("expectancy_breakdown") or {}
        cohort_breakdown = scorecard.get("cohort_breakdown") or {}
        slice_breakdown = [row for row in scorecard.get("slice_breakdown", []) if isinstance(row, dict)]
        native_diagnostics = [row for row in scorecard.get("native_model_diagnostics", []) if isinstance(row, dict)]
        demotion_recommendations = [row for row in scorecard.get("demotion_recommendations", []) if isinstance(row, dict)]
        abstention_reason_breakdown = [row for row in scorecard.get("abstention_reason_breakdown", []) if isinstance(row, dict)]
        near_miss_recovery_candidates = [row for row in scorecard.get("near_miss_recovery_candidates", []) if isinstance(row, dict)]
        leading_symbol = symbol_focus[0] if symbol_focus else None
        summary = {
            "phase": 2,
            "champion_model": champion_model,
            "champion_research_model": champion_research_model,
            "expectancy_breakdown": expectancy_breakdown,
            "cohort_breakdown": cohort_breakdown,
            "slice_breakdown": slice_breakdown[:12],
            "native_diagnostics": native_diagnostics[:8],
            "demotion_recommendations": demotion_recommendations[:8],
            "abstention_reason_breakdown": abstention_reason_breakdown[:8],
            "near_miss_recovery_candidates": near_miss_recovery_candidates[:8],
            "leading_symbol": leading_symbol,
            "symbol_focus": symbol_focus[:12],
            "top_open_forecasts": forecast_rows[:20],
            "why_now": [
                f"Phase 2 is {'ready' if readiness.get('ready_for_phase3_review') else 'not ready'} for Phase 3 review.",
                (
                    f"Current overall champion is {champion_model.get('model_id')} at "
                    f"{float(champion_model.get('mean_net_bps') or 0.0):.2f} mean net bps."
                    if champion_model else
                    "No settled champion model yet."
                ),
                (
                    f"Best current symbol focus is {leading_symbol.get('symbol')} because "
                    f"{leading_symbol.get('forecast_count')} non-abstain forecasts are clustering there."
                    if leading_symbol else
                    "No non-abstain symbol cluster yet."
                ),
                (
                    f"Native models are currently {expectancy_breakdown.get('native', {}).get('mean_realized_net_bps'):.2f} mean realized net bps."
                    if expectancy_breakdown.get('native', {}).get('mean_realized_net_bps') is not None else
                    "Native models still lack enough settled evidence for a realized expectancy read."
                ),
                (
                    f"{len(demotion_recommendations)} model demotion candidates are currently flagged by settled evidence."
                    if demotion_recommendations else
                    "No model is yet flagged for evidence-based demotion."
                ),
                (
                    f"Cohort leaders are available for {len(cohort_breakdown)} cohort buckets."
                    if cohort_breakdown else
                    "Cohort-level evidence is still accumulating."
                ),
                (
                    f"{len(slice_breakdown)} thesis-regime-symbol-class slices are currently scored."
                    if slice_breakdown else
                    "Slice-level evidence has not accumulated yet."
                ),
                (
                    f"Top abstention pressure is {abstention_reason_breakdown[0].get('reason')} across "
                    f"{int(abstention_reason_breakdown[0].get('count') or 0)} forecasts."
                    if abstention_reason_breakdown else
                    "No abstention reason concentration has formed yet."
                ),
                (
                    f"{len(near_miss_recovery_candidates)} high-quality near-miss ideas are waiting on better confirmation."
                    if near_miss_recovery_candidates else
                    "No high-quality near-miss ideas are currently staged for recovery."
                ),
                (
                    "Live hypothesis runner is attached."
                    if bool(status_payload.get("thread_alive")) else
                    "Displaying persisted Phase 2 evidence from the data store."
                ),
                (
                    "Compact dashboard snapshot is active to keep the page responsive."
                    if compact else
                    "Full hypothesis detail is active."
                ),
            ],
        }
        return {
            "phase": 2,
            "mode": "hypothesis_research_only",
            "execution_wired": False,
            "orders_submitted": 0,
            "status": status_payload,
            "latest": latest,
            "runs": runs,
            "forecasts": forecasts,
            "outcomes": outcomes,
            "scorecard": scorecard,
            "settlement": settlement,
            "readiness": readiness,
            "summary": summary,
        }

    def phase0_snapshot(self) -> Dict[str, Any]:
        authority = self.agents.get("phoenix_authority") if hasattr(self, "agents") else None
        if authority and hasattr(authority, "snapshot"):
            return phase0_snapshot(self.cfg, authority)
        return phase0_snapshot(self.cfg)

    def execution_lab_snapshot(
        self,
        model_id: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 250,
        compact: bool = False,
    ) -> Dict[str, Any]:
        lab = self.agents.get("execution_lab") if hasattr(self, "agents") else None
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        latest = lab.latest_snapshot() if lab and hasattr(lab, "latest_snapshot") else {}
        runs = orders = []
        scorecard = {"phase": 3, "rows": [], "execution_wired": False, "real_orders_submitted": 0}
        readiness = {
            "phase": 3, "ready_for_phase4_review": False,
            "execution_eligible": False, "reasons": ["data_store_unavailable"],
        }
        if ds:
            try:
                runs = ds.get_simulation_runs(limit=min(50, int(limit or 250))) if hasattr(ds, "get_simulation_runs") else []
            except Exception:
                runs = []
            if not compact:
                try:
                    orders = ds.get_simulated_orders(model_id=model_id, symbol=symbol, limit=limit) if hasattr(ds, "get_simulated_orders") else []
                except Exception:
                    orders = []
                try:
                    scorecard = ds.get_execution_scorecard() if hasattr(ds, "get_execution_scorecard") else scorecard
                except Exception:
                    pass
            try:
                readiness = ds.get_phase3_readiness(
                    min_completed=int(getattr(self.cfg, "phase3_readiness_min_completed", 100) or 100),
                    max_mean_2x_loss_bps=float(getattr(self.cfg, "phase3_readiness_max_mean_2x_loss_bps", 50.0) or 50.0),
                ) if hasattr(ds, "get_phase3_readiness") else readiness
            except Exception:
                pass
        if not latest and runs:
            latest = dict(runs[0]) if isinstance(runs[0], dict) else {}
        if compact and isinstance(latest, dict):
            orders = list(latest.get("simulations") or [])
        status_payload = (
            lab.status() if lab and hasattr(lab, "status") else {"status": "UNAVAILABLE"}
        )
        if status_payload.get("status") == "UNAVAILABLE" and (latest or scorecard.get("rows")):
            status_payload = {
                "phase": 3,
                "mode": "execution_simulation_only",
                "enabled": bool(getattr(self.cfg, "phase3_execution_lab_enabled", True)),
                "status": str(latest.get("status") or "PERSISTED"),
                "run_count": len(runs),
                "last_error": None,
                "thread_alive": False,
                "execution_wired": False,
                "real_orders_submitted": 0,
                "source": "persisted_execution_runs",
            }
        rows = [row for row in scorecard.get("rows", []) if isinstance(row, dict)]
        normal_rows = [row for row in rows if row.get("scenario") == "normal"]
        non_baseline_normal = [row for row in normal_rows if not str(row.get("model_id") or "").startswith("baseline_")]
        best_normal = max(
            non_baseline_normal or normal_rows,
            key=lambda row: float(row.get("mean_net_bps") if row.get("mean_net_bps") is not None else -10**9),
            default=None,
        )
        candidate_intake = latest.get("candidate_intake") if isinstance(latest, dict) else {}
        candidate_sample = candidate_intake.get("sample") if isinstance(candidate_intake, dict) else []
        scenario_count = len({str(row.get("scenario") or "") for row in rows if row.get("scenario")})
        policy_count = len({str(row.get("order_policy") or "") for row in rows if row.get("order_policy")})
        avg_cost = (
            round(sum(float(row.get("mean_total_cost_bps") or 0.0) for row in rows if row.get("mean_total_cost_bps") is not None) / max(1, len([row for row in rows if row.get("mean_total_cost_bps") is not None])), 4)
            if rows else None
        )
        avg_latency = (
            round(sum(float(row.get("mean_latency_bps") or 0.0) for row in rows if row.get("mean_latency_bps") is not None) / max(1, len([row for row in rows if row.get("mean_latency_bps") is not None])), 4)
            if rows else None
        )
        profitable_outcomes = sum(
            int(row.get("completed") or 0) * float(row.get("win_rate") or 0.0)
            for row in rows
            if row.get("win_rate") is not None
        )
        completed_outcomes = sum(int(row.get("completed") or 0) for row in rows)
        adaptation_breakdown = scorecard.get("adaptation_breakdown") or {}
        slice_breakdown = [row for row in scorecard.get("slice_execution_breakdown", []) if isinstance(row, dict)]
        adapted_segment = adaptation_breakdown.get("adapted") if isinstance(adaptation_breakdown, dict) else None
        standard_segment = adaptation_breakdown.get("standard") if isinstance(adaptation_breakdown, dict) else None
        robustness_groups: Dict[tuple[str, str], Dict[str, Any]] = {}
        for row in rows:
            key = (str(row.get("model_id") or ""), str(row.get("order_policy") or ""))
            bucket = robustness_groups.setdefault(key, {
                "model_id": key[0],
                "order_policy": key[1],
                "is_baseline": key[0].startswith("baseline_"),
                "scenario_coverage": 0,
                "positive_scenarios": 0,
                "avg_mean_net_bps": 0.0,
                "worst_mean_net_bps": None,
                "completed": 0,
            })
            bucket["scenario_coverage"] += 1
            mean_net = row.get("mean_net_bps")
            if mean_net is not None:
                bucket["avg_mean_net_bps"] += float(mean_net)
                if float(mean_net) > 0:
                    bucket["positive_scenarios"] += 1
                bucket["worst_mean_net_bps"] = float(mean_net) if bucket["worst_mean_net_bps"] is None else min(bucket["worst_mean_net_bps"], float(mean_net))
            bucket["completed"] += int(row.get("completed") or 0)
        robustness_ranking = []
        for bucket in robustness_groups.values():
            coverage = max(1, int(bucket["scenario_coverage"]))
            bucket["avg_mean_net_bps"] = round(float(bucket["avg_mean_net_bps"]) / coverage, 4)
            bucket["robustness_score"] = round(
                float(bucket["avg_mean_net_bps"])
                + min(0.0, float(bucket["worst_mean_net_bps"] or 0.0)) * 0.35
                + float(bucket["positive_scenarios"]) * 2.0,
                4,
            )
            robustness_ranking.append(bucket)
        robustness_ranking.sort(
            key=lambda row: (
                1 if not row.get("is_baseline") else 0,
                float(row.get("robustness_score") or -10**9),
                int(row.get("completed") or 0),
            ),
            reverse=True,
        )
        recovery_candidates = [row for row in candidate_sample if isinstance(row, dict) and bool(row.get("regime_reentry_eligible"))]
        recovery_candidates.sort(
            key=lambda row: (
                float(row.get("recent_regime_historical_mean_net_bps") or -10**9),
                float(row.get("recent_slice_historical_mean_net_bps") or -10**9),
                float(row.get("expected_net_bps") or -10**9),
                float(row.get("edge_quality_score") or -10**9),
            ),
            reverse=True,
        )
        suppressed_candidates = [
            row for row in candidate_sample
            if isinstance(row, dict)
            and not bool(row.get("regime_reentry_eligible"))
            and row.get("regime_historical_mean_net_bps") is not None
            and float(row.get("regime_historical_mean_net_bps") or 0.0) < 0.0
        ]
        suppressed_candidates.sort(
            key=lambda row: (
                float(row.get("regime_historical_mean_net_bps") or 10**9),
                float(row.get("recent_regime_historical_mean_net_bps") or -10**9),
            ),
        )
        recovery_signals = {
            "recovering_candidates": len(recovery_candidates),
            "suppressed_candidates": len(suppressed_candidates),
            "best_recovery_candidate": recovery_candidates[0] if recovery_candidates else None,
            "best_suppressed_candidate": suppressed_candidates[0] if suppressed_candidates else None,
            "recovering_sample": recovery_candidates[:8],
            "suppressed_sample": suppressed_candidates[:8],
        }
        summary = {
            "phase": 3,
            "best_normal_policy": best_normal,
            "best_research_policy": next((row for row in robustness_ranking if not row.get("is_baseline")), None),
            "scenario_count": scenario_count,
            "policy_count": policy_count,
            "avg_total_cost_bps": avg_cost,
            "avg_latency_bps": avg_latency,
            "completed_outcomes": completed_outcomes,
            "profitable_outcomes": int(round(profitable_outcomes)),
            "profitable_rate": round((profitable_outcomes / completed_outcomes), 6) if completed_outcomes else 0.0,
            "adaptation_breakdown": adaptation_breakdown,
            "slice_execution_breakdown": slice_breakdown[:12],
            "robustness_ranking": robustness_ranking[:12],
            "research_winners": [row for row in robustness_ranking if not row.get("is_baseline")][:8],
            "candidate_intake": candidate_intake,
            "recovery_signals": recovery_signals,
            "capabilities": [
                {"name": "deterministic_order_simulation", "active": True},
                {"name": "fill_assumptions", "active": True},
                {"name": "latency_modeling", "active": True},
                {"name": "spread_slippage_modeling", "active": True},
                {"name": "participation_caps", "active": True},
                {"name": "simulated_stop_target_handling", "active": True},
            ],
            "why_now": [
                (
                    f"{scenario_count} stress scenarios across {policy_count} order policies are being scored."
                    if rows else
                    "No execution simulation rows recorded yet."
                ),
                (
                    "Phase 3 intake screened "
                    f"{candidate_intake.get('raw_pool_size', 0)} settled forecasts down to "
                    f"{candidate_intake.get('selected_count', 0)} after expected-net, probability, and history gates."
                    if candidate_intake else
                    "Phase 3 candidate intake gates have not reported yet."
                ),
                (
                    f"{recovery_signals.get('recovering_candidates', 0)} candidates show fresh same-regime recovery evidence strong enough for re-entry."
                    if candidate_intake else
                    "Recovery signals are waiting for candidate intake."
                ),
                (
                    f"{recovery_signals.get('suppressed_candidates', 0)} candidates still look regime-damaged without enough recent repair."
                    if candidate_intake else
                    "Suppression signals are waiting for candidate intake."
                ),
                (
                    f"Best normal-cost policy is {best_normal.get('model_id')} / {best_normal.get('order_policy')} at {float(best_normal.get('mean_net_bps') or 0.0):.2f} mean net bps."
                    if best_normal else
                    "No best normal-cost policy established yet."
                ),
                (
                    f"Average modeled total cost is {avg_cost:.2f} bps and latency cost is {avg_latency:.2f} bps."
                    if avg_cost is not None and avg_latency is not None else
                    "Average cost stack is still collecting."
                ),
                (
                    f"{int(round(profitable_outcomes)):,} of {completed_outcomes:,} completed simulations were profitable, but policy averages are still negative after cost."
                    if completed_outcomes else
                    "No completed simulations yet."
                ),
                (
                    f"{len(slice_breakdown)} execution slices are now being tracked across thesis, regime, cohort, symbol class, and policy."
                    if slice_breakdown else
                    "Slice-level execution evidence has not accumulated yet."
                ),
                (
                    f"Adapted candidates are running at {float(adapted_segment.get('mean_net_bps') or 0.0):.2f} mean net bps across "
                    f"{int(adapted_segment.get('completed') or 0)} completed simulations."
                    if adapted_segment and int(adapted_segment.get("completed") or 0) > 0 else
                    "Adapted research recoveries have not accumulated execution evidence yet."
                ),
                (
                    f"Standard candidates are running at {float(standard_segment.get('mean_net_bps') or 0.0):.2f} mean net bps across "
                    f"{int(standard_segment.get('completed') or 0)} completed simulations."
                    if standard_segment and int(standard_segment.get("completed") or 0) > 0 else
                    "Standard candidates have not accumulated execution evidence yet."
                ),
                (
                    "Compact dashboard snapshot is active to keep the page responsive."
                    if compact else
                    "Full execution-lab detail is active."
                ),
            ],
        }
        return {
            "phase": 3,
            "mode": "execution_simulation_only",
            "execution_wired": False,
            "real_orders_submitted": 0,
            "status": status_payload,
            "latest": latest,
            "runs": runs,
            "orders": orders,
            "scorecard": scorecard,
            "readiness": readiness,
            "summary": summary,
        }

    def validation_lab_snapshot(self, limit: int = 100, compact: bool = False) -> Dict[str, Any]:
        lab = self.agents.get("validation_lab") if hasattr(self, "agents") else None
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        latest = lab.latest_snapshot() if lab and hasattr(lab, "latest_snapshot") else {}
        runs = candidates = []
        readiness = {
            "phase": 4, "ready_for_phase5_review": False,
            "execution_eligible": False, "human_review_required": True,
            "real_orders_submitted": 0, "reasons": ["data_store_unavailable"],
        }
        if ds:
            try:
                runs = ds.get_phase4_validation_runs(limit=min(50, int(limit or 100))) if hasattr(ds, "get_phase4_validation_runs") else []
            except Exception:
                runs = []
            if not compact:
                try:
                    candidates = ds.get_phase4_candidate_results(limit=limit) if hasattr(ds, "get_phase4_candidate_results") else []
                except Exception:
                    candidates = []
            try:
                readiness = ds.get_phase4_readiness() if hasattr(ds, "get_phase4_readiness") else readiness
            except Exception:
                pass
        if not latest and runs:
            latest = dict(runs[0]) if isinstance(runs[0], dict) else {}
        if compact and isinstance(latest, dict):
            candidates = list(latest.get("candidate_results") or [])
        status_payload = lab.status() if lab and hasattr(lab, "status") else {"status": "UNAVAILABLE"}
        if status_payload.get("status") == "UNAVAILABLE" and (latest or candidates):
            status_payload = {
                "phase": 4,
                "mode": "adversarial_validation_only",
                "enabled": bool(getattr(self.cfg, "phase4_validation_enabled", True)),
                "status": str(latest.get("status") or "PERSISTED"),
                "run_count": len(runs),
                "last_error": None,
                "thread_alive": False,
                "execution_wired": False,
                "real_orders_submitted": 0,
                "source": "persisted_validation_runs",
            }
        champion = latest.get("champion") if isinstance(latest, dict) else {}
        pbo = latest.get("pbo") if isinstance(latest, dict) else {}
        candidate_rows = [row for row in candidates if isinstance(row, dict)]
        passing = [row for row in candidate_rows if row.get("passes_candidate_gates")]
        failing = [row for row in candidate_rows if not row.get("passes_candidate_gates")]
        top_fail_reasons: Dict[str, int] = {}
        for row in failing:
            for reason in row.get("reasons") or []:
                key = str(reason or "unknown")
                top_fail_reasons[key] = top_fail_reasons.get(key, 0) + 1
        fail_reason_rows = [
            {"reason": key, "count": count}
            for key, count in sorted(top_fail_reasons.items(), key=lambda item: (-item[1], item[0]))
        ]
        summary = {
            "phase": 4,
            "champion": champion,
            "candidate_count": len(candidate_rows),
            "passing_count": len(passing),
            "failing_count": len(failing),
            "pbo_estimate": pbo.get("pbo_estimate") if isinstance(pbo, dict) else None,
            "top_failure_reasons": fail_reason_rows[:8],
            "why_now": [
                (
                    f"{len(candidate_rows)} candidate policies were stress-tested for fragility."
                    if candidate_rows else
                    "No adversarial validation evidence has been persisted yet."
                ),
                (
                    f"{len(passing)} candidates passed every adversarial gate and {len(failing)} failed at least one gate."
                    if candidate_rows else
                    "No candidate gate outcomes are available yet."
                ),
                (
                    f"Champion is {champion.get('candidate_key')} with robust score {float(champion.get('robust_score') or 0.0):.2f}, "
                    f"bootstrap lower 95% {float(((champion.get('bootstrap') or {}).get('lower_95_bps') or 0.0)):.2f} bps, "
                    f"and walk-forward positive ratio {float(champion.get('walk_forward_positive_ratio') or 0.0):.2f}."
                    if champion else
                    "No champion has been established yet."
                ),
                (
                    f"PBO estimate is {float(pbo.get('pbo_estimate') or 0.0):.3f}; "
                    f"Phase 5 review is {'open' if readiness.get('ready_for_phase5_review') else 'closed'}."
                    if isinstance(pbo, dict) and pbo.get("pbo_estimate") is not None else
                    "PBO estimate is not available yet."
                ),
            ],
        }
        return {
            "phase": 4,
            "mode": "adversarial_validation_only",
            "execution_wired": False,
            "real_orders_submitted": 0,
            "human_review_required": True,
            "status": status_payload,
            "latest": latest,
            "runs": runs,
            "candidates": candidates,
            "readiness": readiness,
            "summary": summary,
        }

    def shadow_flight_snapshot(self, limit: int = 250) -> Dict[str, Any]:
        lab = self.agents.get("shadow_flight") if hasattr(self, "agents") else None
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        latest = lab.latest_snapshot() if lab and hasattr(lab, "latest_snapshot") else {}
        runs = intents = settlements = []
        scorecard = {"phase": 5, "mode": "public_shadow_only", "execution_eligible": False,
                     "transmission_attempts": 0, "real_orders_submitted": 0}
        readiness = {
            "phase": 5, "ready_for_phase6_review": False, "execution_eligible": False,
            "human_review_required": True, "reasons": ["data_store_unavailable"],
            "transmission_attempts": 0, "real_orders_submitted": 0,
        }
        freeze = {}
        if ds:
            try:
                runs = ds.get_phase5_shadow_runs(limit=min(50, int(limit or 250))) if hasattr(ds, "get_phase5_shadow_runs") else []
                intents = ds.get_phase5_shadow_intents(limit=limit) if hasattr(ds, "get_phase5_shadow_intents") else []
                settlements = ds.get_phase5_shadow_settlements(limit=limit) if hasattr(ds, "get_phase5_shadow_settlements") else []
                scorecard = ds.get_phase5_scorecard() if hasattr(ds, "get_phase5_scorecard") else scorecard
                freeze = ds.get_phase5_active_freeze() if hasattr(ds, "get_phase5_active_freeze") else {}
                from strategies.volatility_breakout.shadow_flight import frozen_config_hash
                readiness = ds.get_phase5_readiness(
                    min_distinct_days=int(getattr(self.cfg, "phase5_readiness_min_distinct_days", 30) or 30),
                    min_settled=int(getattr(self.cfg, "phase5_readiness_min_settled", 100) or 100),
                    max_cost_mae_bps=float(getattr(self.cfg, "phase5_readiness_max_cost_mae_bps", 20.0) or 20.0),
                    min_fill_ratio=float(getattr(self.cfg, "phase5_readiness_min_fill_ratio", 0.50) or 0.50),
                    require_positive_mean=bool(getattr(self.cfg, "phase5_readiness_require_positive_mean", True)),
                    current_config_hash=frozen_config_hash(self.cfg),
                ) if hasattr(ds, "get_phase5_readiness") else readiness
            except Exception:
                logging.exception("Shadow flight snapshot failed")
        return {
            "phase": 5,
            "mode": "public_shadow_only",
            "status": lab.status() if lab and hasattr(lab, "status") else {"status": "UNAVAILABLE"},
            "latest": latest,
            "freeze": freeze,
            "runs": runs,
            "intents": intents,
            "settlements": settlements,
            "scorecard": scorecard,
            "readiness": readiness,
            "execution_wired": False,
            "private_exchange_access": False,
            "transmission_attempts": 0,
            "real_orders_submitted": 0,
            "live_eligible": False,
        }

    def canary_snapshot(self, limit: int = 100) -> Dict[str, Any]:
        """Read-only Phase-6 operator projection.

        The ordinary coordinator never constructs a private Kraken client and
        never owns canary arming authority. This endpoint reads persisted
        evidence only, keeping the desktop UI observational.
        """
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        base = {
            "phase": 6,
            "mode": "tiny_live_canary",
            "operator_process_only": True,
            "desktop_arming_enabled": False,
            "automatic_scaling": False,
            "execution_scale_authorized": False,
            "human_review_required": True,
            "live_config_enabled": bool(getattr(self.cfg, "phase6_live_submission_enabled", False)),
            "environment_interlock_visible": False,
            "credentials_visible": False,
            "allowed_symbols": list(getattr(self.cfg, "phase6_allowed_symbols", []) or []),
            "max_notional_usd": float(getattr(self.cfg, "phase6_max_notional_usd", 5.0) or 5.0),
            "max_entry_orders_per_approval": int(getattr(self.cfg, "phase6_max_entry_orders_per_approval", 1) or 1),
            "leverage": 1,
            "state": {"state": "UNAVAILABLE", "reason": "data_store_unavailable"},
            "approvals": [], "runs": [], "orders": [], "positions": [],
            "incidents": [], "reconciliations": [],
            "scorecard": {"completed_round_trips": 0, "live_orders_submitted": 0,
                          "unknown_orders": 0, "open_incidents": 0},
            "readiness": {"ready_for_phase7_review": False,
                          "execution_scale_authorized": False,
                          "human_review_required": True,
                          "reasons": ["data_store_unavailable"]},
        }
        if not ds:
            return base
        try:
            from strategies.volatility_breakout.canary_store import CanaryStore
            store = CanaryStore(ds)
            base.update({
                "state": store.get_state(),
                "approvals": store.approvals(limit=min(20, int(limit or 100))),
                "runs": store.runs(limit=min(50, int(limit or 100))),
                "orders": store.get_orders(limit=int(limit or 100)),
                "positions": store.get_positions(limit=int(limit or 100)),
                "incidents": store.open_incidents()[:int(limit or 100)],
                "reconciliations": store.reconciliations(limit=min(50, int(limit or 100))),
                "scorecard": store.scorecard(),
                "readiness": store.readiness(
                    min_round_trips=int(getattr(self.cfg, "phase6_min_phase7_round_trips", 50) or 50)
                ),
            })
        except Exception as exc:
            logging.exception("Phase-6 canary snapshot failed")
            base["state"] = {"state": "UNAVAILABLE", "reason": type(exc).__name__}
            base["readiness"]["reasons"] = ["canary_projection_error"]
        return base

    def growth_snapshot(self, limit: int = 50) -> Dict[str, Any]:
        """Read-only Phase-7 controlled-growth projection.

        The ordinary coordinator cannot propose, approve, activate, demote or
        execute a growth stage. It displays persisted evidence only.
        """
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        if not ds:
            return {
                "phase": 7, "mode": "controlled_growth_governor",
                "state": {"state": "UNAVAILABLE", "reason": "data_store_unavailable", "current_stage": 0},
                "current_stage": {"stage_id": 0, "name": "CANARY", "max_notional_usd": 5.0, "allowed_symbols": ["ETH/USD"]},
                "readiness": {"ready_for_next_stage_proposal": False, "reasons": ["data_store_unavailable"]},
                "proposals": [], "approvals": [], "windows": [], "incidents": [],
                "automatic_promotion": False, "automatic_demotion": True,
                "operator_process_only": True, "desktop_stage_activation": False,
                "execution_scale_authorized": False,
            }
        try:
            from strategies.volatility_breakout.canary_store import CanaryStore
            from strategies.volatility_breakout.growth_store import GrowthStore
            from strategies.volatility_breakout.growth_lab import growth_snapshot
            return growth_snapshot(CanaryStore(ds), GrowthStore(ds), self.cfg, limit=int(limit or 50))
        except Exception as exc:
            logging.exception("Phase-7 growth snapshot failed")
            return {
                "phase": 7, "mode": "controlled_growth_governor",
                "state": {"state": "UNAVAILABLE", "reason": type(exc).__name__, "current_stage": 0},
                "readiness": {"ready_for_next_stage_proposal": False, "reasons": ["growth_projection_error"]},
                "automatic_promotion": False, "operator_process_only": True,
                "desktop_stage_activation": False, "execution_scale_authorized": False,
            }

    def integration_plane_snapshot(self) -> Dict[str, Any]:
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        bridge = self.agents.get("public_bot_bridge") if hasattr(self, "agents") else None
        lifecycle = self.agents.get("hummingbot_lifecycle") if hasattr(self, "agents") else None
        backtests = self.agents.get("public_bot_backtests") if hasattr(self, "agents") else None
        advisors = self.agents.get("market_making_advisors") if hasattr(self, "agents") else None
        research_architecture = self.agents.get("research_architecture") if hasattr(self, "agents") else None
        event_spine = self.agents.get("event_spine") if hasattr(self, "agents") else None
        evidence_registry = self.agents.get("evidence_registry") if hasattr(self, "agents") else None
        ml_lab = self.agents.get("ml_research_lab") if hasattr(self, "agents") else None
        execution_parity = self.agents.get("execution_parity") if hasattr(self, "agents") else None
        signal_marketplace = self.agents.get("signal_marketplace") if hasattr(self, "agents") else None
        phoenix_authority = self.agents.get("phoenix_authority") if hasattr(self, "agents") else None
        public_bots = {}
        if bridge and hasattr(bridge, "status"):
            public_bots = bridge.status()
            if hasattr(bridge, "sidecar_commands"):
                public_bots["sidecar_commands"] = bridge.sidecar_commands()
        pair_protections = {}
        promotions = {}
        paper_positions = {}
        if ds:
            try:
                pair_protections = ds.get_pair_protections() if hasattr(ds, "get_pair_protections") else {}
            except Exception:
                pair_protections = {}
            try:
                promotions = ds.get_promotion_records() if hasattr(ds, "get_promotion_records") else {}
            except Exception:
                promotions = {}
            try:
                paper_positions = ds.get_paper_position() if hasattr(ds, "get_paper_position") else {}
            except Exception:
                paper_positions = {}
        default_executor = getattr(self.cfg, "hummingbot_v2_default_executor", "position") or "position"
        return {
            "ts": time.time(),
            "integration_status": {
                "hummingbot_v2_adapter": "plan_and_lifecycle",
                "hummingbot_live_sidecar": "enabled" if bool(getattr(self.cfg, "hummingbot_sidecar_live_enabled", False)) else "persisted_plan_only",
                "worker_performance": "sqlite_persisted_feedback",
                "pair_protections": "swarmguard_enforced",
                "public_bot_backtesting": "export_ingest_connected",
                "market_making_advisors": "watch_only_quote_quality",
            },
            "public_bots": public_bots,
            "executors": self.executor_statuses(),
            "hummingbot_lifecycle": lifecycle.status() if lifecycle and hasattr(lifecycle, "status") else {},
            "public_bot_backtests": backtests.status() if backtests and hasattr(backtests, "status") else {},
            "market_making_advisors": advisors.status() if advisors and hasattr(advisors, "status") else {},
            "research_architecture": research_architecture.snapshot() if research_architecture and hasattr(research_architecture, "snapshot") else {},
            "config_spine": self.agents.get("config_agent").status() if self.agents.get("config_agent") and hasattr(self.agents.get("config_agent"), "status") else {},
            "event_spine": event_spine.status() if event_spine and hasattr(event_spine, "status") else {},
            "evidence_registry": evidence_registry.status() if evidence_registry and hasattr(evidence_registry, "status") else {},
            "evidence_records": ds.get_evidence_records(limit=10) if ds and hasattr(ds, "get_evidence_records") else {},
            "ml_research_lab": ml_lab.status() if ml_lab and hasattr(ml_lab, "status") else {},
            "ml_model_candidates": ds.get_ml_model_candidates(limit=10) if ds and hasattr(ds, "get_ml_model_candidates") else {},
            "execution_parity": execution_parity.status() if execution_parity and hasattr(execution_parity, "status") else {},
            "execution_parity_diagnostics": ds.get_execution_parity_diagnostics(limit=10) if ds and hasattr(ds, "get_execution_parity_diagnostics") else {},
            "signal_marketplace": signal_marketplace.status() if signal_marketplace and hasattr(signal_marketplace, "status") else {},
            "signal_marketplace_rounds": ds.get_signal_marketplace_rounds(limit=10) if ds and hasattr(ds, "get_signal_marketplace_rounds") else {},
            "phoenix_authority": phoenix_authority.snapshot() if phoenix_authority and hasattr(phoenix_authority, "snapshot") else {},
            "quote_quality_advice": self.quote_quality_advice(),
            "observation_swarm": self.observation_snapshot(limit=10),
            "hypothesis_swarm": self.hypothesis_snapshot(limit=25),
            "execution_lab": self.execution_lab_snapshot(limit=25),
            "shadow_flight": self.shadow_flight_snapshot(limit=25),
            "tiny_live_canary": self.canary_snapshot(limit=25),
            "workers": self.worker_plane_snapshot(),
            "pair_protections": pair_protections,
            "promotions": promotions,
            "paper_positions": paper_positions,
            "controls": self.integration_control_values(),
            "sample_hummingbot_plan": self.hummingbot_v2_plan(default_executor, {
                "symbol": getattr(self.cfg, "symbol", "ETH/USDT"),
                "action": "BUY",
                "price": 0.0,
                "notional_usd": getattr(self.cfg, "quote_order_size", 0.0),
            }),
        }

    def _executor_for_symbol(self, symbol: str):
        if bool(getattr(self.cfg, "dry_run", True)):
            return (self._executor_registry or {}).get("paper")
        base = str(symbol or "").split("/")[0].upper()
        if base in ("MAGIC", "BEAM"):
            return None
        return (self._executor_registry or {}).get("base")

    def _pair_protection_for_row(self, row: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
        now = float(now or time.time())
        symbol = row.get("symbol")
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        paper_trades = []
        market_history = []
        paper_stats = {}
        if symbol and ds:
            try:
                paper_trades = ds.get_paper_trades(symbol, days=1) if hasattr(ds, "get_paper_trades") else []
            except Exception:
                paper_trades = []
            try:
                market_history = ds.market_bee_history(symbol, days=1) if hasattr(ds, "market_bee_history") else []
            except Exception:
                market_history = []
            try:
                paper_stats = ds.get_paper_stats(symbol, days=int(getattr(self.cfg, "paper_promotion_window_days", 30) or 30)) if hasattr(ds, "get_paper_stats") else {}
            except Exception:
                paper_stats = {}
        payload = self._pair_protection_evaluator.evaluate(
            row,
            now=now,
            paper_trades=paper_trades,
            market_history=market_history,
            paper_stats=paper_stats,
        )
        try:
            advisors = self.agents.get("market_making_advisors") if hasattr(self, "agents") else None
            if advisors and hasattr(advisors, "advise"):
                payload["quote_advice"] = advisors.advise(row)
        except Exception:
            pass
        try:
            if ds and symbol and hasattr(ds, "upsert_pair_protection"):
                ds.upsert_pair_protection(symbol, payload)
        except Exception:
            pass
        return payload

    def run_replay_backtest(self, symbol: Optional[str] = None, days: int = 30) -> Dict[str, Any]:
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        if not ds or not hasattr(ds, "market_bee_history"):
            return {"ok": False, "error": "data_store_unavailable"}
        rows = ds.market_bee_history(symbol or "", days=int(days or 30))
        if not rows:
            return {"ok": False, "error": "no_market_bee_history", "symbol": symbol, "days": days}
        grouped: Dict[str, list] = {}
        for rec in rows:
            sym = rec.get("symbol")
            if not sym:
                continue
            try:
                import json
                payload = json.loads(rec.get("payload") or "{}")
            except Exception:
                payload = {}
            if not payload:
                payload = {
                    "symbol": sym,
                    "allowed": bool(rec.get("allowed")),
                    "reason": rec.get("reason"),
                    "score": rec.get("score"),
                    "pool": {"price_usd": rec.get("price_usd")},
                    "quality": {
                        "liquidity_usd": rec.get("liquidity_usd"),
                        "volume_24h_usd": rec.get("volume_24h_usd"),
                        "roundtrip_ratio": rec.get("roundtrip_ratio"),
                        "spread_pct": rec.get("spread_pct"),
                        "bid": rec.get("bid"),
                        "ask": rec.get("ask"),
                        "top_of_book_depth_usd": rec.get("top_of_book_depth_usd"),
                    },
                }
            payload["_ts"] = float(rec.get("ts") or time.time())
            grouped.setdefault(sym, []).append(payload)

        results = []
        for sym, history in grouped.items():
            result = self._simulate_replay_symbol(sym, history, days=int(days or 30))
            evidence = self._record_replay_evidence(result)
            if evidence:
                result["evidence"] = evidence
            parity = self._record_execution_parity(result, evidence=evidence)
            if parity:
                result["execution_parity"] = parity
            results.append(result)
            try:
                if hasattr(ds, "store_replay_result"):
                    ds.store_replay_result(result)
            except Exception:
                pass
        summary = {
            "ok": True,
            "days": int(days or 30),
            "symbols": len(results),
            "results": sorted(results, key=lambda r: r.get("net_margin_pct", 0.0), reverse=True),
            "ts": int(time.time() * 1000),
        }
        try:
            self.share_data("buzz.backtest.replay", {
                "buzz": {"type": "buzz.backtest.replay", "source": "BACKTEST", "ts": summary["ts"]},
                "payload": summary,
            })
        except Exception:
            pass
        return summary

    def _record_replay_evidence(self, result: Dict[str, Any]) -> Dict[str, Any]:
        registry = self.agents.get("evidence_registry") if hasattr(self, "agents") else None
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        if not registry or not hasattr(registry, "from_replay"):
            return {}
        try:
            record = registry.from_replay(result or {})
            if ds and hasattr(ds, "upsert_evidence_record"):
                ds.upsert_evidence_record(record)
            self.share_data("buzz.evidence.recorded", {
                "buzz": {"type": "buzz.evidence.recorded", "source": "EVIDENCE_REGISTRY", "ts": int(time.time() * 1000)},
                "payload": {
                    "evidence_id": record.get("evidence_id"),
                    "source": record.get("source"),
                    "engine": record.get("engine"),
                    "run_id": record.get("run_id"),
                    "symbol": record.get("symbol"),
                    "verdict": record.get("verdict"),
                    "promotion_stage": record.get("promotion_stage"),
                    "gates": record.get("gates"),
                    "metrics": record.get("metrics"),
                },
            })
            return record
        except Exception:
            logging.exception("Failed to record replay evidence")
            return {}

    def _record_execution_parity(self, result: Dict[str, Any], evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        parity = self.agents.get("execution_parity") if hasattr(self, "agents") else None
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        if not parity or not hasattr(parity, "from_replay"):
            return {}
        try:
            result = dict(result or {})
            observations = {}
            if ds and hasattr(ds, "get_execution_observations"):
                observations = ds.get_execution_observations(symbol=result.get("symbol"), limit=500) or {}
            if ds and hasattr(ds, "get_orderbook_snapshots") and result.get("symbol"):
                latest_books = ds.get_orderbook_snapshots(symbol=result.get("symbol"), limit=1) or []
                if latest_books:
                    book = latest_books[0] or {}
                    for key in ("spread_pct", "top_of_book_depth_usd", "bid", "ask", "mid_price"):
                        if result.get(key) is None and book.get(key) is not None:
                            result[key] = book.get(key)
                    notional = float(getattr(self.cfg, "quote_order_size", 0.0) or 0.0)
                    depth = result.get("top_of_book_depth_usd")
                    if result.get("order_size_pct_of_depth") is None and notional > 0 and depth:
                        result["order_size_pct_of_depth"] = notional / max(1e-9, float(depth))
            diagnostic = parity.from_replay(result, evidence=evidence or {}, execution_observations=observations)
            if ds and hasattr(ds, "upsert_execution_parity_diagnostic"):
                ds.upsert_execution_parity_diagnostic(diagnostic)
            self.share_data("buzz.execution.parity", {
                "buzz": {"type": "buzz.execution.parity", "source": "EXECUTION_PARITY", "ts": int(time.time() * 1000)},
                "payload": {
                    "parity_id": diagnostic.get("parity_id"),
                    "source": diagnostic.get("source"),
                    "symbol": diagnostic.get("symbol"),
                    "run_id": diagnostic.get("run_id"),
                    "evidence_id": diagnostic.get("evidence_id"),
                    "verdict": diagnostic.get("verdict"),
                    "gates": diagnostic.get("gates"),
                    "metrics": diagnostic.get("metrics"),
                },
            })
            return diagnostic
        except Exception:
            logging.exception("Failed to record execution parity diagnostic")
            return {}

    def _record_signal_marketplace_round(self, proposals: list, symbol: Optional[str] = None, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        marketplace = self.agents.get("signal_marketplace") if hasattr(self, "agents") else None
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        if not proposals or not marketplace or not hasattr(marketplace, "score_round"):
            return {}
        try:
            round_record = marketplace.score_round(
                proposals,
                perf_by_worker=self._perf_by_worker(),
                symbol=symbol or getattr(self.cfg, "symbol", None),
                context=context or {},
            )
            if ds and hasattr(ds, "upsert_signal_marketplace_round"):
                ds.upsert_signal_marketplace_round(round_record)
            self.share_data("buzz.signal.marketplace", {
                "buzz": {"type": "buzz.signal.marketplace", "source": "SIGNAL_MARKETPLACE", "ts": int(time.time() * 1000)},
                "payload": {
                    "round_id": round_record.get("round_id"),
                    "symbol": round_record.get("symbol"),
                    "verdict": round_record.get("verdict"),
                    "summary": round_record.get("summary"),
                    "gates": round_record.get("gates"),
                },
            })
            return round_record
        except Exception:
            logging.exception("Failed to record signal marketplace round")
            return {}

    def _latest_symbol_evidence(self, symbol: str) -> Dict[str, Any]:
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        if not symbol or not ds or not hasattr(ds, "get_evidence_records"):
            return {}
        try:
            records = ds.get_evidence_records(symbol=symbol, limit=1) or {}
            if not records:
                return {}
            return next(iter(records.values())) or {}
        except Exception:
            return {}

    def _simulate_replay_symbol(self, symbol: str, rows: list, days: int = 30) -> Dict[str, Any]:
        rows = sorted(rows, key=lambda r: float(r.get("_ts") or 0.0))
        hard_stop = float(getattr(self.cfg, "exit_hard_stop_pct", 0.025) or 0.025)
        take_profit = float(getattr(self.cfg, "exit_take_profit_pct", 0.04) or 0.04)
        trail = float(getattr(self.cfg, "exit_trailing_stop_pct", 0.025) or 0.025)
        time_stop = int(getattr(self.cfg, "exit_time_stop_sec", 21600) or 21600)
        max_route_loss = float(getattr(self.cfg, "pair_max_route_loss_spike_pct", 0.04) or 0.04)
        fee_pct = float(getattr(self.cfg, "fee_buffer_pct", 0.0015) or 0.0015)
        roundtrip_fee_pct = max(0.0, fee_pct * 2.0)
        position = None
        trades = []
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        max_observed_route_loss = 0.0
        max_observed_spread = 0.0
        max_order_size_pct_of_depth = 0.0
        max_top_depth_usd = 0.0
        exposure_sec = 0.0
        first_ts = float(rows[0].get("_ts") or time.time()) if rows else time.time()
        last_ts = float(rows[-1].get("_ts") or first_ts) if rows else first_ts
        midpoint_ts = first_ts + ((last_ts - first_ts) / 2.0)
        for row in rows:
            ts = float(row.get("_ts") or time.time())
            pool = row.get("pool") or {}
            q = row.get("quality") or {}
            price = float(pool.get("price_usd") or 0.0)
            if price <= 0:
                continue
            rr = q.get("roundtrip_ratio")
            route_loss = 1.0 - float(rr) if rr is not None else 0.0
            route_loss = max(0.0, route_loss)
            max_observed_route_loss = max(max_observed_route_loss, route_loss)
            spread = self._row_spread_pct(row)
            if spread is not None:
                max_observed_spread = max(max_observed_spread, max(0.0, float(spread)))
            top_depth = self._row_top_depth_usd(row, price)
            if top_depth is not None:
                max_top_depth_usd = max(max_top_depth_usd, max(0.0, float(top_depth)))
                notional = float(getattr(self.cfg, "quote_order_size", 0.0) or 0.0)
                if notional > 0:
                    max_order_size_pct_of_depth = max(max_order_size_pct_of_depth, notional / max(1e-9, float(top_depth)))
            readiness = row.get("readiness") or ("READY" if row.get("allowed") else "BLOCKED")
            if not position:
                if row.get("allowed") and readiness in ("READY", "WATCH"):
                    prot = self._pair_protection_for_row(row, now=ts)
                    if prot.get("allowed"):
                        position = {"entry": price, "highest": price, "opened": ts}
                continue
            position["highest"] = max(float(position.get("highest") or price), price)
            pnl = (price - float(position["entry"])) / max(1e-9, float(position["entry"]))
            dd_high = (float(position["highest"]) - price) / max(1e-9, float(position["highest"]))
            held = ts - float(position["opened"])
            reason = None
            if pnl <= -hard_stop:
                reason = "HARD_STOP"
            elif pnl >= take_profit and dd_high >= trail:
                reason = "TRAILING_TAKE_PROFIT"
            elif held >= time_stop and pnl <= 0:
                reason = "TIME_STOP"
            elif readiness == "BLOCKED":
                reason = "QUALITY_COLLAPSE"
            elif route_loss >= max_route_loss:
                reason = "ROUTE_LOSS_SPIKE"
            if reason:
                held = max(0.0, ts - float(position["opened"]))
                exposure_sec += held
                net = pnl - route_loss - roundtrip_fee_pct
                clean = reason in ("TRAILING_TAKE_PROFIT", "TIME_STOP") and net >= 0
                trades.append({
                    "ts": ts,
                    "net_margin_pct": net,
                    "reason": reason,
                    "clean_exit": clean,
                    "route_loss_pct": route_loss,
                    "fee_pct": roundtrip_fee_pct,
                    "split": "test" if ts >= midpoint_ts else "train",
                })
                equity += net
                peak = max(peak, equity)
                max_dd = min(max_dd, equity - peak)
                position = None
        wins = len([t for t in trades if float(t.get("net_margin_pct") or 0.0) > 0])
        losses = len(trades) - wins
        clean_exits = len([t for t in trades if t.get("clean_exit")])
        failed_exits = len([t for t in trades if not t.get("clean_exit")])
        train_trades = [t for t in trades if t.get("split") == "train"]
        test_trades = [t for t in trades if t.get("split") == "test"]
        train_net = sum(float(t.get("net_margin_pct") or 0.0) for t in train_trades)
        test_net = sum(float(t.get("net_margin_pct") or 0.0) for t in test_trades)
        walk_forward_passed = bool(train_trades and test_trades and train_net > 0.0 and test_net > 0.0)
        span = max(1.0, last_ts - first_ts)
        return {
            "ok": True,
            "symbol": symbol,
            "run_id": f"hivenance-replay-{symbol}-{int(time.time())}",
            "strategy": "market_bee_replay",
            "days": days,
            "trades": len(trades),
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / len(trades)) if trades else 0.0,
            "net_margin_pct": equity,
            "net_profit_pct": equity,
            "max_drawdown_pct": abs(max_dd),
            "fee_pct": roundtrip_fee_pct,
            "slippage_pct": max_observed_route_loss,
            "spread_pct": max_observed_spread if max_observed_spread > 0.0 else None,
            "top_of_book_depth_usd": max_top_depth_usd if max_top_depth_usd > 0.0 else None,
            "order_size_pct_of_depth": max_order_size_pct_of_depth if max_order_size_pct_of_depth > 0.0 else None,
            "exposure_pct": min(1.0, exposure_sec / span),
            "walk_forward": walk_forward_passed,
            "walk_forward_train_trades": len(train_trades),
            "walk_forward_test_trades": len(test_trades),
            "walk_forward_train_net_pct": train_net,
            "walk_forward_test_net_pct": test_net,
            "clean_exits": clean_exits,
            "failed_exits": failed_exits,
            "open_position": bool(position),
            "ts": time.time(),
        }

    def _row_spread_pct(self, row: Dict[str, Any]) -> Optional[float]:
        q = row.get("quality") or {}
        for key in ("spread_pct", "bid_ask_spread_pct"):
            try:
                if q.get(key) is not None:
                    return float(q.get(key))
                if row.get(key) is not None:
                    return float(row.get(key))
            except Exception:
                pass
        try:
            bid = q.get("bid") or row.get("bid")
            ask = q.get("ask") or row.get("ask")
            if bid and ask and float(bid) > 0:
                return (float(ask) - float(bid)) / float(bid)
        except Exception:
            pass
        return None

    def _row_top_depth_usd(self, row: Dict[str, Any], price: float) -> Optional[float]:
        q = row.get("quality") or {}
        for key in ("top_of_book_depth_usd", "depth_usd"):
            try:
                if q.get(key) is not None:
                    return float(q.get(key))
                if row.get(key) is not None:
                    return float(row.get(key))
            except Exception:
                pass
        orderbook = row.get("orderbook") or q.get("orderbook") or {}
        try:
            bids = orderbook.get("bids") or []
            asks = orderbook.get("asks") or []
            bid_vol = sum(float(b[1]) for b in bids[:3])
            ask_vol = sum(float(a[1]) for a in asks[:3])
            depth = (bid_vol + ask_vol) * max(0.0, float(price or 0.0))
            return depth if depth > 0 else None
        except Exception:
            return None

    def _update_paper_promotion_and_positions(self, snapshot: Dict[str, Any]) -> None:
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        if not ds:
            return
        rows = (snapshot or {}).get("all") or []
        if not rows:
            return
        now = time.time()
        # Paper observations are rate-limited separately from market snapshots.
        paper_interval = int(getattr(self.cfg, "paper_promotion_eval_interval_sec", 3600) or 3600)
        do_paper = (now - float(getattr(self, "_last_paper_eval_ts", 0.0) or 0.0)) >= paper_interval
        if do_paper:
            self._last_paper_eval_ts = now
        memory_changed = False
        memory = self._load_symbol_memory()
        for row in rows:
            symbol = row.get("symbol")
            if not symbol:
                continue
            base = symbol.split("/")[0].upper()
            q = row.get("quality") or {}
            pool = row.get("pool") or {}
            net_margin = q.get("net_margin_pct")
            price = pool.get("price_usd")
            protection = {}
            try:
                protection = self._pair_protection_for_row(row, now=now)
            except Exception:
                protection = {"allowed": True, "reason": "PROTECTION_ERROR_NON_BLOCKING"}
            if do_paper and price:
                try:
                    if protection.get("allowed", True):
                        self._simulate_paper_position(row, now)
                except Exception:
                    pass
                try:
                    stats = ds.get_paper_stats(symbol, days=int(getattr(self.cfg, "paper_promotion_window_days", 30) or 30))
                    current = memory.setdefault(base, {})
                    current.setdefault("stage", "paper")
                    current["paper_trades"] = int(stats.get("trades") or 0)
                    current["paper_win_rate"] = round(float(stats.get("win_rate") or 0.0), 4)
                    current["paper_net_margin_sum"] = round(float(stats.get("net_margin_sum") or 0.0), 6)
                    current["max_drawdown_pct"] = round(float(stats.get("max_drawdown_pct") or 0.0) * 100.0, 4)
                    min_trades = int(getattr(self.cfg, "promotion_min_paper_trades", 25) or 25)
                    min_win = float(getattr(self.cfg, "promotion_min_win_rate", 0.52) or 0.52)
                    max_dd = float(getattr(self.cfg, "promotion_max_drawdown_pct", 5.0) or 5.0)
                    paper_trades = ds.get_paper_trades(symbol, days=int(getattr(self.cfg, "paper_promotion_window_days", 30) or 30)) if hasattr(ds, "get_paper_trades") else []
                    clean_exits = len([t for t in paper_trades if float(t.get("net_margin_pct") or 0.0) > 0 and "QUALITY_COLLAPSE" not in str(t.get("reason") or "")])
                    failed_exits = len([t for t in paper_trades if float(t.get("net_margin_pct") or 0.0) <= 0 or "QUALITY_COLLAPSE" in str(t.get("reason") or "")])
                    latest_evidence = self._latest_symbol_evidence(symbol)
                    evidence_verdict = latest_evidence.get("verdict")
                    promotion_reasons = []
                    if current["paper_trades"] < min_trades:
                        promotion_reasons.append("NEEDS_MORE_PAPER_TRADES")
                    if current["paper_win_rate"] < min_win:
                        promotion_reasons.append("WIN_RATE_TOO_LOW")
                    if current["paper_net_margin_sum"] <= 0:
                        promotion_reasons.append("NET_MARGIN_NOT_POSITIVE")
                    if current["max_drawdown_pct"] > max_dd:
                        promotion_reasons.append("DRAWDOWN_TOO_HIGH")
                    if failed_exits > clean_exits:
                        promotion_reasons.append("EXITS_NOT_CLEAN")
                    if evidence_verdict != "external_research_passed":
                        promotion_reasons.append(f"EVIDENCE_{str(evidence_verdict or 'MISSING').upper()}")
                    if protection and not protection.get("allowed", True):
                        promotion_reasons.append(f"PAIR_PROTECTED:{protection.get('reason')}")
                    legacy_candidate_ready = (
                        current.get("stage") == "paper"
                        and current["paper_trades"] >= min_trades
                        and current["paper_win_rate"] >= min_win
                        and current["paper_net_margin_sum"] > 0
                        and current["max_drawdown_pct"] <= max_dd
                        and clean_exits >= failed_exits
                        and evidence_verdict == "external_research_passed"
                        and protection.get("allowed", True)
                    )
                    current["phoenix_candidate_ready"] = bool(legacy_candidate_ready)
                    current["next_required_phase"] = 2
                    current["last_paper_eval"] = int(now * 1000)
                    try:
                        if hasattr(ds, "upsert_promotion_record"):
                            ds.upsert_promotion_record(symbol, {
                                "symbol": symbol,
                                "stage": "paper",
                                "eligible": False,
                                "reason": "PHOENIX_PHASE2_REQUIRED" if current.get("phoenix_candidate_ready") else ",".join(promotion_reasons or ["COLLECTING_EVIDENCE"]),
                                "paper_trades": current["paper_trades"],
                                "win_rate": current["paper_win_rate"],
                                "net_margin_sum": current["paper_net_margin_sum"],
                                "max_drawdown_pct": current["max_drawdown_pct"],
                                "clean_exits": clean_exits,
                                "failed_exits": failed_exits,
                                "updated_ts": now,
                                "protection": protection,
                                "evidence_id": latest_evidence.get("evidence_id"),
                                "evidence_verdict": evidence_verdict,
                                "phoenix_candidate_ready": bool(current.get("phoenix_candidate_ready")),
                                "execution_authority": "none",
                                "promotion_authority": "none",
                                "next_required_phase": 2,
                            })
                    except Exception:
                        pass
                    memory_changed = True
                except Exception:
                    pass
            try:
                self._update_position_memory_for_row(row)
            except Exception:
                pass
        if memory_changed:
            self._write_symbol_memory(memory)

    def run_dry_run_probe(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Run a read-only/paper probe through Market Bee and paper memory."""
        if not bool(getattr(self.cfg, "dry_run", True)):
            return {"ok": False, "error": "dry_run_required"}
        if not self._dex_margin_oracle:
            return {"ok": False, "error": "dex_margin_oracle_unavailable"}
        amount_usd = min(
            float(getattr(self.cfg, "dex_probe_amount_usd", 1.0) or 1.0),
            float(getattr(self.cfg, "quote_order_size", 1.0) or 1.0),
            float(getattr(self.cfg, "max_trade_usd", 1.0) or 1.0),
        )
        amount_usd = max(0.25, amount_usd)
        top_n = max(4, int(getattr(self.cfg, "market_bee_top_n", 4) or 4))
        snapshot = self._dex_margin_oracle.market_bee_snapshot(top_n=top_n, amount_usd=amount_usd)
        rows = snapshot.get("all") or snapshot.get("top") or []
        wanted = str(symbol or "").upper().strip()
        selected = None
        if wanted:
            wanted_base = wanted.split("/")[0]
            for row in rows:
                base = str(row.get("symbol") or "").upper().split("/")[0]
                if base == wanted_base:
                    selected = row
                    break
        if not selected:
            for row in rows:
                if row.get("allowed") and row.get("readiness") in ("READY", "WATCH"):
                    selected = row
                    break
        if not selected:
            selected = rows[0] if rows else None
        if not selected:
            return {"ok": False, "error": "no_market_bee_rows"}

        now = time.time()
        protection = self._pair_protection_for_row(selected, now=now)
        executor_result = {}
        try:
            if protection.get("allowed", True):
                self._simulate_paper_position(selected, now)
                executor = self._executor_for_symbol(selected.get("symbol"))
                if executor:
                    executor_result = executor.execute({
                        "symbol": selected.get("symbol"),
                        "side": "BUY",
                        "notional_usd": amount_usd,
                        "reason": "DRY_RUN_PROBE",
                    }, market_row=selected)
        except Exception:
            pass
        q = selected.get("quality") or {}
        pool = selected.get("pool") or {}
        payload = {
            "ok": bool(protection.get("allowed", True)),
            "mode": "DRY_RUN_PROBE",
            "action": "PAPER_ENTRY_OR_WATCH",
            "symbol": selected.get("symbol"),
            "notional_usd": amount_usd,
            "allowed": bool(selected.get("allowed")),
            "protection_allowed": bool(protection.get("allowed", True)),
            "protection_reason": protection.get("reason"),
            "readiness": selected.get("readiness"),
            "reason": selected.get("reason"),
            "score": selected.get("score"),
            "price_usd": pool.get("price_usd"),
            "liquidity_usd": q.get("liquidity_usd"),
            "volume_24h_usd": q.get("volume_24h_usd"),
            "roundtrip_ratio": q.get("roundtrip_ratio"),
            "roundtrip_loss_pct": (1.0 - float(q.get("roundtrip_ratio"))) if q.get("roundtrip_ratio") is not None else None,
            "executor": executor_result or {"status": "SKIPPED", "reason": protection.get("reason")},
            "dry_run": True,
            "ts": int(now * 1000),
        }
        self.share_data("buzz.dry_run.probe", {
            "buzz": {"type": "buzz.dry_run.probe", "source": "DRY_RUN", "ts": int(now * 1000)},
            "payload": payload,
        })
        return payload

    def _simulate_paper_position(self, row: Dict[str, Any], now: float) -> None:
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        if not ds or not hasattr(ds, "upsert_paper_position"):
            return
        symbol = row.get("symbol")
        pool = row.get("pool") or {}
        q = row.get("quality") or {}
        price = float(pool.get("price_usd") or 0.0)
        if not symbol or price <= 0:
            return
        readiness = row.get("readiness") or ("READY" if row.get("allowed") else "BLOCKED")
        notional = float(getattr(self.cfg, "dex_probe_amount_usd", 1.0) or 1.0)
        existing = {}
        try:
            existing = (ds.get_paper_position(symbol) or {}).get(symbol) or {}
        except Exception:
            existing = {}
        if not existing or existing.get("status") in ("CLOSED", "EXITED"):
            if readiness not in ("READY", "WATCH") or not row.get("allowed"):
                return
            qty = notional / max(1e-9, price)
            ds.upsert_paper_position(symbol, {
                "symbol": symbol,
                "qty": qty,
                "entry_price": price,
                "highest_price": price,
                "opened_ts": now,
                "updated_ts": now,
                "status": "OPEN",
                "entry_reason": row.get("reason"),
                "entry_readiness": readiness,
                "entry_quality": q,
            })
            return

        entry = float(existing.get("entry_price") or price)
        highest = max(float(existing.get("highest_price") or price), price)
        qty = float(existing.get("qty") or (notional / max(1e-9, entry)))
        opened_ts = float(existing.get("opened_ts") or now)
        pnl_pct = (price - entry) / max(1e-9, entry)
        drawdown_from_high = (highest - price) / max(1e-9, highest)
        route_loss = 1.0 - float(q.get("roundtrip_ratio") or 1.0)
        hard_stop = float(getattr(self.cfg, "exit_hard_stop_pct", 0.025) or 0.025)
        take_profit = float(getattr(self.cfg, "exit_take_profit_pct", 0.04) or 0.04)
        trail = float(getattr(self.cfg, "exit_trailing_stop_pct", 0.025) or 0.025)
        held_sec = now - opened_ts
        exit_reason = None
        if pnl_pct <= -hard_stop:
            exit_reason = "PAPER_HARD_STOP"
        elif pnl_pct >= take_profit and drawdown_from_high >= trail:
            exit_reason = "PAPER_TRAILING_TAKE_PROFIT"
        elif held_sec >= int(getattr(self.cfg, "exit_time_stop_sec", 21600) or 21600) and pnl_pct <= 0:
            exit_reason = "PAPER_TIME_STOP"
        elif readiness == "BLOCKED":
            exit_reason = "PAPER_QUALITY_COLLAPSE"
        if exit_reason:
            net_margin = pnl_pct - max(0.0, route_loss)
            ds.store_paper_trade({
                "ts": now,
                "symbol": symbol,
                "side": "EXIT",
                "qty": qty,
                "price": price,
                "notional_usd": qty * price,
                "reason": exit_reason,
                "net_margin_pct": net_margin,
                "status": "PAPER_CLOSED",
            })
            ds.upsert_paper_position(symbol, {
                "symbol": symbol,
                "qty": qty,
                "entry_price": entry,
                "highest_price": highest,
                "current_price": price,
                "opened_ts": opened_ts,
                "updated_ts": now,
                "status": "CLOSED",
                "exit_reason": exit_reason,
                "paper_pnl_pct": pnl_pct,
                "paper_net_margin_pct": net_margin,
                "route_loss_pct": route_loss,
                "exit_quality": q,
            })
            return
        ds.upsert_paper_position(symbol, {
            "symbol": symbol,
            "qty": qty,
            "entry_price": entry,
            "highest_price": highest,
            "current_price": price,
            "opened_ts": opened_ts,
            "updated_ts": now,
            "held_sec": held_sec,
            "status": "OPEN",
            "paper_pnl_pct": pnl_pct,
            "drawdown_from_high_pct": drawdown_from_high,
            "readiness": readiness,
            "quality": q,
        })

    def _load_symbol_memory(self) -> Dict[str, Any]:
        path = getattr(self.cfg, "symbol_memory_path", "data/symbol_memory.json")
        try:
            import json
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}

    def _write_symbol_memory(self, memory: Dict[str, Any]) -> None:
        path = getattr(self.cfg, "symbol_memory_path", "data/symbol_memory.json")
        try:
            import json
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(memory, f, indent=2, sort_keys=True)
        except Exception:
            pass

    def _update_position_memory_for_row(self, row: Dict[str, Any]) -> None:
        ds = self.agents.get("data_store") if hasattr(self, "agents") else None
        if not ds or not row:
            return
        symbol = row.get("symbol")
        base = (symbol or "").split("/")[0].upper()
        if not symbol or not base:
            return
        balances = self._last_wallet_balances or {}
        qty = 0.0
        if base == "ETH":
            qty = float(balances.get("eth") or 0.0)
        elif str(balances.get("token_symbol") or "").upper() == base:
            qty = float(balances.get("token") or 0.0)
        if qty <= 0:
            return
        pool = row.get("pool") or {}
        price = float(pool.get("price_usd") or 0.0)
        if price <= 0:
            return
        existing = (ds.get_position_memory(symbol) or {}).get(symbol) or {}
        opened_ts = float(existing.get("opened_ts") or time.time())
        entry = float(existing.get("entry_price") or price)
        highest = max(float(existing.get("highest_price") or price), price)
        hard_stop = float(getattr(self.cfg, "exit_hard_stop_pct", 0.025) or 0.025)
        take_profit = float(getattr(self.cfg, "exit_take_profit_pct", 0.04) or 0.04)
        trail = float(getattr(self.cfg, "exit_trailing_stop_pct", 0.025) or 0.025)
        held_sec = time.time() - opened_ts
        pnl_pct = (price - entry) / max(1e-9, entry)
        drawdown_from_high = (highest - price) / max(1e-9, highest)
        exit_reason = None
        if pnl_pct <= -hard_stop:
            exit_reason = "HARD_STOP"
        elif pnl_pct >= take_profit and drawdown_from_high >= trail:
            exit_reason = "TRAILING_TAKE_PROFIT"
        elif held_sec >= int(getattr(self.cfg, "exit_time_stop_sec", 21600) or 21600) and pnl_pct <= 0:
            exit_reason = "TIME_STOP"
        payload = {
            "symbol": symbol,
            "qty": qty,
            "entry_price": entry,
            "highest_price": highest,
            "current_price": price,
            "opened_ts": opened_ts,
            "updated_ts": time.time(),
            "held_sec": held_sec,
            "unrealized_pnl_pct": pnl_pct,
            "drawdown_from_high_pct": drawdown_from_high,
            "exit_reason": exit_reason,
            "status": "EXIT_SIGNAL" if exit_reason else "OPEN",
            "sell_quote": row.get("quality") or {},
        }
        ds.upsert_position_memory(symbol, payload)
        if exit_reason:
            self.share_data("buzz.exit.manager", {
                "buzz": {"type": "buzz.exit.manager", "source": "EXIT_MANAGER", "ts": int(time.time() * 1000)},
                "payload": payload,
            })

    def _apply_capital_policy(self, symbol: str, action: str, position_size: float, latest_price: float) -> tuple:
        """Apply coarse capital buckets: reserve, core, experimental."""
        reason = None
        try:
            if not getattr(self.cfg, "capital_allocator_enabled", False):
                return position_size, reason
            if not symbol or "/" not in symbol or latest_price <= 0:
                return position_size, reason
            base = symbol.split("/")[0].upper()
            if action == "SELL":
                return position_size, reason

            core = set(str(x).upper() for x in (getattr(self.cfg, "core_assets", []) or []))
            experimental = set(str(x).upper() for x in (getattr(self.cfg, "experimental_assets", []) or []))
            reserve_pct = max(0.0, min(0.95, float(getattr(self.cfg, "capital_reserve_pct", 0.65) or 0.0)))
            core_pct = max(0.0, min(1.0, float(getattr(self.cfg, "core_allocation_pct", 0.30) or 0.0)))
            exp_pct = max(0.0, min(1.0, float(getattr(self.cfg, "experimental_allocation_pct", 0.05) or 0.0)))
            max_trade_usd = float(getattr(self.cfg, "max_trade_usd", 0.0) or 0.0)

            bucket_pct = core_pct if base in core else exp_pct if base in experimental else min(core_pct, exp_pct)
            if max_trade_usd > 0:
                bucket_cap_usd = max_trade_usd * max(0.05, bucket_pct / max(0.05, 1.0 - reserve_pct))
                cap_qty = bucket_cap_usd / latest_price
                if cap_qty < position_size:
                    position_size = cap_qty
                    reason = f"CAPITAL_ALLOCATOR({base}, cap_usd={bucket_cap_usd:.2f})"
        except Exception:
            pass
        return position_size, reason

    def _wallet_spend_allowed(self, notional_usd: float) -> tuple:
        """Enforce a local daily BUY spend cap before creating live intents."""
        try:
            if not getattr(self.cfg, "wallet_safety_enabled", True):
                return True, None
            cap = float(getattr(self.cfg, "wallet_max_daily_spend_usd", 0.0) or 0.0)
            if cap <= 0:
                return True, None
            day = time.strftime("%Y-%m-%d", time.gmtime())
            spent = float(self._wallet_daily_spend.get(day, 0.0) or 0.0)
            if spent + float(notional_usd or 0.0) > cap:
                return False, f"WALLET_DAILY_SPEND_CAP({spent + float(notional_usd or 0.0):.2f}>{cap:.2f})"
            return True, None
        except Exception:
            return True, None

    def _record_wallet_spend(self, notional_usd: float):
        try:
            day = time.strftime("%Y-%m-%d", time.gmtime())
            self._wallet_daily_spend[day] = float(self._wallet_daily_spend.get(day, 0.0) or 0.0) + float(notional_usd or 0.0)
        except Exception:
            pass

    def _switch_symbol(self, new_symbol: str):
        """Switch active symbol and reinitialize market/execution agents."""
        try:
            if not new_symbol or new_symbol == getattr(self.cfg, "symbol", ""):
                return
            self.cfg.symbol = new_symbol
            # Update market data agent
            try:
                if self._client and self.cfg.exchange.lower() == "kraken":
                    self.agents["market_data"] = KrakenMarketData(self._client, new_symbol, self.cfg.interval)
                elif self._client:
                    self.agents["market_data"] = MarketData(self._client, new_symbol, self.cfg.interval)
            except Exception:
                pass
            # Update execution agent
            try:
                if getattr(self.cfg, "onchain_enabled", False):
                    from agents.execution import DexExecutionAgent
                    self.agents["execution"] = DexExecutionAgent(self.cfg, coordinator=self)
                else:
                    if self._client and self.cfg.exchange.lower() == "kraken":
                        trader = KrakenTrader(self._client, new_symbol, self.cfg.dry_run, self.cfg.max_position_base)
                    elif self._client:
                        trader = BinanceTrader(self._client, new_symbol, self.cfg.dry_run, self.cfg.max_position_base)
                    else:
                        trader = None
                    if trader:
                        from agents.execution import ExecutionAgent
                        self.agents["execution"] = ExecutionAgent(
                            trader,
                            coordinator=self,
                            dry_run=self.cfg.dry_run,
                            min_notional=getattr(self.cfg, "min_trade_usd", 1.0),
                            spread_threshold_pct=getattr(self.cfg, "spread_guard_pct", 0.0015),
                        )
            except Exception:
                pass
            # Update wallet monitor execution agent reference
            try:
                if self.agents.get("wallet") and hasattr(self.agents["wallet"], "execution_agent"):
                    self.agents["wallet"].execution_agent = self.agents.get("execution")
            except Exception:
                pass
            logging.info(f"Switched active symbol to {new_symbol}")
        except Exception:
            pass

    # ---- multi-symbol helpers ----
    def _symbol_list(self):
        syms = [getattr(self.cfg, "symbol", "")]
        extra = getattr(self.cfg, "multi_symbols", []) or []
        for s in extra:
            if s and s not in syms:
                syms.append(s)
        return [s for s in syms if s]

    def _get_exec_for_symbol(self, symbol: str):
        if not symbol:
            return None
        if symbol in self._exec_by_symbol:
            return self._exec_by_symbol.get(symbol)
        # build new execution agent for symbol
        try:
            if getattr(self.cfg, "onchain_enabled", False):
                from agents.execution import DexExecutionAgent
                exec_agent = DexExecutionAgent(self.cfg, coordinator=self)
                # adjust symbol on the agent
                try:
                    if hasattr(exec_agent, "set_symbol"):
                        exec_agent.set_symbol(symbol)
                    else:
                        exec_agent.symbol = symbol
                        if "/" in symbol:
                            exec_agent.base_asset, exec_agent.quote_asset = symbol.split("/")
                except Exception:
                    pass
                self._exec_by_symbol[symbol] = exec_agent
                return exec_agent
            # CEX path
            trader = None
            if self._client and self.cfg.exchange.lower() == "kraken":
                from agents.execution import KrakenTrader, ExecutionAgent
                trader = KrakenTrader(self._client, symbol, self.cfg.dry_run, self.cfg.max_position_base)
                exec_agent = ExecutionAgent(
                    trader,
                    coordinator=self,
                    dry_run=self.cfg.dry_run,
                    min_notional=getattr(self.cfg, "min_trade_usd", 1.0),
                    spread_threshold_pct=getattr(self.cfg, "spread_guard_pct", 0.0015),
                )
            elif self._client:
                from agents.execution import BinanceTrader, ExecutionAgent
                trader = BinanceTrader(self._client, symbol, self.cfg.dry_run, self.cfg.max_position_base)
                exec_agent = ExecutionAgent(
                    trader,
                    coordinator=self,
                    dry_run=self.cfg.dry_run,
                    min_notional=getattr(self.cfg, "min_trade_usd", 1.0),
                    spread_threshold_pct=getattr(self.cfg, "spread_guard_pct", 0.0015),
                )
            else:
                exec_agent = None
            self._exec_by_symbol[symbol] = exec_agent
            return exec_agent
        except Exception:
            return None

    def _get_cex_exec_for_symbol(self, symbol: str):
        """Return a CEX execution agent for fallback, regardless of on-chain mode."""
        if not symbol:
            return None
        if symbol in self._cex_exec_by_symbol:
            return self._cex_exec_by_symbol.get(symbol)
        try:
            if not self._client:
                return None
            trader = None
            if self.cfg.exchange.lower() == "kraken":
                from agents.execution import KrakenTrader, ExecutionAgent
                trader = KrakenTrader(self._client, symbol, self.cfg.dry_run, self.cfg.max_position_base)
            else:
                from agents.execution import BinanceTrader, ExecutionAgent
                trader = BinanceTrader(self._client, symbol, self.cfg.dry_run, self.cfg.max_position_base)
            if trader:
                exec_agent = ExecutionAgent(
                    trader,
                    coordinator=self,
                    dry_run=self.cfg.dry_run,
                    min_notional=getattr(self.cfg, "min_trade_usd", 1.0),
                    spread_threshold_pct=getattr(self.cfg, "spread_guard_pct", 0.0015),
                )
                self._cex_exec_by_symbol[symbol] = exec_agent
                return exec_agent
        except Exception:
            return None
        return None

    def _get_cex_exec_for_symbol(self, symbol: str):
        """Build or reuse a CEX execution agent for fallback when on-chain gas is too high."""
        if not symbol:
            return None
        if symbol in self._cex_exec_by_symbol:
            return self._cex_exec_by_symbol.get(symbol)
        try:
            trader = None
            if self._client and self.cfg.exchange.lower() == "kraken":
                from agents.execution import KrakenTrader, ExecutionAgent
                trader = KrakenTrader(self._client, symbol, self.cfg.dry_run, self.cfg.max_position_base)
                exec_agent = ExecutionAgent(
                    trader,
                    coordinator=self,
                    dry_run=self.cfg.dry_run,
                    min_notional=getattr(self.cfg, "min_trade_usd", 1.0),
                    spread_threshold_pct=getattr(self.cfg, "spread_guard_pct", 0.0015),
                )
            elif self._client:
                from agents.execution import BinanceTrader, ExecutionAgent
                trader = BinanceTrader(self._client, symbol, self.cfg.dry_run, self.cfg.max_position_base)
                exec_agent = ExecutionAgent(
                    trader,
                    coordinator=self,
                    dry_run=self.cfg.dry_run,
                    min_notional=getattr(self.cfg, "min_trade_usd", 1.0),
                    spread_threshold_pct=getattr(self.cfg, "spread_guard_pct", 0.0015),
                )
            else:
                exec_agent = None
            if exec_agent:
                self._cex_exec_by_symbol[symbol] = exec_agent
            return exec_agent
        except Exception:
            return None

    def _fetch_symbol_series(self, symbol: str, limit: int = 200):
        """Fetch OHLCV series for a symbol using the exchange client."""
        try:
            client = getattr(self, "_client", None)
            if client and hasattr(client, "fetch_ohlcv"):
                ohlcv = client.fetch_ohlcv(symbol, timeframe=self.cfg.interval, limit=limit)
                if not ohlcv:
                    return [], [], None, None
                times = [int(c[0]) for c in ohlcv]
                closes = [float(c[4]) for c in ohlcv]
                volumes = [float(c[5]) for c in ohlcv]
                return times, closes, volumes, closes[-1] if closes else None
        except Exception:
            pass
        return [], [], [], None

    def _get_regime_for_symbol(self, symbol: str, exec_agent=None):
        try:
            oracle = self._regime_oracles.get(symbol)
            if not oracle:
                oracle = RegimeOracle(
                    symbol=symbol,
                    timeframes=getattr(self.cfg, "regime_timeframes", ["1m", "5m", "1h"]),
                    min_duration_sec=getattr(self.cfg, "regime_min_duration_sec", 300),
                    confirm_bars=getattr(self.cfg, "regime_confirmations", 3),
                    confidence_threshold=getattr(self.cfg, "regime_confidence_threshold", 0.15),
                )
                self._regime_oracles[symbol] = oracle
            # create a lightweight market data adapter for the symbol
            md = None
            try:
                if self._client and self.cfg.exchange.lower() == "kraken":
                    md = KrakenMarketData(self._client, symbol, self.cfg.interval)
                elif self._client:
                    md = MarketData(self._client, symbol, self.cfg.interval)
            except Exception:
                md = None
            return oracle.update(md, exec_agent)
        except Exception:
            return None

    def _select_best_symbol(self):
        """Evaluate proposals per symbol and pick the best actionable symbol."""
        symbols = self._symbol_list()
        if not symbols:
            return None
        best = None
        best_score = -1.0
        for sym in symbols:
            try:
                decision = None
                times, closes, volumes, latest_price = self._fetch_symbol_series(sym, limit=self.cfg.lookback)
                if not closes:
                    continue
                # publish market data for each symbol for UI visibility
                try:
                    self.share_data('buzz.market.data', {
                        'buzz': {'type': 'buzz.market.data', 'source': 'MARKET_DATA', 'ts': int(time.time() * 1000)},
                        'payload': {
                            'symbol': sym,
                            'price': latest_price,
                            'interval': self.cfg.interval,
                            'venue': self.cfg.exchange,
                            'ts': int(time.time() * 1000),
                        }
                    })
                except Exception:
                    pass

                # regime snapshot
                exec_agent = self._get_exec_for_symbol(sym)
                regime_snapshot = self._get_regime_for_symbol(sym, exec_agent)
                if regime_snapshot:
                    try:
                        self.share_data("buzz.regime.snapshot", {
                            "buzz": {"type": "buzz.regime.snapshot", "source": "ORACLE", "ts": int(time.time() * 1000)},
                            "payload": regime_snapshot,
                        })
                    except Exception:
                        pass

                # proposals via council
                proposals = []
                if self.agents.get("council") and self.strategy_workers:
                    proposals, _ = self.agents["council"].collect(
                        self.strategy_workers,
                        closes,
                        volumes,
                        latest_price,
                        sym,
                        regime_snapshot=regime_snapshot,
                        perf_by_worker=self._perf_by_worker(),
                    )
                    self._record_signal_marketplace_round(
                        proposals,
                        symbol=sym,
                        context={"source": "multi_symbol_council", "latest_price": latest_price},
                    )

                # governance decision
                if self.governance:
                    perf_metrics = {}
                    try:
                        if self.agents.get("logging"):
                            perf_metrics = self.agents["logging"].get_metrics() or {}
                    except Exception:
                        perf_metrics = {}
                    exec_quality = {}
                    try:
                        client = getattr(self, "_client", None)
                        if client and hasattr(client, "fetch_ticker"):
                            t = client.fetch_ticker(sym)
                            bid = t.get("bid")
                            ask = t.get("ask")
                            if bid and ask and bid > 0:
                                exec_quality["spread_pct"] = (ask - bid) / bid
                    except Exception:
                        pass
                    try:
                        exec_agent = self.agents.get("execution")
                        if exec_agent and hasattr(exec_agent, "health_snapshot"):
                            hs = exec_agent.health_snapshot() or {}
                            if "order_unconfirmed_ms" in hs:
                                exec_quality["order_unconfirmed_ms"] = hs.get("order_unconfirmed_ms")
                            if "api_failures_60s" in hs:
                                exec_quality["api_failures_60s"] = hs.get("api_failures_60s")
                            for k in (
                                "quote_output_ratio",
                                "min_output_ratio",
                                "price_impact_pct",
                                "gas_drag_pct",
                                "gas_usd",
                                "route_from_usd",
                                "route_to_usd",
                            ):
                                if k in hs:
                                    exec_quality[k] = hs.get(k)
                    except Exception:
                        pass
                    try:
                        if self._dex_margin_oracle and bool(getattr(self.cfg, "dex_margin_oracle_enabled", True)):
                            quote_usd = float(getattr(self.cfg, "quote_order_size", 1.0) or 1.0)
                            exec_quality.update(self._dex_margin_oracle.exec_quality_for_symbol(sym, amount_usd=quote_usd))
                    except Exception:
                        pass
                    portfolio = {"base_free": 0.0, "quote_free": 0.0, "latest_price": latest_price}
                    decision = self.governance.decide(regime_snapshot or {}, proposals, portfolio, exec_quality, perf_metrics, self.cfg)
                    if decision:
                        decision["symbol"] = sym
                        # emit decision for UI
                        try:
                            self.share_data("buzz.governance.decision", {
                                "buzz": {"type": "buzz.governance.decision", "source": "QUEEN", "ts": int(time.time() * 1000)},
                                "payload": decision,
                            })
                        except Exception:
                            pass
                        action = decision.get("action")
                        svs = float(decision.get("svs") or 0.0)
                        if action in ("BUY", "SELL") and svs >= best_score:
                            best_score = svs
                            best = sym
                # update per-symbol cycle snapshot
                try:
                    self._update_cycle(sym, latest_price, proposals, decision if 'decision' in locals() else None)
                except Exception:
                    pass
            except Exception:
                continue
        return best
