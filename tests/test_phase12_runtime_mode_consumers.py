from types import SimpleNamespace

from strategies.volatility_breakout.hypothesis_competition import HypothesisCompetition


def cfg(**modes):
    return SimpleNamespace(
        exchange="kraken",
        phase2_worker_signal_federation_enabled=True,
        phase2_worker_coalition_enabled=True,
        medium_trend_phase2_model_enabled=False,
        derivatives_trend_phase2_model_enabled=False,
        phase12_organ_runtime_modes=modes,
    )


def test_worker_modes_remove_worker_influence_from_active_model_roster():
    comp=HypothesisCompetition(cfg(
        strategy_workers="SHADOW",
        worker_coalition="QUARANTINED",
        learning_memory="ACTIVE",
        statistics_bee="ACTIVE",
    ))
    assert comp.phase12_worker_influence_enabled is False
    assert comp.phase12_worker_coalition_influence_enabled is False
    assert comp.phase12_learning_influence_enabled is True
    assert comp.phase12_statistics_influence_enabled is True


def test_learning_and_statistics_modes_are_independently_controllable():
    comp=HypothesisCompetition(cfg(
        strategy_workers="ACTIVE",
        worker_coalition="ACTIVE",
        learning_memory="SHADOW",
        statistics_bee="ADVISORY",
    ))
    assert comp.phase12_worker_influence_enabled is True
    assert comp.phase12_worker_coalition_influence_enabled is True
    assert comp.phase12_learning_influence_enabled is False
    assert comp.phase12_statistics_influence_enabled is True
