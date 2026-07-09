import asyncio
import html
import re

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

MAX_MESSAGE_LENGTH = 4000

dp = Dispatcher()


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
        lines.append(
            f"{VERDICT_EMOJI[verdict.label]} <b>{VERDICT_TITLES[verdict.label]}:</b> "
            f"{html.escape(verdict.claim.text)}"
        )
        lines.append(html.escape(verdict.explanation))
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
    status = await message.answer("Проверяю, это может занять пару минут…")
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout * 3) as client:
            response = await client.post(f"{settings.backend_url}/api/analyze", json=payload)
        response.raise_for_status()
        result = AnalysisResult.model_validate(response.json())
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
