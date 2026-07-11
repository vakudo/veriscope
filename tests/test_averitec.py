import json

import pytest

from app.evaluation.averitec import (
    AVERITEC_LABELS,
    claim_date,
    classification_metrics,
    fact_check_domain,
    load_references,
    prediction_from_verdict,
    select_references,
    stratified_indices,
)
from app.schemas import (
    Claim,
    ClaimVerdict,
    Confidence,
    EvidenceItem,
    EvidenceSource,
    SourceType,
    Stance,
    VerdictLabel,
)


def reference(claim: str, label: str) -> dict:
    return {"claim": claim, "label": label}


def test_load_and_select_references(tmp_path):
    path = tmp_path / "dev.json"
    rows = [reference(f"claim {index}", label) for index, label in enumerate(AVERITEC_LABELS)]
    path.write_text(json.dumps(rows), encoding="utf-8")

    assert select_references(load_references(path), offset=1, limit=2) == rows[1:3]


def test_load_references_rejects_unknown_label(tmp_path):
    path = tmp_path / "dev.json"
    path.write_text(json.dumps([reference("claim", "Maybe")]), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown label"):
        load_references(path)


def test_stratified_indices_are_balanced_deterministic_and_sorted():
    rows = [
        reference(f"{label} {index}", label)
        for label in AVERITEC_LABELS
        for index in range(5)
    ]

    first = stratified_indices(rows, samples_per_label=2, seed=7)
    second = stratified_indices(rows, samples_per_label=2, seed=7)

    assert first == second
    assert first == sorted(first)
    assert len(first) == 8
    assert {label: sum(rows[index]["label"] == label for index in first) for label in AVERITEC_LABELS} == {
        label: 2 for label in AVERITEC_LABELS
    }


def test_stratified_indices_reject_insufficient_label_bucket():
    rows = [reference(label, label) for label in AVERITEC_LABELS]

    with pytest.raises(ValueError, match="not enough"):
        stratified_indices(rows, samples_per_label=2)


def test_fact_check_domain_unwraps_archive_url():
    row = {
        "fact_checking_article": (
            "https://web.archive.org/web/20201103001419/"
            "https://www.example.com/fact-check/story"
        )
    }

    assert fact_check_domain(row) == "example.com"


def test_claim_date_parses_averitec_format():
    assert claim_date({"claim_date": "31-10-2020"}).isoformat() == "2020-10-31"
    assert claim_date({}) is None


def test_prediction_contains_official_label_and_one_string_per_cluster():
    first = EvidenceSource(
        url="https://one.example/story",
        domain="one.example",
        title="First",
        snippet="Evidence",
        published_at="2020-10-30",
        source_type=SourceType.possible_primary,
        cluster_id=0,
    )
    reprint = EvidenceSource(
        url="https://two.example/reprint",
        domain="two.example",
        title="Reprint",
        snippet="Same evidence",
        source_type=SourceType.reprint,
        cluster_id=0,
    )
    verdict = ClaimVerdict(
        claim=Claim(id=3, text="A normalized claim"),
        label=VerdictLabel.supported,
        confidence=Confidence.low,
        independent_supporting=1,
        independent_refuting=0,
        evidence=[
            EvidenceItem(source=first, stance=Stance.supports, rationale="Supports"),
            EvidenceItem(source=reprint, stance=Stance.supports, rationale="Inherited"),
        ],
        explanation="One independent group supports the claim.",
    )

    prediction = prediction_from_verdict(verdict)

    assert prediction["label"] == "Supported"
    assert prediction["string_evidence"] == ["First Evidence"]
    assert len(prediction["veriscope"]["evidence"]) == 2
    assert prediction["veriscope"]["evidence"][0]["published_at"] == "2020-10-30"


def test_prediction_has_scorable_placeholder_when_no_evidence_exists():
    verdict = ClaimVerdict(
        claim=Claim(id=0, text="An unverifiable claim"),
        label=VerdictLabel.unverifiable,
        confidence=Confidence.low,
        independent_supporting=0,
        independent_refuting=0,
        evidence=[],
        explanation="No evidence.",
    )

    assert prediction_from_verdict(verdict)["string_evidence"] == ["No evidence found."]


def test_classification_metrics_include_abstention_and_confusion():
    references = [reference(str(index), label) for index, label in enumerate(AVERITEC_LABELS)]
    predictions = [
        {"label": "Supported"},
        {"label": "Refuted"},
        {"label": "Not Enough Evidence"},
        {"label": "Not Enough Evidence"},
    ]

    metrics = classification_metrics(predictions, references)

    assert metrics["accuracy"] == 0.75
    assert metrics["abstention_rate"] == 0.5
    assert metrics["abstention_precision"] == 0.5
    assert metrics["answered_accuracy"] == 1.0
    assert metrics["confusion_matrix"]["Conflicting Evidence/Cherrypicking"][
        "Not Enough Evidence"
    ] == 1


def test_classification_metrics_reject_length_mismatch():
    with pytest.raises(ValueError, match="length mismatch"):
        classification_metrics([], [reference("claim", "Supported")])
