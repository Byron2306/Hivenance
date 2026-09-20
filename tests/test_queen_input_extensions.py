from strategies.relative_value_lab.queen_input_extensions import queen_extensions_from_cycle


class Node:
    def __init__(self):
        self.family="STATISTICAL_SYNTHESIS"
        self.evidence_roots=("sha256:"+"a"*64,)


class View:
    nodes=(Node(),)


class Cycle:
    queen_view=View()
    learning={
        "probabilistic_synthesis":{
            "state_id":"s1",
            "hierarchical_win_probability":.6,
        }
    }


def test_cycle_builds_statistical_and_context_extensions():
    extensions=queen_extensions_from_cycle(
        cycle=Cycle(),
        research_context={
            "regime":{"context_id":"r1"},
            "statistics":{"state_id":"s1"},
            "external":{"features":()},
            "calibration":{"health_id":"h1"},
        },
    )
    assert extensions["STATISTICAL_SYNTHESIS"].state=="PRESENT"
    assert extensions["STATISTICAL_SYNTHESIS"].evidence_roots==("sha256:"+"a"*64,)
    assert extensions["REGIME_CONTEXT"].payload["context_id"]=="r1"
    assert extensions["RESEARCH_CONTEXT"].state=="PRESENT"
