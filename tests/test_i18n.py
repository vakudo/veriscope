from app.i18n import STRINGS, detect_language
from app.pipeline.manipulation import detect_manipulation
from app.pipeline.runner import FactCheckPipeline
from app.pipeline.search import SearchResult
from app.schemas import VerdictLabel
from tests.conftest import FakeLLM, FakeSearch


def test_detect_language():
    assert detect_language("Компания объявила о сделке") == "ru"
    assert detect_language("The company announced a deal") == "en"
    assert detect_language("Компания Alpha купила Beta Corp") == "ru"


def test_string_tables_have_same_keys():
    assert set(STRINGS["ru"]) == set(STRINGS["en"])


def test_manipulation_flags_localized():
    text = "somewhere something happened and everyone discusses consequences quietly"
    flags = detect_manipulation(None, text, "en")
    assert any("neither dates nor names" in flag.detail for flag in flags)


async def test_english_article_gets_english_verdicts(settings):
    llm = FakeLLM(
        claims=["Company Alpha acquired company Beta"],
        vectors={"ALPHA": [1.0, 0.0, 0.0]},
    )
    search = FakeSearch(
        default=[
            SearchResult(
                url="https://one.example/news/1",
                title="",
                snippet="ALPHA STANCE_SUPPORTS",
                published_at="2026-03-05",
            )
        ]
    )
    pipeline = FactCheckPipeline(llm=llm, search=search, cache=None, settings=settings)
    result = await pipeline.analyze(
        text="On March 5, 2026 company Alpha announced the acquisition of company Beta, John Smith said."
    )
    assert result.language == "en"
    verdict = result.claims[0]
    assert verdict.label == VerdictLabel.supported
    assert "Independent source groups" in verdict.explanation
    assert "Claims checked: 1" in result.summary
