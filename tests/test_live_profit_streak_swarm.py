from pathlib import Path

from scripts import run_live_profit_streak_swarm as lab


def test_live_streak_lab_is_public_paper_only():
    assert lab.AUTHORITY == "PUBLIC_MARKET_PAPER_ONLY_NO_PRIVATE_KEYS_NO_ORDERS"
    mutation_ids = {item["id"] for item in lab.MUTATIONS}
    assert "random30" in mutation_ids
    assert "majority5" in mutation_ids
    assert "inferred_regime" in mutation_ids
    assert "no_vol_worker" in mutation_ids


def test_live_streak_lab_source_contains_no_private_order_calls():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "run_live_profit_streak_swarm.py").read_text()
    forbidden = (
        ".create_order(",
        ".create_market_order(",
        ".create_limit_order(",
        ".fetch_balance(",
        "HIVENANCE_KRAKEN_API_KEY",
        "HIVENANCE_KRAKEN_API_SECRET",
    )
    for token in forbidden:
        assert token not in source


def test_termux_launcher_keeps_live_submission_out_of_scope():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "launch_termux_profit_streak_lab.sh").read_text()
    assert "run_live_profit_streak_swarm.py" in source
    assert "phase6" not in source.lower()
    assert "live_submission" not in source.lower()
