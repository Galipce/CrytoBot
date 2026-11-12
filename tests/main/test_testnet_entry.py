"""Spec 0041 CB-1, CB-3: giriş noktası ağı okumaya iletir; paper modda testnet reddedilir."""

import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import crytobot.__main__ as entry
from crytobot.__main__ import EXIT_OK, EXIT_REFUSED, run
from crytobot.app import StopRequest, prepare_live_store
from crytobot.market_data import MarketRead
from tests.app.test_live_start import NOW, FakeLiveClient, write_test_config


class ReadSpy:
    """`read_market_data` yerine: ağ bayrağını yazar, durdurma ister, borsaya çıkmaz."""

    def __init__(self, stop: StopRequest) -> None:
        self.stop = stop
        self.networks: list[bool] = []

    def __call__(
        self, pairs: Any, settings: Any, clock: Any, *, testnet: bool = False, **_: Any
    ) -> MarketRead:
        self.networks.append(testnet)
        self.stop.request("test")
        moment: datetime = clock()
        return MarketRead((), moment, None)


@pytest.mark.parametrize("testnet", [True, False])
def test_live_testnet_turn_uses_testnet_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, testnet: bool
) -> None:
    """CB-1: testnet canlı koşusunun turu okumayı testnet'ten ister; mainnet'te bugünkü gibi."""
    cfg = write_test_config(tmp_path, mode="live", testnet=testnet)
    prepare_live_store(
        (tmp_path / "bot.db").as_posix(),
        NOW,
        testnet=testnet,
        live_client=FakeLiveClient(free_balance=Decimal(1000)),
    )
    stop = StopRequest()
    spy = ReadSpy(stop)
    monkeypatch.setattr(entry, "read_market_data", spy)

    run(
        ["start", "--live"],
        config_path=cfg,
        console=io.StringIO(),
        live_client=FakeLiveClient(free_balance=Decimal(1000)),
        stop=stop,
        wait=lambda _: None,
    )

    assert spy.networks == [testnet]


@pytest.mark.parametrize("argv", [["start"], ["start", "--trial"], ["prepare"]])
def test_paper_start_trial_prepare_refuse_testnet(tmp_path: Path, argv: list[str]) -> None:
    """CB-3: paper modda `testnet = true` → ret; depo, kilit ve kayıt dosyası oluşmaz, okuma
    yapılmaz, çıkış 1."""
    cfg = write_test_config(tmp_path, mode="paper", testnet=True)
    before = sorted(p.name for p in tmp_path.iterdir())
    reads: list[object] = []

    def read(pairs: tuple[str, ...], settings: object) -> MarketRead:
        reads.append(pairs)
        raise AssertionError("no read in a refused paper start")

    out = io.StringIO()

    code = run(argv, config_path=cfg, console=out, read=read)

    assert code == EXIT_REFUSED
    (refusal,) = out.getvalue().splitlines()
    assert refusal.endswith(
        "ayar bot başlamadı: ayar geçersiz: exchange.testnet (testnet yalnız live modda)"
    )
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert reads == []


@pytest.mark.parametrize("argv", [["status"], ["stop"]])
def test_paper_control_commands_do_not_read_the_network(tmp_path: Path, argv: list[str]) -> None:
    """G-2: kontrol komutları ağ ayarını okumaz; CB-3 retti yalnız start/prepare içindir."""
    cfg = write_test_config(tmp_path, mode="paper", testnet=True)
    out = io.StringIO()

    run(argv, config_path=cfg, console=out)

    assert "exchange.testnet" not in out.getvalue()


@pytest.mark.parametrize(("testnet", "label"), [(True, "[TESTNET]"), (False, None)])
def test_entry_labels_the_reporter_only_on_testnet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, testnet: bool, label: str | None
) -> None:
    """Review round 1 F-2 (CB-5, G-3): reporter verilmeyen canlı başlatmada giriş noktası
    Telegram servisini testnet'te `[TESTNET]` etiketiyle, mainnet'te etiketsiz kurar."""
    from crytobot.reporting import ReportingService, TelegramConfig

    cfg = write_test_config(tmp_path, mode="live", testnet=testnet)
    prepare_live_store(
        (tmp_path / "bot.db").as_posix(),
        NOW,
        testnet=testnet,
        live_client=FakeLiveClient(free_balance=Decimal(1000)),
    )
    active = TelegramConfig(enabled=True, bot_token="t", chat_id="c")
    monkeypatch.setattr(entry, "load_reporting_config", lambda *a, **k: active)
    labels: list[str | None] = []

    def spy(config: TelegramConfig, label: str | None = None) -> ReportingService:
        labels.append(label)
        return ReportingService(config, transport=lambda u, p: (200, "{}"), label=label)

    monkeypatch.setattr(entry, "ReportingService", spy)
    stop = StopRequest()
    stop.request("test")

    run(
        ["start", "--live"],
        config_path=cfg,
        console=io.StringIO(),
        live_client=FakeLiveClient(free_balance=Decimal(1000)),
        stop=stop,
    )

    assert labels == [label]


_KEYS = {
    "BINANCE_API_KEY": "mainnet-key",
    "BINANCE_API_SECRET": "mainnet-secret",
    "BINANCE_TESTNET_API_KEY": "testnet-key",
    "BINANCE_TESTNET_API_SECRET": "testnet-secret",
}


def _record_built_clients(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    """`BinanceLiveClient` yerine: kimlikten kurulan istemcinin anahtarını ve ağını yazar, borsaya
    çıkmaz. Ortamda iki anahtar seti vardır; çalışma dizini `.env` içermez."""
    from crytobot.app import _start as start_module

    built: list[tuple[str, bool]] = []

    class Recording(FakeLiveClient):
        def __init__(self, credentials: Any, exchange: Any = None) -> None:
            built.append((credentials.api_key, credentials.testnet))
            super().__init__(free_balance=Decimal(1000))

    for name, value in _KEYS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(start_module, "BinanceLiveClient", Recording)
    return built


@pytest.mark.parametrize(("testnet", "key"), [(True, "testnet-key"), (False, "mainnet-key")])
def test_live_start_and_prepare_load_the_network_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, testnet: bool, key: str
) -> None:
    """Verify round 1 F-11 (PB-4, CB-1): istemci verilmeyen `prepare --live` ve `start --live`
    testnet'te yalnız testnet anahtarıyla, mainnet'te yalnız mainnet anahtarıyla istemci kurar."""
    monkeypatch.chdir(tmp_path)
    cfg = write_test_config(tmp_path, mode="live", testnet=testnet)
    built = _record_built_clients(monkeypatch)

    prepared = run(["prepare", "--live"], config_path=cfg, console=io.StringIO())

    assert prepared == EXIT_OK
    assert built == [(key, testnet)]

    stop = StopRequest()
    stop.request("test")
    started = run(["start", "--live"], config_path=cfg, console=io.StringIO(), stop=stop)

    assert started == EXIT_OK
    assert built == [(key, testnet), (key, testnet)]
