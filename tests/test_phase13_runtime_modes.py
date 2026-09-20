from strategies.relative_value_lab.phase13_runtime_modes import build_phase13_mode_snapshot


def test_phase13_frozen_full_hive_does_not_inherit_adaptive_demotions():
    snap=build_phase13_mode_snapshot(
        adaptive_control={
            "statistics_bee":{"mode":"SHADOW"},
            "strategy_workers":{"mode":"QUARANTINED"},
            "learning_memory":{"mode":"DORMANT"},
            "worker_coalition":{"mode":"SHADOW"},
        }
    )
    assert snap.frozen_modes["statistics_bee"]=="ACTIVE"
    assert snap.frozen_modes["strategy_workers"]=="ACTIVE"
    assert snap.adaptive_modes["statistics_bee"]=="SHADOW"
    assert snap.adaptive_modes["strategy_workers"]=="QUARANTINED"
    assert snap.frozen_modes_mutable is False
    assert snap.adaptive_modes_mutable is True
