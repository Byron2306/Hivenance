import json
import sqlite3

from strategies.relative_value_lab.historical_real_corpus import (
    HistoricalRealCorpus,
)


def make_db(path):
    con = sqlite3.connect(path)

    con.executescript(
        """
        CREATE TABLE
        full_organism_selector_freezes(
            freeze_id TEXT PRIMARY KEY,
            run_id TEXT,
            observed_ts REAL,
            target_ts REAL,
            symbol TEXT,
            selector_rank INTEGER,
            selector_score REAL,
            selected INTEGER,
            blind_rank INTEGER,
            blind_selected INTEGER,
            payload TEXT
        );

        CREATE TABLE
        full_organism_selector_settlements_v3(
            settlement_id TEXT PRIMARY KEY,
            freeze_id TEXT UNIQUE,
            settled_ts REAL,
            symbol TEXT,
            selected INTEGER,
            selector_rank INTEGER,
            regime TEXT,
            payload TEXT
        );

        CREATE TABLE observation_snapshots(
            snapshot_id TEXT PRIMARY KEY,
            run_id TEXT,
            observed_ts REAL,
            symbol TEXT,
            payload TEXT
        );

        CREATE TABLE hypothesis_forecasts(
            forecast_id TEXT PRIMARY KEY,
            run_id TEXT,
            observation_run_id TEXT,
            ts REAL,
            target_ts REAL,
            venue TEXT,
            symbol TEXT,
            model_id TEXT,
            hypothesis TEXT,
            horizon_seconds INTEGER,
            direction TEXT,
            entry_price REAL,
            probability_positive_net REAL,
            expected_move_bps REAL,
            expected_cost_bps REAL,
            expected_net_bps REAL,
            raw_score REAL,
            abstain INTEGER,
            reason TEXT,
            settled INTEGER,
            execution_eligible INTEGER,
            payload TEXT
        );

        CREATE TABLE hypothesis_outcomes(
            forecast_id TEXT PRIMARY KEY,
            settled_ts REAL,
            exit_price REAL,
            gross_return_bps REAL,
            directional_return_bps REAL,
            net_return_bps REAL,
            positive_net INTEGER,
            brier_score REAL,
            absolute_error_bps REAL,
            payload TEXT
        );
        """
    )

    world_hash = (
        "sha256:" + "a" * 64
    )

    freeze_payload = {
        "canonical_world_state_id":
            "ws_a",
        "canonical_world_state_hash":
            world_hash,
        "evidence_root":
            "sha256:" + "b" * 64,
        "horizon_seconds": 300,
        "predicted_roundtrip_cost_bps":
            10.0,
        "price": 100.0,
    }

    settlement_payload = {
        "canonical_world_state_id":
            "ws_a",
        "canonical_world_state_hash":
            world_hash,
        "evidence_root":
            "sha256:" + "b" * 64,
        "entry_price": 100.0,
        "exit_price": 102.0,
        "gross_absolute_move_bps":
            200.0,
        "net_opportunity_bps":
            190.0,
    }

    con.execute(
        """
        INSERT INTO
        full_organism_selector_freezes
        VALUES (
            ?,?,?,?,?,?,?,?,?,?,?
        )
        """,
        (
            "freeze-1",
            "obs-1",
            1000.0,
            1300.0,
            "BTC/USD",
            1,
            .9,
            1,
            4,
            0,
            json.dumps(
                freeze_payload
            ),
        ),
    )

    con.execute(
        """
        INSERT INTO
        full_organism_selector_settlements_v3
        VALUES (
            ?,?,?,?,?,?,?,?
        )
        """,
        (
            "settle-1",
            "freeze-1",
            1301.0,
            "BTC/USD",
            1,
            1,
            "trend",
            json.dumps(
                settlement_payload
            ),
        ),
    )

    con.execute(
        """
        INSERT INTO observation_snapshots
        VALUES (?,?,?,?,?)
        """,
        (
            "snap-1",
            "obs-1",
            999.0,
            "BTC/USD",
            "{}",
        ),
    )

    con.execute(
        """
        INSERT INTO hypothesis_forecasts
        VALUES (
            ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
        )
        """,
        (
            "forecast-1",
            "hyp-1",
            "obs-1",
            999.0,
            1299.0,
            "kraken",
            "BTC/USD",
            "m",
            "h",
            300,
            "UP",
            100.0,
            None,
            10.0,
            2.0,
            8.0,
            1.0,
            0,
            "test",
            1,
            0,
            "{}",
        ),
    )

    con.execute(
        """
        INSERT INTO hypothesis_outcomes
        VALUES (
            ?,?,?,?,?,?,?,?,?,?
        )
        """,
        (
            "forecast-1",
            1301.0,
            102.0,
            200.0,
            200.0,
            198.0,
            1,
            None,
            None,
            "{}",
        ),
    )

    con.commit()
    con.close()


def test_real_corpus_adapter_joins_freeze_settlement_and_context(
    tmp_path,
):
    db = tmp_path / "x.db"

    make_db(db)

    manifest = (
        HistoricalRealCorpus(
            db
        ).manifest()
    )

    assert manifest.case_count == 1
    assert manifest.selected_count == 1
    assert manifest.rejected_count == 0

    case = manifest.cases[0]

    assert (
        case.observation_run_id
        == "obs-1"
    )

    assert case.symbol == "BTC/USD"

    assert (
        case.world_state_id
        == "ws_a"
    )

    assert (
        case.observation_snapshot
        is not None
    )

    assert len(
        case.matching_forecasts
    ) == 1

    assert len(
        case.matching_outcomes
    ) == 1

    assert (
        case.historical_reconstruction_only
        is True
    )

    assert case.execution_eligible is False
    assert case.promotion_eligible is False


def test_manifest_never_claims_prospective_envelopes(
    tmp_path,
):
    db = tmp_path / "x.db"

    make_db(db)

    manifest = (
        HistoricalRealCorpus(
            db
        ).manifest()
    )

    assert (
        manifest.prospective_envelopes_claimed
        is False
    )

    assert (
        manifest.historical_reconstruction_only
        is True
    )
