from __future__ import annotations

import pytest

from strategies.volatility_breakout.hypothesis_registry import (
    is_out_of_sample,
    load_all_hypotheses,
    load_hypothesis,
    register_hypothesis,
)


def test_register_hypothesis_writes_immutable_record(tmp_path):
    record = register_hypothesis(
        registry_dir=tmp_path,
        hypothesis_id="mean_reversion_v1",
        title="Overnight mean reversion",
        description="Test hypothesis for registry scaffold.",
        symbols=("ETH/USD",),
        directions=("long", "short"),
        entry_rule_summary="enter on 2-sigma deviation from 24h VWAP",
        exit_rule_summary="exit at VWAP touch or 4h timeout",
        predicted_edge_bps=15.0,
        predicted_edge_rationale="overnight liquidity gaps revert historically",
        registered_by="test-suite",
        now_fn=lambda: 1000.0,
    )
    assert record.hypothesis_id == "mean_reversion_v1"
    assert record.registered_at == 1000.0
    assert len(record.spec_sha256) == 64

    loaded = load_hypothesis(tmp_path, "mean_reversion_v1")
    assert loaded == record


def test_register_hypothesis_refuses_overwrite(tmp_path):
    kwargs = dict(
        registry_dir=tmp_path,
        hypothesis_id="dup_v1",
        title="t",
        description="d",
        symbols=("ETH/USD",),
        directions=("long",),
        entry_rule_summary="e",
        exit_rule_summary="x",
        predicted_edge_bps=1.0,
        predicted_edge_rationale="r",
        registered_by="test",
    )
    register_hypothesis(**kwargs)
    with pytest.raises(FileExistsError):
        register_hypothesis(**kwargs)


def test_is_out_of_sample_boundary(tmp_path):
    record = register_hypothesis(
        registry_dir=tmp_path,
        hypothesis_id="boundary_v1",
        title="t",
        description="d",
        symbols=("ETH/USD",),
        directions=("long",),
        entry_rule_summary="e",
        exit_rule_summary="x",
        predicted_edge_bps=1.0,
        predicted_edge_rationale="r",
        registered_by="test",
        now_fn=lambda: 500.0,
    )
    assert is_out_of_sample(record, 500.0001) is True
    assert is_out_of_sample(record, 500.0) is False
    assert is_out_of_sample(record, 499.0) is False


def test_load_all_hypotheses(tmp_path):
    for hid in ("a_v1", "b_v1"):
        register_hypothesis(
            registry_dir=tmp_path,
            hypothesis_id=hid,
            title="t",
            description="d",
            symbols=("ETH/USD",),
            directions=("long",),
            entry_rule_summary="e",
            exit_rule_summary="x",
            predicted_edge_bps=1.0,
            predicted_edge_rationale="r",
            registered_by="test",
        )
    loaded = load_all_hypotheses(tmp_path)
    assert {h.hypothesis_id for h in loaded} == {"a_v1", "b_v1"}
