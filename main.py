import os
import json
import yaml
import logging
import time
from dataclasses import dataclass
from typing import Optional, List
from binance.client import Client
from agents.coordinator import SwarmCoordinator
from agents.tracing import setup_tracing
from agents.logging_analytics import setup_logging


@dataclass
class Config:
    binance_api_key: str
    binance_api_secret: str
    binance_testnet: bool
    exchange: str
    kraken_api_key: str
    kraken_api_secret: str

    dry_run: bool

    symbol: str
    interval: str
    lookback: int

    strategy_type: str
    sma_fast: int
    sma_slow: int
    rsi_window: int
    rsi_oversold: int
    rsi_overbought: int
    macd_fast: int
    macd_slow: int
    macd_signal: int

    quote_order_size: float
    max_position_base: float
    risk_pct: float
    ratio_gate_enabled: bool
    target_base_ratio: float
    target_ratio_band: float

    poll_seconds: int
    wallet_poll_seconds: int

    max_notional: float
    spread_guard_pct: float
    throttle_multiplier: float
    strategy_cooldown: int
    throttle_bypass_notional: float
    min_trade_usd: float
    max_trade_usd: float

    onchain_enabled: bool
    dex_provider: str
    onchain_chain_id: int
    onchain_slippage_bps: int
    onchain_allowed_pairs: List[str]
    onchain_force_base: bool
    onchain_force_chain_id: Optional[int]
    onchain_prefer_l2: bool
    onchain_l2_chain_id: int
    onchain_max_gas_gwei: float
    onchain_max_gas_eth: float
    onchain_max_gas_usd: float
    onchain_max_fee_eth: float
    onchain_fallback_to_cex: bool
    swarmguard_enabled: bool
    liquidity_k: float
    liquidity_m: float
    expected_move_min_pct: float
    fee_buffer_pct: float
    onchain_token_addresses: Optional[dict]
    swarmguard_max_trades_per_hour: int
    swarmguard_min_trade_interval_sec: int
    swarmguard_consensus_min: int
    swarmguard_consensus_penalty: float
    swarmguard_weight_decay: float
    swarmguard_weight_floor: float
    swarmguard_small_trade_usd: float
    swarmguard_small_trade_bypass: bool
    swarmguard_rules_path: Optional[str]
    swarmguard_risk_rules_path: Optional[str]
    swarmguard_risk_register_path: Optional[str]
    swarmguard_risk_map_path: Optional[str]
    multi_symbol_enabled: bool
    multi_symbols: List[str]
    coin_selection_enabled: bool
    coin_selection_interval_sec: int
    coin_selection_min_vol_usd: float
    coin_selection_spread_max: float
    coin_selection_top_n: int
    coin_selection_lookback: int
    coin_selection_max_symbols: int
    coin_selection_quote_assets: List[str]
    coin_selection_include: List[str]
    coin_selection_exclude: List[str]
    coin_selection_auto_switch: bool

    governance_authoritative: bool
    regime_timeframes: List[str]
    regime_min_duration_sec: int
    regime_confirmations: int
    regime_confidence_threshold: float
    svs_min_threshold: float
    nurse_review_interval_sec: int

    # Learning engine controls
    approval_threshold_usd: float
    auto_trade_enabled: bool
    risk_tolerance: float
    max_position_pct: float

    kill_switch_enabled: bool
    daily_loss_throttle_pct: float
    daily_loss_halt_pct: float
    rejects_threshold_5m: int
    slippage_threshold: float
    market_stale_sec: float
    wallet_stale_sec: float
    throttle_clear_sec: int
    killswitch_equity_floor_usd: float
    max_drawdown_pct: float
    daily_loss_limit: float
    max_consecutive_losses: int
    kill_switch_grace_sec: int
    kill_switch_enforce_stale: bool
    adaptive_min_liquidity_usd: float
    adaptive_max_spread_pct: float
    adaptive_min_volatility_pct: float
    adaptive_max_volatility_pct: float

    ui_enabled: bool
    ui_host: str
    ui_port: int

    network_enabled: bool
    redis_host: str
    redis_port: int
    redis_db: int
    redis_password: Optional[str]

    data_store_enabled: bool
    db_path: str

    performance_enabled: bool

    security_enabled: bool
    encryption_key_file: str
    security_auto_pause: bool
    security_always_armed: bool

    walletconnect_project_id: Optional[str]
    oneinch_api_key: Optional[str]
    buzz_base_url: Optional[str]
    buzz_shared_secret: Optional[str]
    buzz_account: Optional[str]

    queen_telegram_confirm_enabled: bool
    queen_telegram_confirm_timeout_sec: int
    queen_telegram_fail_open: bool
    telegram_bot_token: Optional[str]
    telegram_chat_id: Optional[str]

    web3_rpc_url: Optional[str]
    watch_address: Optional[str]
    erc20_token_address: Optional[str]
    etherscan_api_key: Optional[str]
    allowed_ips: List[str]


