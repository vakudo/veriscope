from app.pipeline.verdict import aggregate_verdict, build_summary
from app.schemas import (
    Claim,
    Confidence,
    EvidenceItem,
    EvidenceSource,
    ManipulationFlag,
    Stance,
    VerdictLabel,
)

CLAIM = Claim(id=0, text="утверждение")


def make_item(cluster_id: int, stance: Stance) -> EvidenceItem:
    source = EvidenceSource(
        url=f"https://s{cluster_id}.example/1", domain=f"s{cluster_id}.example", cluster_id=cluster_id
    )
    return EvidenceItem(source=source, stance=stance)


def test_two_independent_groups_support_high_confidence():
    verdict = aggregate_verdict(CLAIM, [make_item(0, Stance.supports), make_item(1, Stance.supports)])
    assert verdict.label == VerdictLabel.supported
    assert verdict.confidence == Confidence.high
    assert verdict.independent_supporting == 2


def test_single_cluster_reprints_count_once():
    verdict = aggregate_verdict(CLAIM, [make_item(0, Stance.supports), make_item(0, Stance.supports)])
    assert verdict.label == VerdictLabel.supported
    assert verdict.confidence == Confidence.low
    assert verdict.independent_supporting == 1


def test_conflicting_evidence():
    verdict = aggregate_verdict(CLAIM, [make_item(0, Stance.supports), make_item(1, Stance.refutes)])
    assert verdict.label == VerdictLabel.conflicting
    assert verdict.confidence == Confidence.low


def test_refuted_by_independent_groups():
    verdict = aggregate_verdict(CLAIM, [make_item(0, Stance.refutes), make_item(1, Stance.refutes)])
    assert verdict.label == VerdictLabel.refuted
    assert verdict.confidence == Confidence.high


def test_no_evidence_is_unverifiable():
    verdict = aggregate_verdict(CLAIM, [])
    assert verdict.label == VerdictLabel.unverifiable
    assert "не удалось" in verdict.explanation


def test_only_nei_is_unverifiable():
    verdict = aggregate_verdict(CLAIM, [make_item(0, Stance.not_enough_info)])
    assert verdict.label == VerdictLabel.unverifiable


def test_summary_mentions_counts_and_flags():
    verdicts = [
        aggregate_verdict(CLAIM, [make_item(0, Stance.supports), make_item(1, Stance.supports)]),
        aggregate_verdict(CLAIM, []),
    ]
    flags = [ManipulationFlag(kind="clickbait_title", detail="кликбейт")]
    summary = build_summary(verdicts, flags)
    assert "Проверено утверждений: 2" in summary
    assert "манипуляции: 1" in summary


def test_summary_without_claims():
    assert "Не удалось выделить" in build_summary([], [])
