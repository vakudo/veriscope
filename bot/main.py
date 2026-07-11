import asyncio
import html
import json
import re
import time

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.config import get_settings
from app.schemas import AnalysisResult, SourceCategory, SourceType, VerdictLabel

URL_PATTERN = re.compile(r"https?://\S+")

VERDICT_EMOJI = {
    VerdictLabel.supported: "✅",
    VerdictLabel.refuted: "❌",
    VerdictLabel.conflicting: "⚠️",
    VerdictLabel.unverifiable: "❓",
}

TEXTS = {
    "ru": {
        "verdicts": {
            VerdictLabel.supported: "Подтверждается",
            VerdictLabel.refuted: "Опровергается",
            VerdictLabel.conflicting: "Противоречивые данные",
            VerdictLabel.unverifiable: "Не удалось проверить",
        },
        "source_types": {
            SourceType.possible_primary: "возможный первоисточник",
            SourceType.reprint: "перепечатка",
            SourceType.opinion: "мнение",
            SourceType.unknown: "тип не определён",
        },
        "source_categories": {
            SourceCategory.official: "официальный",
            SourceCategory.academic: "научный",
            SourceCategory.fact_check: "фактчек",
            SourceCategory.social: "соцсеть",
            SourceCategory.other: "прочее",
        },
        "start": (
            "Пришлите текст новости или ссылку на статью — я разложу её на проверяемые "
            "утверждения, найду независимые источники и покажу, что подтверждается, "
            "что опровергается, а что проверить не удалось.\n\n"
            "Я не выдаю «процент правдивости»: если данных нет, я честно скажу об этом."
        ),
        "sending": "Отправляю на проверку…",
        "stage_extract": "Извлекаю текст статьи…",
        "stage_claims": "Выделяю проверяемые утверждения…",
        "stage_cached": "Беру готовый результат из кэша…",
        "stage_default": "Идёт проверка…",
        "stage_claims_done": "Найдено утверждений: {total}. Ищу источники…",
        "stage_claim_done": "Проверено {done} из {total}…",
        "flags_header": "Признаки манипуляции:",
        "benchmark": " Исторически такие вердикты верны в {percent}% случаев.",
        "error": (
            "Не получилось обработать сообщение. Проверьте ссылку или пришлите текст "
            "новости целиком."
        ),
    },
    "en": {
        "verdicts": {
            VerdictLabel.supported: "Supported",
            VerdictLabel.refuted: "Refuted",
            VerdictLabel.conflicting: "Conflicting evidence",
            VerdictLabel.unverifiable: "Could not verify",
        },
        "source_types": {
            SourceType.possible_primary: "possible primary source",
            SourceType.reprint: "reprint",
            SourceType.opinion: "opinion",
            SourceType.unknown: "type unknown",
        },
        "source_categories": {
            SourceCategory.official: "official",
            SourceCategory.academic: "academic",
            SourceCategory.fact_check: "fact-check",
            SourceCategory.social: "social",
            SourceCategory.other: "other",
        },
        "start": (
            "Send me a news text or an article link — I will split it into checkable "
            "claims, find independent sources and show what is supported, what is "
            "refuted and what could not be verified.\n\n"
            "I never output a \"truth percentage\": when there is no evidence, I say so."
        ),
        "sending": "Sending for analysis…",
        "stage_extract": "Extracting article text…",
        "stage_claims": "Extracting checkable claims…",
        "stage_cached": "Serving a cached result…",
        "stage_default": "Checking…",
        "stage_claims_done": "Claims found: {total}. Searching for sources…",
        "stage_claim_done": "Checked {done} of {total}…",
        "flags_header": "Manipulation signals:",
        "benchmark": " Historically such verdicts are correct in {percent}% of cases.",
        "error": "Could not process the message. Check the link or send the full news text.",
    },
}

MAX_MESSAGE_LENGTH = 4000
MIN_EDIT_INTERVAL = 3.0

dp = Dispatcher()


def texts_for(message: Message) -> dict:
    code = (message.from_user.language_code or "") if message.from_user else ""
    return TEXTS["ru"] if code.lower().startswith("ru") else TEXTS["en"]


def stage_text(event: dict, texts: dict) -> str:
    if event.get("stage") == "claims_done":
        return texts["stage_claims_done"].format(total=event.get("total"))
    if event.get("stage") == "claim_done":
        return texts["stage_claim_done"].format(done=event.get("done"), total=event.get("total"))
    return texts.get(f"stage_{event.get('stage')}", texts["stage_default"])


async def analyze_with_progress(
    settings, payload: dict, status: Message, texts: dict
) -> AnalysisResult:
    last_edit = 0.0
    last_text = ""
    async with httpx.AsyncClient(timeout=settings.request_timeout * 3) as client:
        async with client.stream(
            "POST", f"{settings.backend_url}/api/analyze/stream", json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                stage = event.get("stage")
                if stage == "done":
                    return AnalysisResult.model_validate(event["result"])
                if stage == "error":
                    raise RuntimeError(event.get("detail", "backend error"))
                text = stage_text(event, texts)
                now = time.monotonic()
                if text != last_text and now - last_edit >= MIN_EDIT_INTERVAL:
                    try:
                        await status.edit_text(text)
                        last_text = text
                        last_edit = now
                    except Exception:
                        pass
    raise RuntimeError("stream ended without result")


def format_result(result: AnalysisResult, texts: dict) -> str:
    lines: list[str] = []
    if result.input_title:
        lines.append(f"<b>{html.escape(result.input_title)}</b>")
    lines.append(html.escape(result.summary))
    if result.flags:
        lines.append("")
        lines.append(f"<b>{texts['flags_header']}</b>")
        for flag in result.flags:
            lines.append(f"❗ {html.escape(flag.detail)}")
    for verdict in result.claims:
        lines.append("")
        header = f"{VERDICT_EMOJI[verdict.label]} <b>{texts['verdicts'][verdict.label]}:</b> "
        header += html.escape(verdict.claim.text)
        lines.append(header)
        explanation = verdict.explanation
        if verdict.historical_accuracy is not None:
            explanation += texts["benchmark"].format(
                percent=round(verdict.historical_accuracy * 100)
            )
        lines.append(html.escape(explanation))
        for item in verdict.evidence[:3]:
            source = item.source
            meta = texts["source_types"][source.source_type]
            meta += f", {texts['source_categories'][source.source_category]}"
            if source.published_at:
                meta += f", {html.escape(source.published_at[:10])}"
            lines.append(
                f'• <a href="{html.escape(source.url)}">{html.escape(source.domain)}</a> ({meta})'
            )
            if item.evidence_quote:
                quote = item.evidence_quote[:240]
                lines.append(f"  ↳ <i>“{html.escape(quote)}”</i>")
    text = "\n".join(lines)
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH] + "…"
    return text


@dp.message(CommandStart())
async def handle_start(message: Message) -> None:
    await message.answer(texts_for(message)["start"])


@dp.message(F.text)
async def handle_text(message: Message) -> None:
    settings = get_settings()
    texts = texts_for(message)
    match = URL_PATTERN.search(message.text or "")
    payload = {"url": match.group(0)} if match else {"text": message.text}
    status = await message.answer(texts["sending"])
    try:
        result = await analyze_with_progress(settings, payload, status, texts)
        await status.edit_text(format_result(result, texts), disable_web_page_preview=True)
    except Exception:
        await status.edit_text(texts["error"])


async def main() -> None:
    settings = get_settings()
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
