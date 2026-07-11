import json
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlparse

from app.schemas import ClaimVerdict, VerdictLabel

AVERITEC_LABELS = (
    "Supported",
    "Refuted",
    "Not Enough Evidence",
    "Conflicting Evidence/Cherrypicking",
)

AVERITEC_LABEL_BY_VERISCOPE = {
    VerdictLabel.supported: "Supported",
    VerdictLabel.refuted: "Refuted",
    VerdictLabel.unverifiable: "Not Enough Evidence",
    VerdictLabel.conflicting: "Conflicting Evidence/Cherrypicking",
}


def load_references(path: str | Path) -> list[dict]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid AVeriTeC JSON: {source}") from error
    if not isinstance(payload, list):
        raise ValueError("AVeriTeC dataset must be a JSON array")
    for index, row in enumerate(payload):
        if not isinstance(row, dict) or not isinstance(row.get("claim"), str):
            raise ValueError(f"AVeriTeC row {index} has no string claim")
        if row.get("label") not in AVERITEC_LABELS:
            raise ValueError(f"AVeriTeC row {index} has unknown label: {row.get('label')!r}")
    return payload


def select_references(
    references: Sequence[dict], offset: int = 0, limit: int | None = None
) -> list[dict]:
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    end = None if limit is None else offset + limit
    return list(references[offset:end])


def fact_check_domain(reference: dict) -> str | None:
    """Return the fact-check publisher domain, including from an archive.org URL."""
    raw = reference.get("fact_checking_article")
    if not isinstance(raw, str) or not raw:
        return None
    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    if host in {"web.archive.org", "www.web.archive.org"}:
        position = parsed.path.find("/http")
        if position >= 0:
            host = urlparse(parsed.path[position + 1 :]).netloc.lower()
    return host.removeprefix("www.") or None


def prediction_from_verdict(verdict: ClaimVerdict) -> dict:
    evidence_strings = []
    evidence_details = []
    seen_clusters: set[int] = set()
    for item in verdict.evidence:
        source = item.source
        evidence_details.append(
            {
                "url": source.url,
                "title": source.title,
                "snippet": source.snippet,
                "domain": source.domain,
                "cluster_id": source.cluster_id,
                "source_type": source.source_type.value,
                "stance": item.stance.value,
                "rationale": item.rationale,
            }
        )
        if source.cluster_id in seen_clusters:
            continue
        seen_clusters.add(source.cluster_id)
        evidence_strings.append(" ".join(part for part in (source.title, source.snippet) if part))
    return {
        "claim": verdict.claim.text,
        "label": AVERITEC_LABEL_BY_VERISCOPE[verdict.label],
        "justification": verdict.explanation,
        "string_evidence": evidence_strings or ["No evidence found."],
        "veriscope": {
            "confidence": verdict.confidence.value,
            "independent_supporting": verdict.independent_supporting,
            "independent_refuting": verdict.independent_refuting,
            "evidence": evidence_details,
        },
    }


def classification_metrics(predictions: Sequence[dict], references: Sequence[dict]) -> dict:
    if len(predictions) != len(references):
        raise ValueError(
            f"prediction/reference length mismatch: {len(predictions)} != {len(references)}"
        )
    if not references:
        raise ValueError("at least one reference is required")
    confusion = {gold: {predicted: 0 for predicted in AVERITEC_LABELS} for gold in AVERITEC_LABELS}
    correct = 0
    for index, (prediction, reference) in enumerate(zip(predictions, references, strict=True)):
        predicted = prediction.get("label")
        gold = reference.get("label")
        if predicted not in AVERITEC_LABELS:
            raise ValueError(f"prediction {index} has unknown label: {predicted!r}")
        if gold not in AVERITEC_LABELS:
            raise ValueError(f"reference {index} has unknown label: {gold!r}")
        confusion[gold][predicted] += 1
        correct += predicted == gold

    per_label = {}
    for label in AVERITEC_LABELS:
        true_positive = confusion[label][label]
        false_positive = sum(confusion[gold][label] for gold in AVERITEC_LABELS if gold != label)
        false_negative = sum(confusion[label][pred] for pred in AVERITEC_LABELS if pred != label)
        support = sum(confusion[label].values())
        precision = _safe_divide(true_positive, true_positive + false_positive)
        recall = _safe_divide(true_positive, true_positive + false_negative)
        f1 = _safe_divide(2 * precision * recall, precision + recall)
        per_label[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }

    abstention_label = "Not Enough Evidence"
    abstentions = sum(confusion[gold][abstention_label] for gold in AVERITEC_LABELS)
    answered = len(references) - abstentions
    answered_correct = sum(
        confusion[label][label] for label in AVERITEC_LABELS if label != abstention_label
    )
    return {
        "examples": len(references),
        "accuracy": correct / len(references),
        "macro_f1": sum(row["f1"] for row in per_label.values()) / len(AVERITEC_LABELS),
        "abstention_rate": abstentions / len(references),
        "abstention_precision": _safe_divide(confusion[abstention_label][abstention_label], abstentions),
        "answered_accuracy": _safe_divide(answered_correct, answered),
        "per_label": per_label,
        "confusion_matrix": confusion,
    }


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0
