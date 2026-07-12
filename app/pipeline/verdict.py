from collections import Counter

from app.i18n import strings_for
from app.schemas import (
    Claim,
    ClaimVerdict,
    Confidence,
    EvidenceItem,
    ManipulationFlag,
    Stance,
    VerdictLabel,
)


def build_explanation(
    label: VerdictLabel, supporting: int, refuting: int, total: int, lang: str = "ru"
) -> str:
    strings = strings_for(lang)
    base = strings["explanation_base"].format(
        supporting=supporting, refuting=refuting, total=total
    )
    if label == VerdictLabel.supported:
        if refuting > 0:
            tail = strings["supported_contested"]
        elif supporting >= 2:
            tail = strings["supported_multi"]
        else:
            tail = strings["supported_single"]
    elif label == VerdictLabel.refuted:
        if supporting > 0:
            tail = strings["refuted_contested"]
        elif refuting >= 2:
            tail = strings["refuted_multi"]
        else:
            tail = strings["refuted_single"]
    elif label == VerdictLabel.conflicting:
        tail = strings["conflicting_tail"]
    else:
        tail = strings["unverifiable_tail"]
    return f"{base} {tail}"


def aggregate_verdict(
    claim: Claim, evidence: list[EvidenceItem], lang: str = "ru"
) -> ClaimVerdict:
    supporting = {item.source.cluster_id for item in evidence if item.stance == Stance.supports}
    refuting = {item.source.cluster_id for item in evidence if item.stance == Stance.refutes}
    if supporting and refuting:
        if len(supporting) > len(refuting):
            label = VerdictLabel.supported
            confidence = Confidence.low
        elif len(refuting) > len(supporting):
            label = VerdictLabel.refuted
            confidence = Confidence.low
        elif len(refuting) == 1:
            # calibration: single-group conflicts were wrong 8/8 times, so one
            # dissenting group is treated as noise, not a conflict
            label = VerdictLabel.supported
            confidence = Confidence.low
        else:
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
        explanation=build_explanation(label, len(supporting), len(refuting), len(evidence), lang),
    )


def build_summary(
    verdicts: list[ClaimVerdict], flags: list[ManipulationFlag], lang: str = "ru"
) -> str:
    strings = strings_for(lang)
    if not verdicts:
        return strings["summary_empty"]
    counts = Counter(verdict.label for verdict in verdicts)
    parts = [
        f"{count} — {strings[f'verdict_{label.value}']}"
        for label, count in counts.items()
    ]
    summary = strings["summary"].format(count=len(verdicts), parts="; ".join(parts))
    if flags:
        summary += strings["summary_flags"].format(count=len(flags))
    return summary
