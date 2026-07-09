from app.schemas import (
    Claim,
    ClaimVerdict,
    Confidence,
    EvidenceItem,
    ManipulationFlag,
    Stance,
    VerdictLabel,
)

VERDICT_TITLES = {
    VerdictLabel.supported: "подтверждается",
    VerdictLabel.refuted: "опровергается",
    VerdictLabel.conflicting: "источники противоречат друг другу",
    VerdictLabel.unverifiable: "не удалось проверить",
}


def build_explanation(label: VerdictLabel, supporting: int, refuting: int, total: int) -> str:
    base = (
        f"Независимых групп источников: за — {supporting}, против — {refuting} "
        f"(всего источников: {total})."
    )
    if label == VerdictLabel.supported:
        if supporting >= 2:
            tail = "Утверждение подтверждается несколькими независимыми группами источников."
        else:
            tail = (
                "Подтверждение опирается на единственную независимую группу источников, "
                "уверенность низкая."
            )
    elif label == VerdictLabel.refuted:
        if refuting >= 2:
            tail = "Утверждение опровергается несколькими независимыми группами источников."
        else:
            tail = (
                "Опровержение опирается на единственную независимую группу источников, "
                "уверенность низкая."
            )
    elif label == VerdictLabel.conflicting:
        tail = "Источники расходятся: есть и независимые подтверждения, и опровержения."
    else:
        tail = "Достаточных доказательств не найдено — честный ответ: проверить не удалось."
    return f"{base} {tail}"


def aggregate_verdict(claim: Claim, evidence: list[EvidenceItem]) -> ClaimVerdict:
    supporting = {item.source.cluster_id for item in evidence if item.stance == Stance.supports}
    refuting = {item.source.cluster_id for item in evidence if item.stance == Stance.refutes}
    if supporting and refuting:
        label = VerdictLabel.conflicting
        confidence = Confidence.low
    elif supporting:
        label = VerdictLabel.supported
        confidence = Confidence.high if len(supporting) >= 2 else Confidence.low
    elif refuting:
        label = VerdictLabel.refuted
        confidence = Confidence.high if len(refuting) >= 2 else Confidence.low
    else:
        label = VerdictLabel.unverifiable
        confidence = Confidence.low
    return ClaimVerdict(
        claim=claim,
        label=label,
        confidence=confidence,
        independent_supporting=len(supporting),
        independent_refuting=len(refuting),
        evidence=evidence,
        explanation=build_explanation(label, len(supporting), len(refuting), len(evidence)),
    )


def build_summary(verdicts: list[ClaimVerdict], flags: list[ManipulationFlag]) -> str:
    if not verdicts:
        return "Не удалось выделить проверяемые утверждения из текста."
    counts: dict[VerdictLabel, int] = {}
    for verdict in verdicts:
        counts[verdict.label] = counts.get(verdict.label, 0) + 1
    parts = [
        f"{count} — {VERDICT_TITLES[label]}"
        for label, count in counts.items()
    ]
    summary = f"Проверено утверждений: {len(verdicts)} ({'; '.join(parts)})."
    if flags:
        summary += f" Обнаружено признаков манипуляции: {len(flags)}."
    return summary
