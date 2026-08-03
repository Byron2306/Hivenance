"""
Lightweight entry point for launching the Flask dashboard without running the
full trading loop. Useful for editing configuration and API keys when the rest
of the system isn't running.
"""

import logging
import os
import threading
import time

from main import apply_phase0_safety_policy, load_config
from agents.coordinator import SwarmCoordinator


def launch_ui_only() -> None:
    """Start the UI Agent and keep the process alive."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    cfg = apply_phase0_safety_policy(load_config())

    # UI-only is observation-only. Keep safety and durable-state agents enabled;
    # disable only expensive performance work.
    # even when trading dependencies (Binance client, database, encryption key)
    # aren't available.
    cfg.ui_enabled = True
    cfg.dry_run = True
    cfg.live_mode = False
    cfg.kill_switch_enabled = True
    cfg.network_enabled = os.getenv("HIVENANCE_ENABLE_REDIS", "0") == "1"
    cfg.data_store_enabled = True
    cfg.performance_enabled = False
    cfg.security_enabled = True
    # Prevent wallet monitor from attempting RPC connections in UI-only mode
    cfg.web3_rpc_url = None
    cfg.watch_address = None
    os.environ.setdefault("HIVENANCE_SKIP_DB_QUICK_CHECK", "1")

    coordinator = SwarmCoordinator(cfg)

    # Initialize a public client so market data (and wallet monitor) can run in UI-only mode.
    client = None
    try:
        if cfg.exchange == "kraken":
            import ccxt
            client = ccxt.kraken({"enableRateLimit": True})
        elif cfg.exchange == "binance":
            from binance.client import Client
            client = Client(cfg.binance_api_key, cfg.binance_api_secret)
            if cfg.binance_testnet:
                client.API_URL = "https://testnet.binance.vision/api"
    except Exception as e:
        logging.warning(f"UI-only exchange client init failed: {e}")

    if cfg.network_enabled:
        try:
            coordinator.enable_network(
                host=cfg.redis_host,
                port=cfg.redis_port,
                db=cfg.redis_db,
                password=cfg.redis_password,
            )
            logging.info("Network (Redis) enabled for UI backend.")
        except Exception as e:
            logging.warning(f"UI backend Redis enable failed: {e}")

    coordinator.start_background_tasks()
    coordinator.share_data("system_mode", {"mode": "ui_only_research_bootstrap", "execution_wired": False})

    if os.getenv("HIVENANCE_UI_BOOTSTRAP_RESEARCH", "0") == "1":
        def _initialize_research_stack() -> None:
            if not client:
                logging.warning("UI-only research bootstrap skipped: no public client available.")
                return
            try:
                coordinator.initialize(client)
                hypothesis = coordinator.agents.get("hypothesis_swarm")
                observer = coordinator.agents.get("observation_swarm")
                if hypothesis and bool(getattr(cfg, "phase2_hypotheses_enabled", True)) and hasattr(hypothesis, "start"):
                    hypothesis.start()
                elif observer and hasattr(observer, "start"):
                    observer.start()
                logging.info("UI-only research bootstrap completed.")
            except Exception as e:
                logging.exception(f"UI-only research bootstrap failed: {e}")

        threading.Thread(
            target=_initialize_research_stack,
            name="hivenance-ui-only-bootstrap",
            daemon=True,
        ).start()
    else:
        logging.info("UI-only research bootstrap disabled for fast local dashboard startup.")

    logging.info("UI available at http://%s:%s", cfg.ui_host, cfg.ui_port)
    logging.info("Press Ctrl+C to stop the UI.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        coordinator.running = False
        if coordinator.agents.get("ui"):
            coordinator.agents["ui"].stop()
        logging.info("UI stopped.")


if __name__ == "__main__":
    launch_ui_only()
