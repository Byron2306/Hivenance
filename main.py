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
    live_mode: bool
    phase0_quarantine: bool
    phoenix_phase: int
    phase1_observation_enabled: bool
    phase1_observation_interval_sec: int
    phase1_observation_max_symbols: int
    phase1_observation_quote_assets: List[str]
    phase1_observation_include: List[str]
    phase1_observation_exclude: List[str]
    phase1_observation_timeframe: str
    phase1_observation_lookback: int
    phase1_observation_orderbook_depth: int
    phase1_observation_short_window: int
    phase1_observation_baseline_window: int
    phase1_observation_stale_after_sec: int
    phase1_observation_min_success_ratio: float
    phase1_observation_min_listing_age_days: float
    phase1_observation_min_quote_volume_usd: float
    phase1_observation_min_depth_usd_25bps: float
    phase1_observation_max_spread_bps: float
    phase1_observation_min_data_quality: float

    phase2_hypotheses_enabled: bool
    phase2_horizons_seconds: List[int]
    phase2_min_data_quality: float
    phase2_taker_fee_bps_per_side: float
    phase2_reference_notional_usd: float
    phase2_latency_buffer_bps: float
    phase2_safety_buffer_bps: float
    phase2_max_total_cost_bps: float
    phase2_minimum_edge_multiple: float
    phase2_breakout_min_expansion: float
    phase2_breakout_min_volume_zscore: float
    phase2_breakout_min_return_zscore: float
    phase2_reversion_min_stretch_zscore: float
    phase2_reversion_min_range_extreme: float
    phase2_settlement_tolerance_sec: int
    phase2_readiness_min_forecasts: int
    phase2_readiness_min_settled_non_abstain: int
    phase2_readiness_min_distinct_days: int

    phase3_execution_lab_enabled: bool
    phase3_interval_sec: int
    phase3_max_forecasts_per_cycle: int
    phase3_simulated_equity_usd: float
    phase3_risk_fraction: float
    phase3_sleeve_fraction: float
    phase3_max_notional_usd: float
    phase3_max_depth_participation: float
    phase3_base_latency_ms: float
    phase3_max_slippage_bps: float
    phase3_min_data_quality: float
    phase3_min_notional_usd: float
    phase3_maker_fee_bps: float
    phase3_taker_fee_bps: float
    phase3_max_entry_spread_bps: float
    phase3_readiness_min_completed: int
    phase3_readiness_max_mean_2x_loss_bps: float

    phase4_validation_enabled: bool
    phase4_interval_sec: int
    phase4_max_rows: int
    phase4_min_candidate_trades: int
    phase4_min_distinct_days: int
    phase4_walk_forward_folds: int
    phase4_purge_seconds: int
    phase4_embargo_seconds: int
    phase4_bootstrap_samples: int
    phase4_bootstrap_block_size: int
    phase4_dsr_min_probability: float
    phase4_pbo_max: float
    phase4_min_walk_forward_positive_ratio: float
    phase4_min_parameter_positive_ratio: float
    phase4_max_symbol_profit_concentration: float
    phase4_max_month_profit_concentration: float
    phase4_max_cost2_loss_bps: float
    phase4_selection_min_probability: float

    phase5_shadow_enabled: bool
    phase5_interval_sec: int
    phase5_shadow_max_intents_per_cycle: int
    phase5_shadow_reference_notional_usd: float
    phase5_shadow_stop_distance_bps: float
    phase5_shadow_entry_latency_ms: float
    phase5_shadow_chase_timeout_sec: int
    phase5_shadow_settlement_tolerance_sec: int
    phase5_shadow_min_data_quality: float
    phase5_shadow_max_spread_bps: float
    phase5_readiness_min_distinct_days: int
    phase5_readiness_min_settled: int
    phase5_readiness_max_cost_mae_bps: float
    phase5_readiness_min_fill_ratio: float
    phase5_readiness_require_positive_mean: bool
    phase5_human_approval_required: bool
    phase5_parameter_freeze_required: bool
    phase6_canary_enabled: bool
    phase6_live_submission_enabled: bool
    phase6_allowed_symbols: List[str]
    phase6_max_notional_usd: float
    phase6_max_entry_orders_per_approval: int
    phase6_approval_lease_sec: int
    phase6_candidate_max_age_sec: int
    phase6_market_data_max_age_sec: int
    phase6_min_data_quality: float
    phase6_max_spread_bps: float
    phase6_max_slippage_bps: float
    phase6_stop_distance_bps: float
    phase6_target_distance_bps: float
    phase6_deadman_timeout_sec: int
    phase6_deadman_refresh_sec: int
    phase6_require_isolated_account: bool
    phase6_max_open_orders: int
    phase6_max_open_positions: int
    phase6_daily_loss_halt_usd: float
    phase6_min_phase7_round_trips: int
    phase6_private_api_base_url: str
    phase6_private_api_timeout_sec: float

    phase7_growth_enabled: bool
    phase7_stage_activation_enabled: bool
    phase7_max_stage: int
    phase7_allowed_symbols: List[str]
    phase7_stage_notional_caps_usd: List[float]
    phase7_stage_symbol_caps: List[int]
    phase7_proposal_cooldown_sec: int
    phase7_proposal_expiry_sec: int
    phase7_approval_lease_sec: int
    phase7_min_new_round_trips: int
    phase7_min_distinct_days: int
    phase7_require_positive_total_pnl: bool
    phase7_min_profit_factor: float
    phase7_max_drawdown_bps: float
    phase7_max_loss_rate: float
    phase7_max_rejection_rate: float
    phase7_max_mean_abs_slippage_bps: float
    phase7_auto_demotion_enabled: bool

    phase4_selection_min_expected_net_bps: float
    phase4_human_review_required: bool

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
    ratio_gate_trade_override_enabled: bool

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
    onchain_require_gas_estimate: bool
    onchain_min_output_ratio: float
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
    coin_selection_target_volatility: float
    coin_selection_max_volatility: float
    core_assets: List[str]
    experimental_assets: List[str]
    stable_reserve_assets: List[str]
    capital_allocator_enabled: bool
    capital_reserve_pct: float
    core_allocation_pct: float
    experimental_allocation_pct: float
    symbol_memory_path: str
    promotion_allowed_stages: List[str]
    promotion_min_paper_trades: int
    promotion_min_win_rate: float
    promotion_max_drawdown_pct: float
    wallet_safety_enabled: bool
    wallet_max_daily_spend_usd: float
    wallet_max_token_exposure_pct: float
    wallet_approval_check_enabled: bool
    multichain_watch_enabled: bool
    multichain_watch_chains: List[dict]
    market_context_enabled: bool
    btc_dominance_risk_off_threshold: float
    volatility_harvest_enabled: bool
    volatility_harvest_min_expansion: float
    volatility_harvest_min_volume_surge: float
    volatility_harvest_min_return_pct: float
    volatility_harvest_max_drawdown_pct: float
    exit_manager_enabled: bool
    exit_hard_stop_pct: float
    exit_take_profit_pct: float
    exit_trailing_window: int
    exit_trailing_stop_pct: float
    exit_time_stop_sec: int
    dex_min_output_ratio: float
    dex_max_price_impact_pct: float
    dex_max_gas_drag_pct: float
    dex_min_liquidity_usd: float
    dex_margin_oracle_enabled: bool
    dex_probe_amount_usd: float
    dex_min_roundtrip_ratio: float
    dex_min_volume_24h_usd: float
    dex_min_txns_24h: int
    dex_min_token_age_hours: float
    dex_oracle_cache_sec: int
    dex_oracle_timeout_sec: float
    quote_retry_attempts: int
    quote_retry_backoff_sec: float
    quote_backoff_cooldown_sec: int
    last_good_quote_ttl_sec: int
    dex_ready_roundtrip_ratio: float
    goplus_security_enabled: bool
    goplus_cache_sec: int
    contract_max_transfer_tax_pct: float
    contract_max_top10_holder_pct: float
    market_bee_enabled: bool
    market_bee_top_n: int
    market_bee_snapshot_interval_sec: int
    paper_promotion_eval_interval_sec: int
    paper_promotion_window_days: int
    contract_min_liquidity_to_fdv: float
    volatility_harvest_quote_asset: str
    volatility_harvest_require_exit: bool
    tax_export_enabled: bool
    tax_export_path: str

    governance_authoritative: bool
    regime_timeframes: List[str]
    regime_min_duration_sec: int
    regime_confirmations: int
    regime_confidence_threshold: float
    svs_min_threshold: float
    nurse_review_interval_sec: int

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
    settings_path: str
    config_snapshot_dir: str
    config_audit_log_path: str

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
    public_bot_integrations_enabled: bool
    local_crypto_bot_implementations_enabled: bool
    public_bot_repo_root: str
    public_bot_backtest_dir: str
    hummingbot_sidecar_live_enabled: bool
    hummingbot_sidecar_command: str
    hummingbot_sidecar_config_dir: str
    hummingbot_v2_default_executor: str
    hummingbot_v2_twap_duration_sec: int
    hummingbot_v2_twap_interval_sec: int
    hummingbot_v2_grid_width_pct: float
    hummingbot_v2_dca_steps: int
    hummingbot_v2_dca_step_pct: float
    hummingbot_v2_leverage: int
    market_making_advisors_enabled: bool
    market_making_quote_placement_enabled: bool
    pmm_simple_min_liquidity_usd: float
    pmm_simple_max_spread_pct: float
    pmm_simple_min_quote_spread_pct: float
    pmm_dynamic_min_volume_24h_usd: float
    pmm_dynamic_max_spread_pct: float
    pmm_dynamic_max_abs_change_24h_pct: float
    pmm_dynamic_min_quote_spread_pct: float
    public_bot_metrics_auto_promote: bool
    ml_research_lab_enabled: bool
    ml_model_families_enabled: List[str]
    execution_parity_max_latency_ms: int
    execution_parity_max_slippage_pct: float
    execution_parity_min_fill_ratio: float
    execution_parity_max_queue_position_risk: float
    orderbook_capture_enabled: bool
    orderbook_capture_depth: int
    signal_marketplace_min_originality: float
    signal_marketplace_max_drawdown: float
    signal_marketplace_min_stability: float
    signal_marketplace_min_realized_samples: int
    signal_marketplace_reward_scale: float
    signal_marketplace_weight_strength: float
    signal_marketplace_weight_realized_outcome: float
    signal_marketplace_weight_originality: float
    signal_marketplace_weight_stability: float
    signal_marketplace_weight_win_rate: float
    signal_marketplace_weight_drawdown_penalty: float

    openclaw_autonomy_enabled: bool
    openclaw_autonomy_min_score: float

    web3_rpc_url: Optional[str]
    watch_address: Optional[str]
    erc20_token_address: Optional[str]
    etherscan_api_key: Optional[str]
    allowed_ips: List[str]
    profile_path: str
    profile_name: str
    profile_reason: str


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

    # Load from config/settings.yaml (optional)
    settings = {}
    try:
        with open('config/settings.yaml', 'r') as f:
            settings = yaml.safe_load(f)
    except FileNotFoundError:
        logging.warning("config/settings.yaml not found, using default settings")
        settings = {}
    except Exception as e:
        logging.error(f"Error loading settings: {e}")
        settings = {}
    profile_path = os.getenv("HIVENANCE_PROFILE_PATH") or settings.get("profile_path") or "config/conservative_state.yaml"
    try:
        if profile_path and os.path.exists(profile_path):
            with open(profile_path, "r") as f:
                profile = yaml.safe_load(f) or {}
            if isinstance(profile, dict):
                settings.update(profile)
                settings["profile_path"] = profile_path
    except Exception as e:
        logging.error(f"Error loading profile overlay {profile_path}: {e}")

    ui_port = int(os.getenv("HIVENANCE_UI_PORT") or os.getenv("PORT") or settings.get("ui_port", 5001))
    buzz_base_url = os.getenv("BUZZ_BASE_URL") or settings.get("buzz_base_url", "http://localhost:9009")
    redis_port = int(os.getenv("REDIS_PORT") or os.getenv("HIVENANCE_REDIS_PORT") or settings.get("redis_port", 6379))
    safe_hummingbot_sidecar_command = settings.get(
        "hummingbot_sidecar_command",
        "python3 scripts/hummingbot_sidecar_runner.py --config {config_path} --dry-run=true --mode validate --compose-file docker/docker-compose.yml --service hummingbot-sidecar",
    )
    if "--dry-run=false" in safe_hummingbot_sidecar_command or "--mode docker-compose" in safe_hummingbot_sidecar_command:
        safe_hummingbot_sidecar_command = (
            "python3 scripts/hummingbot_sidecar_runner.py --config {config_path} "
            "--dry-run=true --mode validate --compose-file docker/docker-compose.yml --service hummingbot-sidecar"
        )

    return Config(
        binance_api_key=os.getenv("BINANCE_API_KEY") or api_keys.get("binance_api_key", ""),
        binance_api_secret=os.getenv("BINANCE_API_SECRET") or api_keys.get("binance_api_secret", ""),
        binance_testnet=settings.get("binance_testnet", True),
        exchange=settings.get("exchange", "kraken"),
        kraken_api_key=os.getenv("KRAKEN_API_KEY") or api_keys.get("kraken_api_key", ""),
        kraken_api_secret=os.getenv("KRAKEN_API_SECRET") or api_keys.get("kraken_api_secret", ""),

        dry_run=settings.get("dry_run", True),
        live_mode=settings.get("live_mode", False),
        phase0_quarantine=settings.get("phase0_quarantine", True),
        phoenix_phase=settings.get("phoenix_phase", 1),
        phase1_observation_enabled=settings.get("phase1_observation_enabled", True),
        phase1_observation_interval_sec=settings.get("phase1_observation_interval_sec", 120),
        phase1_observation_max_symbols=settings.get("phase1_observation_max_symbols", 12),
        phase1_observation_quote_assets=settings.get("phase1_observation_quote_assets", ["USD", "USDT", "USDC"]),
        phase1_observation_include=settings.get("phase1_observation_include", []),
        phase1_observation_exclude=settings.get("phase1_observation_exclude", []),
        phase1_observation_timeframe=settings.get("phase1_observation_timeframe", "1m"),
        phase1_observation_lookback=settings.get("phase1_observation_lookback", 121),
        phase1_observation_orderbook_depth=settings.get("phase1_observation_orderbook_depth", 50),
        phase1_observation_short_window=settings.get("phase1_observation_short_window", 5),
        phase1_observation_baseline_window=settings.get("phase1_observation_baseline_window", 60),
        phase1_observation_stale_after_sec=settings.get("phase1_observation_stale_after_sec", 180),
        phase1_observation_min_success_ratio=settings.get("phase1_observation_min_success_ratio", 0.90),
        phase1_observation_min_listing_age_days=settings.get("phase1_observation_min_listing_age_days", 90.0),
        phase1_observation_min_quote_volume_usd=settings.get("phase1_observation_min_quote_volume_usd", 5000000.0),
        phase1_observation_min_depth_usd_25bps=settings.get("phase1_observation_min_depth_usd_25bps", 25000.0),
        phase1_observation_max_spread_bps=settings.get("phase1_observation_max_spread_bps", 35.0),
        phase1_observation_min_data_quality=settings.get("phase1_observation_min_data_quality", 0.99),

        phase2_hypotheses_enabled=settings.get("phase2_hypotheses_enabled", True),
        phase2_horizons_seconds=settings.get("phase2_horizons_seconds", [300, 900, 3600]),
        phase2_min_data_quality=settings.get("phase2_min_data_quality", 0.99),
        phase2_taker_fee_bps_per_side=settings.get("phase2_taker_fee_bps_per_side", 10.0),
        phase2_reference_notional_usd=settings.get("phase2_reference_notional_usd", 5.0),
        phase2_latency_buffer_bps=settings.get("phase2_latency_buffer_bps", 2.0),
        phase2_safety_buffer_bps=settings.get("phase2_safety_buffer_bps", 3.0),
        phase2_max_total_cost_bps=settings.get("phase2_max_total_cost_bps", 150.0),
        phase2_minimum_edge_multiple=settings.get("phase2_minimum_edge_multiple", 2.0),
        phase2_breakout_min_expansion=settings.get("phase2_breakout_min_expansion", 1.25),
        phase2_breakout_min_volume_zscore=settings.get("phase2_breakout_min_volume_zscore", 0.50),
        phase2_breakout_min_return_zscore=settings.get("phase2_breakout_min_return_zscore", 0.75),
        phase2_reversion_min_stretch_zscore=settings.get("phase2_reversion_min_stretch_zscore", 1.50),
        phase2_reversion_min_range_extreme=settings.get("phase2_reversion_min_range_extreme", 0.85),
        phase2_settlement_tolerance_sec=settings.get("phase2_settlement_tolerance_sec", 600),
        phase2_readiness_min_forecasts=settings.get("phase2_readiness_min_forecasts", 300),
        phase2_readiness_min_settled_non_abstain=settings.get("phase2_readiness_min_settled_non_abstain", 100),
        phase2_readiness_min_distinct_days=settings.get("phase2_readiness_min_distinct_days", 14),

        phase3_execution_lab_enabled=settings.get("phase3_execution_lab_enabled", True),
        phase3_interval_sec=settings.get("phase3_interval_sec", 120),
        phase3_max_forecasts_per_cycle=settings.get("phase3_max_forecasts_per_cycle", 50),
        phase3_simulated_equity_usd=settings.get("phase3_simulated_equity_usd", 1000.0),
        phase3_risk_fraction=settings.get("phase3_risk_fraction", 0.0005),
        phase3_sleeve_fraction=settings.get("phase3_sleeve_fraction", 0.02),
        phase3_max_notional_usd=settings.get("phase3_max_notional_usd", 25.0),
        phase3_max_depth_participation=settings.get("phase3_max_depth_participation", 0.01),
        phase3_base_latency_ms=settings.get("phase3_base_latency_ms", 180.0),
        phase3_max_slippage_bps=settings.get("phase3_max_slippage_bps", 75.0),
        phase3_min_data_quality=settings.get("phase3_min_data_quality", 0.99),
        phase3_min_notional_usd=settings.get("phase3_min_notional_usd", 5.0),
        phase3_maker_fee_bps=settings.get("phase3_maker_fee_bps", 10.0),
        phase3_taker_fee_bps=settings.get("phase3_taker_fee_bps", 20.0),
        phase3_max_entry_spread_bps=settings.get("phase3_max_entry_spread_bps", 60.0),
        phase3_readiness_min_completed=settings.get("phase3_readiness_min_completed", 100),
        phase3_readiness_max_mean_2x_loss_bps=settings.get("phase3_readiness_max_mean_2x_loss_bps", 50.0),

        phase4_validation_enabled=settings.get("phase4_validation_enabled", True),
        phase4_interval_sec=settings.get("phase4_interval_sec", 900),
        phase4_max_rows=settings.get("phase4_max_rows", 100000),
        phase4_min_candidate_trades=settings.get("phase4_min_candidate_trades", 100),
        phase4_min_distinct_days=settings.get("phase4_min_distinct_days", 14),
        phase4_walk_forward_folds=settings.get("phase4_walk_forward_folds", 5),
        phase4_purge_seconds=settings.get("phase4_purge_seconds", 3600),
        phase4_embargo_seconds=settings.get("phase4_embargo_seconds", 3600),
        phase4_bootstrap_samples=settings.get("phase4_bootstrap_samples", 1000),
        phase4_bootstrap_block_size=settings.get("phase4_bootstrap_block_size", 5),
        phase4_dsr_min_probability=settings.get("phase4_dsr_min_probability", 0.95),
        phase4_pbo_max=settings.get("phase4_pbo_max", 0.20),
        phase4_min_walk_forward_positive_ratio=settings.get("phase4_min_walk_forward_positive_ratio", 0.60),
        phase4_min_parameter_positive_ratio=settings.get("phase4_min_parameter_positive_ratio", 0.70),
        phase4_max_symbol_profit_concentration=settings.get("phase4_max_symbol_profit_concentration", 0.25),
        phase4_max_month_profit_concentration=settings.get("phase4_max_month_profit_concentration", 0.35),
        phase4_max_cost2_loss_bps=settings.get("phase4_max_cost2_loss_bps", 50.0),
        phase4_selection_min_probability=settings.get("phase4_selection_min_probability", 0.50),

        phase5_shadow_enabled=settings.get("phase5_shadow_enabled", True),
        phase5_interval_sec=settings.get("phase5_interval_sec", 120),
        phase5_shadow_max_intents_per_cycle=settings.get("phase5_shadow_max_intents_per_cycle", 25),
        phase5_shadow_reference_notional_usd=settings.get("phase5_shadow_reference_notional_usd", 10.0),
        phase5_shadow_stop_distance_bps=settings.get("phase5_shadow_stop_distance_bps", 250.0),
        phase5_shadow_entry_latency_ms=settings.get("phase5_shadow_entry_latency_ms", 250.0),
        phase5_shadow_chase_timeout_sec=settings.get("phase5_shadow_chase_timeout_sec", 30),
        phase5_shadow_settlement_tolerance_sec=settings.get("phase5_shadow_settlement_tolerance_sec", 900),
        phase5_shadow_min_data_quality=settings.get("phase5_shadow_min_data_quality", 0.99),
        phase5_shadow_max_spread_bps=settings.get("phase5_shadow_max_spread_bps", 60.0),
        phase5_readiness_min_distinct_days=settings.get("phase5_readiness_min_distinct_days", 30),
        phase5_readiness_min_settled=settings.get("phase5_readiness_min_settled", 100),
        phase5_readiness_max_cost_mae_bps=settings.get("phase5_readiness_max_cost_mae_bps", 20.0),
        phase5_readiness_min_fill_ratio=settings.get("phase5_readiness_min_fill_ratio", 0.50),
        phase5_readiness_require_positive_mean=settings.get("phase5_readiness_require_positive_mean", True),
        phase5_human_approval_required=settings.get("phase5_human_approval_required", True),
        phase5_parameter_freeze_required=settings.get("phase5_parameter_freeze_required", True),
        phase6_canary_enabled=settings.get("phase6_canary_enabled", True),
        phase6_live_submission_enabled=settings.get("phase6_live_submission_enabled", False),
        phase6_allowed_symbols=settings.get("phase6_allowed_symbols", ["ETH/USD"]),
        phase6_max_notional_usd=settings.get("phase6_max_notional_usd", 5.0),
        phase6_max_entry_orders_per_approval=settings.get("phase6_max_entry_orders_per_approval", 1),
        phase6_approval_lease_sec=settings.get("phase6_approval_lease_sec", 900),
        phase6_candidate_max_age_sec=settings.get("phase6_candidate_max_age_sec", 30),
        phase6_market_data_max_age_sec=settings.get("phase6_market_data_max_age_sec", 10),
        phase6_min_data_quality=settings.get("phase6_min_data_quality", 0.99),
        phase6_max_spread_bps=settings.get("phase6_max_spread_bps", 30.0),
        phase6_max_slippage_bps=settings.get("phase6_max_slippage_bps", 40.0),
        phase6_stop_distance_bps=settings.get("phase6_stop_distance_bps", 250.0),
        phase6_target_distance_bps=settings.get("phase6_target_distance_bps", 400.0),
        phase6_deadman_timeout_sec=settings.get("phase6_deadman_timeout_sec", 60),
        phase6_deadman_refresh_sec=settings.get("phase6_deadman_refresh_sec", 20),
        phase6_require_isolated_account=settings.get("phase6_require_isolated_account", True),
        phase6_max_open_orders=settings.get("phase6_max_open_orders", 1),
        phase6_max_open_positions=settings.get("phase6_max_open_positions", 1),
        phase6_daily_loss_halt_usd=settings.get("phase6_daily_loss_halt_usd", 1.0),
        phase6_min_phase7_round_trips=settings.get("phase6_min_phase7_round_trips", 50),
        phase6_private_api_base_url=settings.get("phase6_private_api_base_url", "https://api.kraken.com"),
        phase6_private_api_timeout_sec=settings.get("phase6_private_api_timeout_sec", 10.0),

        phase7_growth_enabled=settings.get("phase7_growth_enabled", True),
        phase7_stage_activation_enabled=settings.get("phase7_stage_activation_enabled", False),
        phase7_max_stage=settings.get("phase7_max_stage", 4),
        phase7_allowed_symbols=settings.get("phase7_allowed_symbols", ["ETH/USD", "BTC/USD", "SOL/USD"]),
        phase7_stage_notional_caps_usd=settings.get("phase7_stage_notional_caps_usd", [5.0, 7.5, 10.0, 15.0, 20.0]),
        phase7_stage_symbol_caps=settings.get("phase7_stage_symbol_caps", [1, 1, 2, 2, 3]),
        phase7_proposal_cooldown_sec=settings.get("phase7_proposal_cooldown_sec", 86400),
        phase7_proposal_expiry_sec=settings.get("phase7_proposal_expiry_sec", 604800),
        phase7_approval_lease_sec=settings.get("phase7_approval_lease_sec", 3600),
        phase7_min_new_round_trips=settings.get("phase7_min_new_round_trips", 50),
        phase7_min_distinct_days=settings.get("phase7_min_distinct_days", 14),
        phase7_require_positive_total_pnl=settings.get("phase7_require_positive_total_pnl", True),
        phase7_min_profit_factor=settings.get("phase7_min_profit_factor", 1.05),
        phase7_max_drawdown_bps=settings.get("phase7_max_drawdown_bps", 500.0),
        phase7_max_loss_rate=settings.get("phase7_max_loss_rate", 0.65),
        phase7_max_rejection_rate=settings.get("phase7_max_rejection_rate", 0.05),
        phase7_max_mean_abs_slippage_bps=settings.get("phase7_max_mean_abs_slippage_bps", 40.0),
        phase7_auto_demotion_enabled=settings.get("phase7_auto_demotion_enabled", True),

        phase4_selection_min_expected_net_bps=settings.get("phase4_selection_min_expected_net_bps", 0.0),
        phase4_human_review_required=settings.get("phase4_human_review_required", True),

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
        ratio_gate_trade_override_enabled=settings.get("ratio_gate_trade_override_enabled", False),

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
        onchain_require_gas_estimate=settings.get("onchain_require_gas_estimate", True),
        onchain_min_output_ratio=settings.get("onchain_min_output_ratio", 0.90),
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
        swarmguard_small_trade_bypass=settings.get("swarmguard_small_trade_bypass", False),
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
        coin_selection_auto_switch=settings.get("coin_selection_auto_switch", False),
        coin_selection_target_volatility=settings.get("coin_selection_target_volatility", 0.006),
        coin_selection_max_volatility=settings.get("coin_selection_max_volatility", 0.025),
        core_assets=settings.get("core_assets", ["BTC", "ETH", "USDC"]),
        experimental_assets=settings.get("experimental_assets", ["XCN", "TOSHI", "WLD"]),
        stable_reserve_assets=settings.get("stable_reserve_assets", ["USDC", "USDT", "USD"]),
        capital_allocator_enabled=settings.get("capital_allocator_enabled", True),
        capital_reserve_pct=settings.get("capital_reserve_pct", 0.65),
        core_allocation_pct=settings.get("core_allocation_pct", 0.30),
        experimental_allocation_pct=settings.get("experimental_allocation_pct", 0.05),
        symbol_memory_path=settings.get("symbol_memory_path", "data/symbol_memory.json"),
        promotion_allowed_stages=settings.get("promotion_allowed_stages", ["paper", "research_import"]),
        promotion_min_paper_trades=settings.get("promotion_min_paper_trades", 25),
        promotion_min_win_rate=settings.get("promotion_min_win_rate", 0.52),
        promotion_max_drawdown_pct=settings.get("promotion_max_drawdown_pct", 5.0),
        wallet_safety_enabled=settings.get("wallet_safety_enabled", True),
        wallet_max_daily_spend_usd=settings.get("wallet_max_daily_spend_usd", 25.0),
        wallet_max_token_exposure_pct=settings.get("wallet_max_token_exposure_pct", 0.35),
        wallet_approval_check_enabled=settings.get("wallet_approval_check_enabled", True),
        multichain_watch_enabled=settings.get("multichain_watch_enabled", False),
        multichain_watch_chains=settings.get("multichain_watch_chains", []),
        market_context_enabled=settings.get("market_context_enabled", True),
        btc_dominance_risk_off_threshold=settings.get("btc_dominance_risk_off_threshold", 58.0),
        volatility_harvest_enabled=settings.get("volatility_harvest_enabled", False),
        volatility_harvest_min_expansion=settings.get("volatility_harvest_min_expansion", 1.15),
        volatility_harvest_min_volume_surge=settings.get("volatility_harvest_min_volume_surge", 0.85),
        volatility_harvest_min_return_pct=settings.get("volatility_harvest_min_return_pct", 0.002),
        volatility_harvest_max_drawdown_pct=settings.get("volatility_harvest_max_drawdown_pct", 0.08),
        exit_manager_enabled=settings.get("exit_manager_enabled", True),
        exit_hard_stop_pct=settings.get("exit_hard_stop_pct", 0.025),
        exit_take_profit_pct=settings.get("exit_take_profit_pct", 0.04),
        exit_trailing_window=settings.get("exit_trailing_window", 12),
        exit_trailing_stop_pct=settings.get("exit_trailing_stop_pct", 0.025),
        exit_time_stop_sec=settings.get("exit_time_stop_sec", 21600),
        dex_min_output_ratio=settings.get("dex_min_output_ratio", settings.get("onchain_min_output_ratio", 0.90)),
        dex_max_price_impact_pct=settings.get("dex_max_price_impact_pct", 0.02),
        dex_max_gas_drag_pct=settings.get("dex_max_gas_drag_pct", 0.01),
        dex_min_liquidity_usd=settings.get("dex_min_liquidity_usd", 0.0),
        dex_margin_oracle_enabled=settings.get("dex_margin_oracle_enabled", True),
        dex_probe_amount_usd=settings.get("dex_probe_amount_usd", settings.get("quote_order_size", 1.0)),
        dex_min_roundtrip_ratio=settings.get("dex_min_roundtrip_ratio", 0.94),
        dex_min_volume_24h_usd=settings.get("dex_min_volume_24h_usd", 25000),
        dex_min_txns_24h=settings.get("dex_min_txns_24h", 50),
        dex_min_token_age_hours=settings.get("dex_min_token_age_hours", 24),
        dex_oracle_cache_sec=settings.get("dex_oracle_cache_sec", 45),
        dex_oracle_timeout_sec=settings.get("dex_oracle_timeout_sec", 8),
        quote_retry_attempts=settings.get("quote_retry_attempts", 3),
        quote_retry_backoff_sec=settings.get("quote_retry_backoff_sec", 0.6),
        quote_backoff_cooldown_sec=settings.get("quote_backoff_cooldown_sec", 30),
        last_good_quote_ttl_sec=settings.get("last_good_quote_ttl_sec", 900),
        dex_ready_roundtrip_ratio=settings.get("dex_ready_roundtrip_ratio", 0.985),
        goplus_security_enabled=settings.get("goplus_security_enabled", True),
        goplus_cache_sec=settings.get("goplus_cache_sec", 3600),
        contract_max_transfer_tax_pct=settings.get("contract_max_transfer_tax_pct", 0.05),
        contract_max_top10_holder_pct=settings.get("contract_max_top10_holder_pct", 0.80),
        market_bee_enabled=settings.get("market_bee_enabled", True),
        market_bee_top_n=settings.get("market_bee_top_n", 4),
        market_bee_snapshot_interval_sec=settings.get("market_bee_snapshot_interval_sec", 300),
        paper_promotion_eval_interval_sec=settings.get("paper_promotion_eval_interval_sec", 3600),
        paper_promotion_window_days=settings.get("paper_promotion_window_days", 30),
        contract_min_liquidity_to_fdv=settings.get("contract_min_liquidity_to_fdv", 0.002),
        volatility_harvest_quote_asset=settings.get("volatility_harvest_quote_asset", "USD"),
        volatility_harvest_require_exit=settings.get("volatility_harvest_require_exit", True),
        tax_export_enabled=settings.get("tax_export_enabled", True),
        tax_export_path=settings.get("tax_export_path", "data/tax_export.csv"),

        governance_authoritative=settings.get("governance_authoritative", True),
        regime_timeframes=settings.get("regime_timeframes", ["1m", "5m", "1h"]),
        regime_min_duration_sec=settings.get("regime_min_duration_sec", 300),
        regime_confirmations=settings.get("regime_confirmations", 3),
        regime_confidence_threshold=settings.get("regime_confidence_threshold", 0.15),
        svs_min_threshold=settings.get("svs_min_threshold", 0.35),
        nurse_review_interval_sec=settings.get("nurse_review_interval_sec", 120),

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

        ui_enabled=settings.get("ui_enabled", True),
        ui_host=settings.get("ui_host", "0.0.0.0"),
        ui_port=ui_port,

        network_enabled=settings.get("network_enabled", False),  # Default to False for easier startup
        redis_host=os.getenv("REDIS_HOST") or os.getenv("HIVENANCE_REDIS_HOST") or settings.get("redis_host", "localhost"),
        redis_port=redis_port,
        redis_db=settings.get("redis_db", 0),
        redis_password=settings.get("redis_password"),

        data_store_enabled=settings.get("data_store_enabled", True),
        db_path=settings.get("db_path", "data/swarm_data.db"),
        settings_path=settings.get("settings_path", "config/settings.yaml"),
        config_snapshot_dir=settings.get("config_snapshot_dir", "data/config_snapshots"),
        config_audit_log_path=settings.get("config_audit_log_path", "logs/config_audit.jsonl"),

        performance_enabled=settings.get("performance_enabled", True),

        security_enabled=settings.get("security_enabled", False),  # Default to False
        encryption_key_file=settings.get("encryption_key_file", "config/encryption.key"),
        security_auto_pause=settings.get("security_auto_pause", False),
        security_always_armed=settings.get("security_always_armed", True),

        walletconnect_project_id=os.getenv("WALLETCONNECT_PROJECT_ID") or settings.get("walletconnect_project_id") or api_keys.get("walletconnect_project_id"),
        oneinch_api_key=os.getenv("ONEINCH_API_KEY") or api_keys.get("oneinch_api_key"),
        buzz_base_url=buzz_base_url,
        buzz_shared_secret=os.getenv("BUZZ_SHARED_SECRET") or os.getenv("HIVE_SHARED_SECRET") or settings.get("buzz_shared_secret", ""),
        buzz_account=settings.get("buzz_account", "hivenance-system"),
        public_bot_integrations_enabled=settings.get("public_bot_integrations_enabled", True),
        local_crypto_bot_implementations_enabled=settings.get("local_crypto_bot_implementations_enabled", True),
        public_bot_repo_root=settings.get("public_bot_repo_root", "external/public-bots"),
        public_bot_backtest_dir=settings.get("public_bot_backtest_dir", "data/public_bot_backtests"),
        hummingbot_sidecar_live_enabled=settings.get("hummingbot_sidecar_live_enabled", False),
        hummingbot_sidecar_command=safe_hummingbot_sidecar_command,
        hummingbot_sidecar_config_dir=settings.get("hummingbot_sidecar_config_dir", "data/hummingbot_executors"),
        hummingbot_v2_default_executor=settings.get("hummingbot_v2_default_executor", "position"),
        hummingbot_v2_twap_duration_sec=settings.get("hummingbot_v2_twap_duration_sec", 300),
        hummingbot_v2_twap_interval_sec=settings.get("hummingbot_v2_twap_interval_sec", 30),
        hummingbot_v2_grid_width_pct=settings.get("hummingbot_v2_grid_width_pct", 0.012),
        hummingbot_v2_dca_steps=settings.get("hummingbot_v2_dca_steps", 3),
        hummingbot_v2_dca_step_pct=settings.get("hummingbot_v2_dca_step_pct", 0.006),
        hummingbot_v2_leverage=settings.get("hummingbot_v2_leverage", 1),
        market_making_advisors_enabled=settings.get("market_making_advisors_enabled", True),
        market_making_quote_placement_enabled=settings.get("market_making_quote_placement_enabled", False),
        pmm_simple_min_liquidity_usd=settings.get("pmm_simple_min_liquidity_usd", 25000.0),
        pmm_simple_max_spread_pct=settings.get("pmm_simple_max_spread_pct", 0.015),
        pmm_simple_min_quote_spread_pct=settings.get("pmm_simple_min_quote_spread_pct", 0.003),
        pmm_dynamic_min_volume_24h_usd=settings.get("pmm_dynamic_min_volume_24h_usd", 50000.0),
        pmm_dynamic_max_spread_pct=settings.get("pmm_dynamic_max_spread_pct", 0.02),
        pmm_dynamic_max_abs_change_24h_pct=settings.get("pmm_dynamic_max_abs_change_24h_pct", 0.25),
        pmm_dynamic_min_quote_spread_pct=settings.get("pmm_dynamic_min_quote_spread_pct", 0.004),
        public_bot_metrics_auto_promote=settings.get("public_bot_metrics_auto_promote", False),
        ml_research_lab_enabled=settings.get("ml_research_lab_enabled", True),
        ml_model_families_enabled=settings.get("ml_model_families_enabled", ["freqai", "finrl_crypto", "macrohft", "webcryptoagent"]),
        execution_parity_max_latency_ms=settings.get("execution_parity_max_latency_ms", 1500),
        execution_parity_max_slippage_pct=settings.get("execution_parity_max_slippage_pct", 0.01),
        execution_parity_min_fill_ratio=settings.get("execution_parity_min_fill_ratio", 0.98),
        execution_parity_max_queue_position_risk=settings.get("execution_parity_max_queue_position_risk", 0.35),
        orderbook_capture_enabled=settings.get("orderbook_capture_enabled", True),
        orderbook_capture_depth=settings.get("orderbook_capture_depth", 5),
        signal_marketplace_min_originality=settings.get("signal_marketplace_min_originality", 0.35),
        signal_marketplace_max_drawdown=settings.get("signal_marketplace_max_drawdown", 0.45),
        signal_marketplace_min_stability=settings.get("signal_marketplace_min_stability", 0.2),
        signal_marketplace_min_realized_samples=settings.get("signal_marketplace_min_realized_samples", 25),
        signal_marketplace_reward_scale=settings.get("signal_marketplace_reward_scale", 100.0),
        signal_marketplace_weight_strength=settings.get("signal_marketplace_weight_strength", 0.2),
        signal_marketplace_weight_realized_outcome=settings.get("signal_marketplace_weight_realized_outcome", 0.3),
        signal_marketplace_weight_originality=settings.get("signal_marketplace_weight_originality", 0.2),
        signal_marketplace_weight_stability=settings.get("signal_marketplace_weight_stability", 0.15),
        signal_marketplace_weight_win_rate=settings.get("signal_marketplace_weight_win_rate", 0.15),
        signal_marketplace_weight_drawdown_penalty=settings.get("signal_marketplace_weight_drawdown_penalty", 0.35),

        openclaw_autonomy_enabled=settings.get("openclaw_autonomy_enabled", False),
        openclaw_autonomy_min_score=settings.get("openclaw_autonomy_min_score", 0.55),

        web3_rpc_url=os.getenv("WEB3_RPC_URL") or settings.get("web3_rpc_url") or api_keys.get("web3_rpc_url"),
        watch_address=os.getenv("WATCH_ADDRESS") or settings.get("watch_address") or api_keys.get("watch_address"),
        erc20_token_address=os.getenv("ERC20_TOKEN_ADDRESS") or settings.get("erc20_token_address") or api_keys.get("erc20_token_address"),
        etherscan_api_key=os.getenv("ETHERSCAN_API_KEY") or api_keys.get("etherscan_api_key") or settings.get("etherscan_api_key"),
        allowed_ips=settings.get("allowed_ips", []),
        profile_path=settings.get("profile_path", profile_path),
        profile_name=settings.get("profile_name", ""),
        profile_reason=settings.get("profile_reason", ""),
    )


