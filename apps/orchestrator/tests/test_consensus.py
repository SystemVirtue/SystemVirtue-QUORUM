from app.consensus.engine import consensus
from app.core.schemas import MemberOutput


def test_consensus_ranks_candidates():
    outputs = [
        MemberOutput(label="Alpha", role="tester", model_id="a", output_text="Use tests. The code should handle empty input.", revised_text="Use tests. The code should handle empty input.", confidence=80),
        MemberOutput(label="Beta", role="critic", model_id="b", output_text="Use tests. The code should handle empty input.", revised_text="Use tests. The code should handle empty input.", confidence=80),
        MemberOutput(label="Gamma", role="architect", model_id="c", output_text="Completely unrelated.", revised_text="Completely unrelated.", confidence=20),
    ]
    report = consensus("prompt", outputs, "balanced")
    assert report.candidate_ranking[0]["label"] in {"Alpha", "Beta"}
    assert report.overall_consensus_score > 0