def load_config() -> Config:
    # Load from config/api_keys.json (optional)
    api_keys = {}
    try:
        with open('config/api_keys.json', 'r') as f:
            api_keys = json.load(f)
    except FileNotFoundError:
        logging.warning("config/api_keys.json not found, using empty API keys")
        api_keys = {}
    except Exception as e:
        logging.error(f"Error loading API keys: {e}")
        api_keys = {}

    # Load from config/settings.yaml (optional). Override path with CRYPTSWARM_SETTINGS_PATH.
    settings = {}
    settings_path = os.getenv('CRYPTSWARM_SETTINGS_PATH', 'config/settings.yaml')
    try:
        with open(settings_path, 'r') as f:
            settings = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logging.warning(f"{settings_path} not found, using default settings")
        settings = {}
    except Exception as e:
        logging.error(f"Error loading settings from {settings_path}: {e}")
        settings = {}

    return Config(
        binance_api_key=api_keys.get("binance_api_key", ""),
        binance_api_secret=api_keys.get("binance_api_secret", ""),
        binance_testnet=settings.get("binance_testnet", True),
        exchange=settings.get("exchange", "kraken"),
        kraken_api_key=api_keys.get("kraken_api_key", ""),
        kraken_api_secret=api_keys.get("kraken_api_secret", ""),

        dry_run=settings.get("dry_run", True),

        symbol=settings.get("symbol", "BTCUSDT"),
        interval=settings.get("interval", "1m"),
        lookback=settings.get("lookback", 500),

        strategy_type=settings.get("strategy_type", "sma_crossover"),
        sma_fast=settings.get("sma_fast", 20),
        sma_slow=settings.get("sma_slow", 50),
        rsi_window=settings.get("rsi_window", 14),
        rsi_oversold=settings.get("rsi_oversold", 30),
        rsi_overbought=settings.get("rsi_overbought", 70),
        macd_fast=settings.get("macd_fast", 12),
        macd_slow=settings.get("macd_slow", 26),
        macd_signal=settings.get("macd_signal", 9),

        quote_order_size=settings.get("quote_order_size", 25.0),
        max_position_base=settings.get("max_position_base", 0.002),
        risk_pct=settings.get("risk_pct", 0.01),
        ratio_gate_enabled=settings.get("ratio_gate_enabled", True),
        target_base_ratio=settings.get("target_base_ratio", 0.5),
        target_ratio_band=settings.get("target_ratio_band", 0.1),

        poll_seconds=settings.get("poll_seconds", 10),
        wallet_poll_seconds=settings.get("wallet_poll_seconds", 5),

        max_notional=settings.get("max_notional", 2.0),
        spread_guard_pct=settings.get("spread_guard_pct", 0.05),
        throttle_multiplier=settings.get("throttle_multiplier", 0.05),
        strategy_cooldown=settings.get("strategy_cooldown", 120),
        throttle_bypass_notional=settings.get("throttle_bypass_notional", settings.get("max_notional", 2.0)),
        min_trade_usd=settings.get("min_trade_usd", 2.0),
        max_trade_usd=settings.get("max_trade_usd", 5.0),

        onchain_enabled=settings.get("onchain_enabled", False),
        dex_provider=settings.get("dex_provider", "1inch"),
        onchain_chain_id=settings.get("onchain_chain_id", 1),
        onchain_slippage_bps=settings.get("onchain_slippage_bps", 50),
        onchain_allowed_pairs=settings.get("onchain_allowed_pairs", []),
        onchain_force_base=settings.get("onchain_force_base", False),
        onchain_force_chain_id=settings.get("onchain_force_chain_id"),
        onchain_prefer_l2=settings.get("onchain_prefer_l2", False),
        onchain_l2_chain_id=settings.get("onchain_l2_chain_id", 8453),
        onchain_max_gas_gwei=settings.get("onchain_max_gas_gwei", 0.0),
        onchain_max_gas_eth=settings.get("onchain_max_gas_eth", 0.0),
        onchain_max_gas_usd=settings.get("onchain_max_gas_usd", 0.0),
        onchain_max_fee_eth=settings.get("onchain_max_fee_eth", 0.0),
        onchain_fallback_to_cex=settings.get("onchain_fallback_to_cex", False),
        swarmguard_enabled=settings.get("swarmguard_enabled", True),
        liquidity_k=settings.get("liquidity_k", 0.08),
        liquidity_m=settings.get("liquidity_m", 0.02),
        expected_move_min_pct=settings.get("expected_move_min_pct", 0.003),
        fee_buffer_pct=settings.get("fee_buffer_pct", 0.0015),
        onchain_token_addresses=settings.get("onchain_token_addresses"),
        swarmguard_max_trades_per_hour=settings.get("swarmguard_max_trades_per_hour", 12),
        swarmguard_min_trade_interval_sec=settings.get("swarmguard_min_trade_interval_sec", 120),
        swarmguard_consensus_min=settings.get("swarmguard_consensus_min", 3),
        swarmguard_consensus_penalty=settings.get("swarmguard_consensus_penalty", 0.7),
        swarmguard_weight_decay=settings.get("swarmguard_weight_decay", 0.9),
        swarmguard_weight_floor=settings.get("swarmguard_weight_floor", 0.4),
        swarmguard_small_trade_usd=settings.get("swarmguard_small_trade_usd", settings.get("max_trade_usd", 5.0)),
        swarmguard_small_trade_bypass=settings.get("swarmguard_small_trade_bypass", True),
        swarmguard_rules_path=settings.get("swarmguard_rules_path", "config/swarmguard_rules_v1.json"),
        swarmguard_risk_rules_path=settings.get("swarmguard_risk_rules_path", "config/swarmguard_rules.json"),
        swarmguard_risk_register_path=settings.get("swarmguard_risk_register_path", "config/risk_register.json"),
        swarmguard_risk_map_path=settings.get("swarmguard_risk_map_path", "config/risk_agent_control_map.json"),
        multi_symbol_enabled=settings.get("multi_symbol_enabled", False),
        multi_symbols=settings.get("multi_symbols", []),
        coin_selection_enabled=settings.get("coin_selection_enabled", False),
        coin_selection_interval_sec=settings.get("coin_selection_interval_sec", 600),
        coin_selection_min_vol_usd=settings.get("coin_selection_min_vol_usd", 100000),
        coin_selection_spread_max=settings.get("coin_selection_spread_max", 0.03),
        coin_selection_top_n=settings.get("coin_selection_top_n", 3),
        coin_selection_lookback=settings.get("coin_selection_lookback", 60),
        coin_selection_max_symbols=settings.get("coin_selection_max_symbols", 25),
        coin_selection_quote_assets=settings.get("coin_selection_quote_assets", ["USDT", "USDC", "USD"]),
        coin_selection_include=settings.get("coin_selection_include", []),
        coin_selection_exclude=settings.get("coin_selection_exclude", []),
        coin_selection_auto_switch=settings.get("coin_selection_auto_switch", True),

        governance_authoritative=settings.get("governance_authoritative", True),
        regime_timeframes=settings.get("regime_timeframes", ["1m", "5m", "1h"]),
        regime_min_duration_sec=settings.get("regime_min_duration_sec", 300),
        regime_confirmations=settings.get("regime_confirmations", 3),
        regime_confidence_threshold=settings.get("regime_confidence_threshold", 0.15),
        svs_min_threshold=settings.get("svs_min_threshold", 0.35),
        nurse_review_interval_sec=settings.get("nurse_review_interval_sec", 120),

        approval_threshold_usd=settings.get("approval_threshold_usd", 10.0),
        auto_trade_enabled=settings.get("auto_trade_enabled", False),
        risk_tolerance=settings.get("risk_tolerance", 0.5),
        max_position_pct=settings.get("max_position_pct", 0.10),

        kill_switch_enabled=settings.get("kill_switch_enabled", True),
        daily_loss_throttle_pct=settings.get("daily_loss_throttle_pct", -0.25),
        daily_loss_halt_pct=settings.get("daily_loss_halt_pct", -0.50),
        rejects_threshold_5m=settings.get("rejects_threshold_5m", 20),
        slippage_threshold=settings.get("slippage_threshold", 0.02),
        market_stale_sec=settings.get("market_stale_sec", 300.0),
        wallet_stale_sec=settings.get("wallet_stale_sec", 300.0),
        throttle_clear_sec=settings.get("throttle_clear_sec", 120),
        killswitch_equity_floor_usd=settings.get("killswitch_equity_floor_usd", 25.0),
        max_drawdown_pct=settings.get("max_drawdown_pct", 10.0),
        daily_loss_limit=settings.get("daily_loss_limit", 50.0),
        max_consecutive_losses=settings.get("max_consecutive_losses", 5),
        kill_switch_grace_sec=settings.get("kill_switch_grace_sec", 120),
        kill_switch_enforce_stale=settings.get("kill_switch_enforce_stale", True),
        adaptive_min_liquidity_usd=settings.get("adaptive_min_liquidity_usd", 10000.0),
        adaptive_max_spread_pct=settings.get("adaptive_max_spread_pct", 0.03),
        adaptive_min_volatility_pct=settings.get("adaptive_min_volatility_pct", 0.20),
        adaptive_max_volatility_pct=settings.get("adaptive_max_volatility_pct", 1.00),

        ui_enabled=settings.get("ui_enabled", True),
        ui_host=settings.get("ui_host", "0.0.0.0"),
        ui_port=settings.get("ui_port", 5000),

        network_enabled=settings.get("network_enabled", False),  # Default to False for easier startup
        redis_host=settings.get("redis_host", "localhost"),
        redis_port=settings.get("redis_port", 6379),
        redis_db=settings.get("redis_db", 0),
        redis_password=settings.get("redis_password"),

        data_store_enabled=settings.get("data_store_enabled", True),
        db_path=settings.get("db_path", "data/swarm_data.db"),

        performance_enabled=settings.get("performance_enabled", True),

        security_enabled=settings.get("security_enabled", False),  # Default to False
        encryption_key_file=settings.get("encryption_key_file", "config/encryption.key"),
        security_auto_pause=settings.get("security_auto_pause", False),
        security_always_armed=settings.get("security_always_armed", True),

        walletconnect_project_id=settings.get("walletconnect_project_id") or api_keys.get("walletconnect_project_id"),
        oneinch_api_key=os.getenv("ONEINCH_API_KEY") or settings.get("oneinch_api_key") or api_keys.get("oneinch_api_key"),
        buzz_base_url=settings.get("buzz_base_url", "http://localhost:9009"),
        buzz_shared_secret=settings.get("buzz_shared_secret", ""),
        buzz_account=settings.get("buzz_account", "hivenance-system"),

        queen_telegram_confirm_enabled=settings.get("queen_telegram_confirm_enabled", False),
        queen_telegram_confirm_timeout_sec=settings.get("queen_telegram_confirm_timeout_sec", 90),
        queen_telegram_fail_open=settings.get("queen_telegram_fail_open", False),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or settings.get("telegram_bot_token") or api_keys.get("telegram_bot_token"),
        telegram_chat_id=settings.get("telegram_chat_id") or api_keys.get("telegram_chat_id"),

        web3_rpc_url=api_keys.get("web3_rpc_url") or settings.get("web3_rpc_url"),
        watch_address=api_keys.get("watch_address") or settings.get("watch_address"),
        erc20_token_address=api_keys.get("erc20_token_address") or settings.get("erc20_token_address"),
        etherscan_api_key=api_keys.get("etherscan_api_key") or settings.get("etherscan_api_key"),
        allowed_ips=settings.get("allowed_ips", []),
    )


