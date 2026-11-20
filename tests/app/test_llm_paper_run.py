"""Spec 0060 review round 1 M-2, M-8: indirme karar kaydını okur, etkin dönemin sonuna
kadar iner."""

from datetime import datetime, timedelta

from crytobot.app._forward import ForwardOutcome
from crytobot.app._llm_paper_config import (
    MEASUREMENT_END,
    MEASUREMENT_START,
    LlmPaperConfig,
    load_llm_paper_config,
)
from crytobot.app._llm_paper_report import RecordTurn
from crytobot.app._llm_paper_run import (
    LlmPaperDownloadParts,
    LlmPaperRecord,
    run_llm_paper_download,
)
from crytobot.market_data import DownloadOutcome, PriceNeed

HOUR = timedelta(hours=1)
_LOADED = load_llm_paper_config(
    {
        "llm_paper": {
            key: f"C:/x/{key}"
            for key in (
                "decide_store_path",
                "s0_store_path",
                "price_store_path",
                "rules_path",
                "report_path",
                "trades_path",
            )
        }
    }
).config
assert _LOADED is not None
CONFIG: LlmPaperConfig = _LOADED


def parts(
    record: object, now: datetime, needs: list[tuple[PriceNeed, ...]]
) -> LlmPaperDownloadParts:
    def fetch() -> tuple[str, None]:
        return "{}", None

    def download(wanted: tuple[PriceNeed, ...]) -> DownloadOutcome:
        needs.append(wanted)
        return DownloadOutcome.COMPLETE

    return LlmPaperDownloadParts(
        ("BTC", "ETH"),
        lambda: record,  # type: ignore[arg-type, return-value]
        fetch,
        download,
        lambda path, text: True,
        lambda text: None,
        lambda: now,
    )


def test_restarted_period_downloads_past_the_fixed_end() -> None:
    restart = MEASUREMENT_START + timedelta(days=80)
    record = LlmPaperRecord(
        (
            RecordTurn(MEASUREMENT_START, "m", "p", "ok", True),
            RecordTurn(restart, "m", "q", "ok", True),
        ),
        (),
        0,
    )
    now = MEASUREMENT_END + timedelta(days=5, minutes=10)
    needs: list[tuple[PriceNeed, ...]] = []
    assert run_llm_paper_download(CONFIG, parts(record, now, needs)).outcome is (
        ForwardOutcome.COMPLETED
    )
    assert {n.end for n in needs[0]} == {MEASUREMENT_END + timedelta(days=5)}


def test_unchanged_period_stops_at_the_end() -> None:
    record = LlmPaperRecord((RecordTurn(MEASUREMENT_START, "m", "p", "ok", True),), (), 0)
    needs: list[tuple[PriceNeed, ...]] = []
    run_llm_paper_download(CONFIG, parts(record, MEASUREMENT_END + timedelta(days=5), needs))
    assert {n.end for n in needs[0]} == {MEASUREMENT_END}
    assert {n.start for n in needs[0]} == {MEASUREMENT_START - HOUR}


def test_unreadable_record_refused_before_network() -> None:
    needs: list[tuple[PriceNeed, ...]] = []
    found = run_llm_paper_download(CONFIG, parts("karar kaydı okunamıyor", MEASUREMENT_END, needs))
    assert (found.outcome, found.message) == (ForwardOutcome.REFUSED, "karar kaydı okunamıyor")
    assert needs == []
