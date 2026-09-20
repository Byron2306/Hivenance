from strategies.relative_value_lab.queen_input_assembly import assemble_queen_inputs
from strategies.relative_value_lab.queen_input_v2 import (
    EXTENSION_CHANNELS,
    assemble_queen_inputs_v2,
    extension_channel,
)
from strategies.relative_value_lab.world_graph import WorldGraph
from strategies.relative_value_lab.world_score import CanonicalWorldScore, ScoreObservation


def frame():
    obs=ScoreObservation(
        observation_id="o",
        source_id="kraken",
        source_class="public_market",
        scope="BTC/USD",
        observed_at_ms=10,
        received_at_ms=10,
        evidence_root="sha256:"+"a"*64,
        payload={"price":100},
    )
    return CanonicalWorldScore.assemble(
        observations=(obs,),
        assembled_at_ms=10,
        freshness_window_ms=100,
    )


def test_v2_preserves_v1_and_adds_extensions():
    graph=WorldGraph(frame())
    view=graph.queen_view(created_at_ms=11)
    base=assemble_queen_inputs(
        queen_view=view,
        created_at_ms=11,
        channels={},
    )
    v2=assemble_queen_inputs_v2(
        base=base,
        created_at_ms=11,
        extensions={
            "STATISTICAL_SYNTHESIS": extension_channel(
                name="STATISTICAL_SYNTHESIS",
                state="PRESENT",
                evidence_roots=("sha256:"+"b"*64,),
                payload={"state_id":"s1"},
            )
        },
    )
    assert v2.base_v1_assembly_id==base.assembly_id
    assert v2.base_channels==len(base.channels)==17
    assert len(v2.extension_channels)==len(EXTENSION_CHANNELS)==5
    assert v2.present_extensions==("STATISTICAL_SYNTHESIS",)
    assert "REGIME_CONTEXT" in v2.absent_extensions
    assert v2.execution_eligible is False


def test_v2_extension_mask_is_explicit():
    graph=WorldGraph(frame())
    base=assemble_queen_inputs(
        queen_view=graph.queen_view(created_at_ms=11),
        created_at_ms=11,
        channels={},
    )
    v2=assemble_queen_inputs_v2(
        base=base,
        created_at_ms=11,
        extensions={
            "REGIME_CONTEXT": extension_channel(
                name="REGIME_CONTEXT",
                state="DISABLED_BY_MASK",
                reason="NO_BAYES",
            )
        },
    )
    assert v2.disabled_extensions==("REGIME_CONTEXT",)