SUPPORTED_EXCHANGES = {"kraken", "binance"}


def apply_phase0_safety_policy(cfg: Config) -> Config:
    """Fail closed and enforce the Phase-0 observation quarantine.

    Phase 0 intentionally permits market observation, dry-run simulation, and UI
    work only. It does not permit live CEX/DEX execution, automatic promotion,
    leverage, or small-trade governance bypasses.
    """
    exchange = str(getattr(cfg, "exchange", "") or "").strip().lower()
    if exchange not in SUPPORTED_EXCHANGES:
        raise RuntimeError(
            f"Unsupported exchange {exchange!r}. Registered exchanges: "
            f"{', '.join(sorted(SUPPORTED_EXCHANGES))}."
        )
    cfg.exchange = exchange

    live_env = os.getenv("CRYPTSWARM_LIVE") == "1"
    live_requested = live_env or bool(getattr(cfg, "live_mode", False)) or not bool(getattr(cfg, "dry_run", True))

    if bool(getattr(cfg, "phase0_quarantine", True)):
        if live_requested:
            raise RuntimeError(
                "Phase-0 quarantine blocks live execution. Keep dry_run=true, "
                "live_mode=false, and CRYPTSWARM_LIVE unset until the Phase-0 exit gate is signed off."
            )
        enforced = {
            "dry_run": True,
            "live_mode": False,
            "kill_switch_enabled": True,
            "security_enabled": True,
            "governance_authoritative": True,
            "swarmguard_enabled": True,
            "onchain_enabled": False,
            "onchain_fallback_to_cex": False,
            "swarmguard_small_trade_bypass": False,
            "public_bot_metrics_auto_promote": False,
            "hummingbot_sidecar_live_enabled": False,
            "hummingbot_v2_leverage": 1,
            "market_making_quote_placement_enabled": False,
            "openclaw_autonomy_enabled": False,
            "coin_selection_auto_switch": False,
            "volatility_harvest_enabled": False,
        }
        for key, value in enforced.items():
            if getattr(cfg, key, value) != value:
                logging.warning("Phase-0 quarantine overriding %s=%r -> %r", key, getattr(cfg, key, None), value)
            setattr(cfg, key, value)
        return cfg

    # The ordinary coordinator is permanently research-only. Phase 6 and Phase 7
    # use dedicated operator processes with separate profiles, approvals, stores,
    # reconciliation, and environment interlocks.
    if live_requested:
        raise RuntimeError(
            "Legacy coordinator live execution is retired. Use the dedicated "
            "Phase-6 canary or Phase-7 controlled-growth operator process."
        )
    cfg.live_mode = False
    cfg.dry_run = True
    cfg.public_bot_metrics_auto_promote = False
    cfg.hummingbot_sidecar_live_enabled = False
    cfg.market_making_quote_placement_enabled = False
    return cfg


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
    cfg = apply_phase0_safety_policy(cfg)

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
    if cfg.exchange == "kraken":
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
    elif cfg.exchange == "binance":
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
    else:  # Defensive: apply_phase0_safety_policy should already reject this.
        raise RuntimeError(f"Unsupported exchange: {cfg.exchange}")

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
