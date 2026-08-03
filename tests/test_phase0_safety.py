from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_profiles_are_quarantined():
    for rel in [
        "config/settings.yaml", "config/settings.live.yaml", "config/conservative_state.yaml",
        "config/conservative_headless_10m.yaml", "config/live_safe_1h.yaml",
    ]:
        cfg = yaml.safe_load((ROOT / rel).read_text()) or {}
        assert cfg["phase0_quarantine"] is True
        assert cfg["auto_trade_enabled"] is False
        assert cfg["dry_run"] is True
        assert cfg["live_mode"] is False
        assert cfg["kill_switch_enabled"] is True
        assert cfg["onchain_enabled"] is False
        assert cfg["swarmguard_small_trade_bypass"] is False
        assert cfg["public_bot_metrics_auto_promote"] is False
        assert cfg["volatility_harvest_enabled"] is False
        assert cfg["hummingbot_v2_leverage"] == 1
        assert cfg["ui_host"] == "127.0.0.1"


def test_no_source_controlled_secret_files():
    assert not (ROOT / "config/api_keys.json").exists()
    assert not (ROOT / "config/api_keys.json.backup").exists()
    assert not (ROOT / "config/encryption.key").exists()


def test_strategy_scaffold_cannot_execute():
    from strategies.volatility_breakout.feature_engine import Phase0FeatureEngine
    from strategies.volatility_breakout.signal_model import ObservationOnlySignalModel

    features = Phase0FeatureEngine().unavailable("ETH/USD", 1)
    forecast = ObservationOnlySignalModel().forecast(features)
    assert forecast.abstain is True
    assert forecast.direction == "ABSTAIN"


def test_docker_socket_is_not_mounted():
    compose = (ROOT / "docker/docker-compose.yml").read_text()
    assert "/var/run/docker.sock" not in compose


def test_no_legacy_live_safety_bypass_in_main():
    source = (ROOT / "main.py").read_text()
    assert "disabling dry_run and kill_switch" not in source
    assert "cfg.kill_switch_enabled = False" not in source
