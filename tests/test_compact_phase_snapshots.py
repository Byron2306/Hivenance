import json
from types import SimpleNamespace

from agents.coordinator import SwarmCoordinator


class PersistedSnapshotStore:
    def open_dashboard_reader(self):
        return self

    def close_dashboard_reader(self):
        return None

    def get_simulation_runs(self, limit=1):
        payload = {
            "status": "FILTERED_NO_EDGE",
            "run": {"forecasts_examined": 12, "simulations_created": 4, "completed": 3},
            "candidate_intake": {"raw_pool_size": 12, "selected_count": 4, "rejections": {}},
            "readiness": {"phase": 3, "ready_for_phase4_review": True, "reasons": []},
            "dio_gate": {"phase_scope": 3, "decision": "ALLOW", "reasons": []},
        }
        return [{"run_id": "sim-test", "payload": json.dumps(payload)}]

    def get_phase4_validation_runs(self, limit=1):
        payload = {
            "status": "HEALTHY",
            "run_id": "val-test",
            "candidate_results": [
                {"candidate_key": "candidate-a", "passes_candidate_gates": False, "reasons": ["cost_stress"]}
            ],
            "champion": {"candidate_key": "candidate-a", "robust_score": 1.0},
            "pbo": {"pbo_estimate": 0.1},
            "readiness": {"phase": 4, "ready_for_phase5_review": False, "reasons": ["no_candidate_passed"]},
        }
        return [{"run_id": "val-test", "payload": json.dumps(payload)}]

    def get_phase4_readiness(self):
        return {"phase": 4, "ready_for_phase5_review": False, "reasons": ["no_candidate_passed"]}

    def get_dio_gate_snapshot(self, phase):
        return {"phase_scope": phase, "decision": "REFUSE", "reasons": ["no_candidate_passed"]}

    def get_crystal_registry_overview(self, phase_scope):
        return {"phase_scope": phase_scope, "total": 0, "counts": {}}

    def get_inference_rung_overview(self, phase_scope):
        return {"phase_scope": phase_scope, "total": 0, "by_rung": {}, "by_outcome": {}}


def coordinator_with_persisted_store():
    coordinator = object.__new__(SwarmCoordinator)
    coordinator.agents = {"data_store": PersistedSnapshotStore()}
    coordinator.cfg = SimpleNamespace(
        phase3_execution_lab_enabled=True,
        phase3_readiness_min_completed=1,
        phase3_readiness_max_mean_2x_loss_bps=50.0,
        phase4_validation_enabled=True,
    )
    coordinator._ui_snapshot_cache = {}
    return coordinator


def test_compact_execution_snapshot_parses_persisted_payload():
    snapshot = coordinator_with_persisted_store().execution_lab_snapshot(limit=1, compact=True)

    assert snapshot["latest"]["status"] == "FILTERED_NO_EDGE"
    assert snapshot["summary"]["completed_outcomes"] == 3
    assert snapshot["summary"]["candidate_pressure"]["raw_pool_size"] == 12
    assert snapshot["dio_gate"]["decision"] == "ALLOW"


def test_compact_validation_snapshot_parses_persisted_payload():
    snapshot = coordinator_with_persisted_store().validation_lab_snapshot(limit=1, compact=True)

    assert snapshot["latest"]["run_id"] == "val-test"
    assert snapshot["summary"]["candidate_count"] == 1
    assert snapshot["summary"]["pbo_estimate"] == 0.1
    assert snapshot["summary"]["top_failure_reasons"] == [{"reason": "cost_stress", "count": 1}]
