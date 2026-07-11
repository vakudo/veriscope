import re

CYRILLIC_LETTERS = re.compile(r"[а-яё]", re.IGNORECASE)
LATIN_LETTERS = re.compile(r"[a-z]", re.IGNORECASE)


def detect_language(text: str) -> str:
    cyrillic = len(CYRILLIC_LETTERS.findall(text))
    latin = len(LATIN_LETTERS.findall(text))
    return "ru" if cyrillic >= latin else "en"


STRINGS = {
    "ru": {
        "verdict_supported": "подтверждается",
        "verdict_refuted": "опровергается",
        "verdict_conflicting": "источники противоречат друг другу",
        "verdict_unverifiable": "не удалось проверить",
        "explanation_base": (
            "Независимых групп источников: за — {supporting}, против — {refuting} "
            "(всего источников: {total})."
        ),
        "supported_contested": (
            "Перевес независимых источников на стороне подтверждения, "
            "но есть и опровергающие — уверенность низкая."
        ),
        "supported_multi": "Утверждение подтверждается несколькими независимыми группами источников.",
        "supported_single": (
            "Подтверждение опирается на единственную независимую группу источников, "
            "уверенность низкая."
        ),
        "refuted_contested": (
            "Перевес независимых источников на стороне опровержения, "
            "но есть и подтверждающие — уверенность низкая."
        ),
        "refuted_multi": "Утверждение опровергается несколькими независимыми группами источников.",
        "refuted_single": (
            "Опровержение опирается на единственную независимую группу источников, "
            "уверенность низкая."
        ),
        "conflicting_tail": "Источники расходятся: есть и независимые подтверждения, и опровержения.",
        "unverifiable_tail": (
            "Достаточных доказательств не найдено — честный ответ: проверить не удалось."
        ),
        "summary": "Проверено утверждений: {count} ({parts}).",
        "summary_flags": " Обнаружено признаков манипуляции: {count}.",
        "summary_empty": "Не удалось выделить проверяемые утверждения из текста.",
        "inherited": "Перепечатка того же материала — позиция унаследована от группы источников",
        "unstable": "Позиция источника неустойчива при повторной проверке и не засчитана",
        "flag_emotional": "Эмоционально окрашенная лексика: {words}",
        "flag_anonymous": "Текст ссылается на анонимные или неназванные источники",
        "flag_clickbait": "Заголовок содержит кликбейт-приёмы",
        "flag_missing": (
            "В тексте нет ни дат, ни имён — утверждения сложно привязать к проверяемым фактам"
        ),
    },
    "en": {
        "verdict_supported": "supported",
        "verdict_refuted": "refuted",
        "verdict_conflicting": "sources contradict each other",
        "verdict_unverifiable": "could not be verified",
        "explanation_base": (
            "Independent source groups: for — {supporting}, against — {refuting} "
            "(total sources: {total})."
        ),
        "supported_contested": (
            "Independent sources lean towards confirmation, "
            "but some refute the claim — confidence is low."
        ),
        "supported_multi": "The claim is confirmed by several independent source groups.",
        "supported_single": (
            "The confirmation rests on a single independent source group, confidence is low."
        ),
        "refuted_contested": (
            "Independent sources lean towards refutation, "
            "but some confirm the claim — confidence is low."
        ),
        "refuted_multi": "The claim is refuted by several independent source groups.",
        "refuted_single": (
            "The refutation rests on a single independent source group, confidence is low."
        ),
        "conflicting_tail": (
            "Sources disagree: there are both independent confirmations and refutations."
        ),
        "unverifiable_tail": (
            "Not enough evidence was found — the honest answer is: could not verify."
        ),
        "summary": "Claims checked: {count} ({parts}).",
        "summary_flags": " Manipulation signals detected: {count}.",
        "summary_empty": "No checkable claims could be extracted from the text.",
        "inherited": "Reprint of the same material — stance inherited from the source group",
        "unstable": "The source stance was unstable on re-check and was not counted",
        "flag_emotional": "Emotionally charged wording: {words}",
        "flag_anonymous": "The text cites anonymous or unnamed sources",
        "flag_clickbait": "The headline uses clickbait techniques",
        "flag_missing": (
            "The text contains neither dates nor names — its statements are hard to pin "
            "to checkable facts"
        ),
    },
}


def strings_for(lang: str) -> dict[str, str]:
    return STRINGS.get(lang, STRINGS["en"])
