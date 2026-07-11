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
from app.schemas import AnalysisResult, SourceType, VerdictLabel

URL_PATTERN = re.compile(r"https?://\S+")

VERDICT_EMOJI = {
    VerdictLabel.supported: "✅",
    VerdictLabel.refuted: "❌",
    VerdictLabel.conflicting: "⚠️",
    VerdictLabel.unverifiable: "❓",
}

VERDICT_TITLES = {
    VerdictLabel.supported: "Подтверждается",
    VerdictLabel.refuted: "Опровергается",
    VerdictLabel.conflicting: "Противоречивые данные",
    VerdictLabel.unverifiable: "Не удалось проверить",
}

SOURCE_TYPE_TITLES = {
    SourceType.possible_primary: "возможный первоисточник",
    SourceType.reprint: "перепечатка",
    SourceType.opinion: "мнение",
    SourceType.unknown: "тип не определён",
}

START_TEXT = (
    "Пришлите текст новости или ссылку на статью — я разложу её на проверяемые "
    "утверждения, найду независимые источники и покажу, что подтверждается, "
    "что опровергается, а что проверить не удалось.\n\n"
    "Я не выдаю «процент правдивости»: если данных нет, я честно скажу об этом."
)

STAGE_TEXTS = {
    "extract": "Извлекаю текст статьи…",
    "claims": "Выделяю проверяемые утверждения…",
    "cached": "Беру готовый результат из кэша…",
}

MAX_MESSAGE_LENGTH = 4000
MIN_EDIT_INTERVAL = 3.0

dp = Dispatcher()


def stage_text(event: dict) -> str:
    if event.get("stage") == "claims_done":
        return f"Найдено утверждений: {event.get('total')}. Ищу источники…"
    if event.get("stage") == "claim_done":
        return f"Проверено {event.get('done')} из {event.get('total')}…"
    return STAGE_TEXTS.get(event.get("stage"), "Идёт проверка…")


async def analyze_with_progress(settings, payload: dict, status: Message) -> AnalysisResult:
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
                text = stage_text(event)
                now = time.monotonic()
                if text != last_text and now - last_edit >= MIN_EDIT_INTERVAL:
                    try:
                        await status.edit_text(text)
                        last_text = text
                        last_edit = now
                    except Exception:
                        pass
    raise RuntimeError("stream ended without result")


def format_result(result: AnalysisResult) -> str:
    lines: list[str] = []
    if result.input_title:
        lines.append(f"<b>{html.escape(result.input_title)}</b>")
    lines.append(html.escape(result.summary))
    if result.flags:
        lines.append("")
        lines.append("<b>Признаки манипуляции:</b>")
        for flag in result.flags:
            lines.append(f"❗ {html.escape(flag.detail)}")
    for verdict in result.claims:
        lines.append("")
        header = f"{VERDICT_EMOJI[verdict.label]} <b>{VERDICT_TITLES[verdict.label]}:</b> "
        header += html.escape(verdict.claim.text)
        lines.append(header)
        explanation = verdict.explanation
        if verdict.historical_accuracy is not None:
            explanation += (
                f" Исторически такие вердикты верны в "
                f"{round(verdict.historical_accuracy * 100)}% случаев."
            )
        lines.append(html.escape(explanation))
        for item in verdict.evidence[:3]:
            source = item.source
            meta = SOURCE_TYPE_TITLES[source.source_type]
            if source.published_at:
                meta += f", {html.escape(source.published_at[:10])}"
            lines.append(
                f'• <a href="{html.escape(source.url)}">{html.escape(source.domain)}</a> ({meta})'
            )
    text = "\n".join(lines)
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH] + "…"
    return text


@dp.message(CommandStart())
async def handle_start(message: Message) -> None:
    await message.answer(START_TEXT)


@dp.message(F.text)
async def handle_text(message: Message) -> None:
    settings = get_settings()
    match = URL_PATTERN.search(message.text or "")
    payload = {"url": match.group(0)} if match else {"text": message.text}
    status = await message.answer("Отправляю на проверку…")
    try:
        result = await analyze_with_progress(settings, payload, status)
        await status.edit_text(format_result(result), disable_web_page_preview=True)
    except Exception:
        await status.edit_text(
            "Не получилось обработать сообщение. Проверьте ссылку или пришлите текст новости целиком."
        )


async def main() -> None:
    settings = get_settings()
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
