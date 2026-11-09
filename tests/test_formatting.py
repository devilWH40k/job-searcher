"""Scraped HTML is escaped and each Telegram card stays within its limit."""

from job_bot.models import Vacancy
from job_bot.telegram.formatting import format_vacancy


def test_card_escapes_scraped_fields() -> None:
    vacancy = Vacancy(
        "work.ua",
        "123",
        "https://www.work.ua/jobs/123/",
        '<b>Frontend & "React"</b>',
        company="R&D <script>",
        location="Дистанційно",
        salary_text="$1,000 < $2,000",
    )

    card = format_vacancy(vacancy)

    assert "&lt;b&gt;Frontend &amp; &quot;React&quot;&lt;/b&gt;" in card
    assert "R&amp;D &lt;script&gt;" in card
    assert "$1,000 &lt; $2,000" in card
    assert "Source: Work.ua" in card


def test_missing_fields_are_omitted() -> None:
    card = format_vacancy(
        Vacancy("work.ua", "123", "https://www.work.ua/jobs/123/", "Frontend")
    )

    assert "Salary:" not in card
    assert "Location:" not in card
    assert "None" not in card


def test_pathological_text_stays_within_telegram_limit() -> None:
    long_text = '<>&"😀' * 5000
    vacancy = Vacancy(
        "work.ua",
        "123",
        "https://www.work.ua/jobs/123/",
        long_text,
        company=long_text,
        location=long_text,
        salary_text=long_text,
    )

    card = format_vacancy(vacancy)

    assert len(card.encode("utf-16-le")) // 2 <= 4096
    assert vacancy.salary_text == long_text


def test_djinni_salary_band_and_source_are_identified() -> None:
    vacancy = Vacancy(
        "djinni",
        "123",
        "https://djinni.co/jobs/123-frontend/",
        "Frontend",
        salary_text="$$$$",
    )

    card = format_vacancy(vacancy)

    assert "Salary band (relative): $$$$" in card
    assert "Source: Djinni" in card
    assert "Work.ua" not in card
