import re

from app.i18n import strings_for
from app.schemas import ManipulationFlag

EMOTIONAL_WORDS = {
    "шок",
    "шокирующий",
    "шокирующая",
    "шокирующее",
    "сенсация",
    "сенсационный",
    "скандал",
    "скандальный",
    "ужас",
    "ужасный",
    "ужасающий",
    "кошмар",
    "кошмарный",
    "катастрофа",
    "катастрофический",
    "паника",
    "немыслимый",
    "немыслимо",
    "невероятный",
    "невероятно",
    "возмутительный",
    "возмутительно",
    "срочно",
    "тайный",
    "тайна",
    "разоблачение",
    "shocking",
    "sensational",
    "scandal",
    "scandalous",
    "outrageous",
    "terrifying",
    "horrifying",
    "unbelievable",
    "incredible",
    "panic",
    "urgent",
    "secret",
    "exposed",
    "bombshell",
}

CLICKBAIT_PATTERNS = [
    re.compile(r"вы не поверите", re.IGNORECASE),
    re.compile(r"you won'?t believe", re.IGNORECASE),
    re.compile(r"это изменит", re.IGNORECASE),
    re.compile(r"узнайте", re.IGNORECASE),
    re.compile(r"шок", re.IGNORECASE),
    re.compile(r"сенсаци", re.IGNORECASE),
    re.compile(r"^\d+\s+(причин|способ|фактов|things|reasons|ways)", re.IGNORECASE),
    re.compile(r"!{2,}"),
    re.compile(r"\b[А-ЯЁA-Z]{4,}\b"),
]

ANONYMOUS_PATTERNS = [
    re.compile(r"по (данным|словам|информации) (наших |анонимных |неназванных )?источник", re.IGNORECASE),
    re.compile(r"анонимн\w+ источник", re.IGNORECASE),
    re.compile(r"источник\w*, (пожелавш|близк)", re.IGNORECASE),
    re.compile(r"according to (anonymous |unnamed )?sources", re.IGNORECASE),
    re.compile(r"sources (say|said|told|claim)", re.IGNORECASE),
    re.compile(r"people familiar with the matter", re.IGNORECASE),
]

DATE_PATTERN = re.compile(
    r"\d{1,2}[./]\d{1,2}[./]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{4}\s*(год|г\.)"
    r"|\b(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\b"
    r"|\b(january|february|march|april|may|june|july|august|september|october|november|december)\b"
    r"|\b(вчера|сегодня|накануне|yesterday|today)\b",
    re.IGNORECASE,
)

NAME_PATTERN = re.compile(r"\b[А-ЯЁA-Z][а-яёa-z]+\s+[А-ЯЁA-Z][а-яёa-z]+\b")

WORD_PATTERN = re.compile(r"[а-яёa-z]+")


def detect_manipulation(
    title: str | None, text: str, lang: str = "ru"
) -> list[ManipulationFlag]:
    strings = strings_for(lang)
    flags: list[ManipulationFlag] = []
    words = WORD_PATTERN.findall(text.lower())
    emotional_hits = sorted({word for word in words if word in EMOTIONAL_WORDS})
    if len(emotional_hits) >= 2:
        flags.append(
            ManipulationFlag(
                kind="emotional_language",
                detail=strings["flag_emotional"].format(words=", ".join(emotional_hits[:8])),
            )
        )
    if any(pattern.search(text) for pattern in ANONYMOUS_PATTERNS):
        flags.append(
            ManipulationFlag(kind="anonymous_sources", detail=strings["flag_anonymous"])
        )
    if title and any(pattern.search(title) for pattern in CLICKBAIT_PATTERNS):
        flags.append(
            ManipulationFlag(kind="clickbait_title", detail=strings["flag_clickbait"])
        )
    if not DATE_PATTERN.search(text) and not NAME_PATTERN.search(text):
        flags.append(
            ManipulationFlag(kind="missing_attribution", detail=strings["flag_missing"])
        )
    return flags