def main():
    setup_tracing()
    setup_logging()
    cfg = load_config()
    # Force Base chain for on-chain swaps if configured
    try:
        if getattr(cfg, "onchain_enabled", False) and getattr(cfg, "onchain_force_base", True):
            cfg.onchain_chain_id = 8453
            if not getattr(cfg, "web3_rpc_url", None):
                cfg.web3_rpc_url = "https://mainnet.base.org"
    except Exception:
        pass
    # Live mode override: set CRYPTSWARM_LIVE=1 to force live trading behavior.
    # Safety systems remain enabled; only execution mode/toggles are promoted.
    try:
        live_env = os.getenv('CRYPTSWARM_LIVE') == '1'
    except Exception:
        live_env = False
    live_cfg_flag = bool(getattr(cfg, 'live_mode', False)) if hasattr(cfg, 'live_mode') else False
    if live_env or live_cfg_flag:
        logging.warning('Live mode active: enabling real execution and auto-trade (safety controls stay ON).')
        try:
            cfg.dry_run = False
        except Exception:
            pass
        try:
            cfg.auto_trade_enabled = True
        except Exception:
            pass

    # On Windows host runs, the Docker service name "swarm-redis" is not resolvable.
    # Disable auto network enable to avoid a startup hang.
    try:
        if os.name == "nt" and getattr(cfg, "network_enabled", False) and getattr(cfg, "redis_host", "") in ("swarm-redis", "redis"):
            logging.warning("Disabling network_enabled for local Windows run (redis host swarm-redis not resolvable).")
            cfg.network_enabled = False
    except Exception:
        pass

    # Create exchange client only if API keys are provided
    client = None
    if cfg.exchange.lower() == "kraken":
        try:
            import ccxt
            if cfg.kraken_api_key and cfg.kraken_api_secret:
                client = ccxt.kraken({
                    "apiKey": cfg.kraken_api_key,
                    "secret": cfg.kraken_api_secret,
                    "enableRateLimit": True
                })
                logging.info("Kraken client initialized successfully")
            else:
                # Allow public market data without keys
                client = ccxt.kraken({
                    "enableRateLimit": True
                })
                logging.info("No Kraken API keys provided - using public client for market data")
        except Exception as e:
            logging.warning(f"Failed to initialize Kraken client: {e}")
            client = None
    else:
        if cfg.binance_api_key and cfg.binance_api_secret:
            try:
                client = Client(cfg.binance_api_key, cfg.binance_api_secret)
                # Testnet routing
                if cfg.binance_testnet:
                    client.API_URL = "https://testnet.binance.vision/api"
                logging.info("Binance client initialized successfully")
            except Exception as e:
                logging.warning(f"Failed to initialize Binance client: {e}")
                client = None
        else:
            logging.info("No Binance API keys provided - trading agents will be disabled")

    coordinator = SwarmCoordinator(cfg)
    # Always initialize so optional agents (wallet/UI/data store) come up even without an exchange client.
    try:
        coordinator.initialize(client)
    except Exception:
        logging.exception('Coordinator.initialize failed; continuing with best-effort startup')

    # Publish startup system status buzz so UI reflects runtime dry/live mode immediately
    try:
        now_ms = int(time.time() * 1000)
        live_env = os.getenv('CRYPTSWARM_LIVE') == '1'
        live_cfg_flag = getattr(cfg, 'live_mode', False) if hasattr(cfg, 'live_mode') else False
        live_flag = bool(live_env or live_cfg_flag) and not bool(cfg.dry_run)
        evt = {'buzz': {'type': 'buzz.system.status', 'source': 'COORDINATOR', 'ts': now_ms}, 'payload': {'dry_run': bool(cfg.dry_run), 'live': bool(live_flag)}}
        try:
            coordinator.share_data('buzz.system.status', evt)
        except Exception:
            pass
    except Exception:
        pass

    # Try to enable Network (Redis) at startup if configured
    if cfg.network_enabled:
        try:
            success = coordinator.enable_network(
                host=cfg.redis_host,
                port=cfg.redis_port,
                db=cfg.redis_db,
                password=cfg.redis_password,
            )
            if success:
                logging.info("Network (Redis) enabled at startup.")
            else:
                logging.warning("Network (Redis) not enabled at startup. Use UI to connect.")
        except Exception as e:
            logging.warning(f"Network enable attempt failed at startup: {e}")

    print(
        f"Starting swarm agent | symbol={cfg.symbol} interval={cfg.interval} "
        f"fast={cfg.sma_fast} slow={cfg.sma_slow} lookback={cfg.lookback} "
        f"exchange={cfg.exchange} testnet={cfg.binance_testnet} dry_run={cfg.dry_run}"
    )

    # Resilient run loop: restart coordinator on unexpected crashes to keep service available
    while True:
        try:
            coordinator.run_loop()
            # normal exit from run_loop (e.g., graceful shutdown) -> break
            break
        except Exception:
            logging.exception('Coordinator.run_loop crashed; will attempt restart in 5s')
            try:
                time.sleep(5)
            except Exception:
                pass
            # attempt to restart background tasks/agents if possible
            try:
                coordinator.start_background_tasks()
            except Exception:
                pass


if __name__ == "__main__":
    main()
