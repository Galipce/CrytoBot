"""Reporting servisi: bildirim dağıtımı, kuyruk eritme ve fail-safe izolasyonu.

Spec 0029 (R-7, AC-7, AC-8).

Bu servis botun ana döngüsünden (`app`) olayları alır. Telegram istemcisine iletir;
ağ hatası durumunda mesajları sessizce kuyruğa alır ve döngüyü kesinlikle durdurmaz.
"""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

from crytobot.reporting._client import TelegramClient
from crytobot.reporting._config import TelegramConfig
from crytobot.reporting._formatter import (
    format_close_notice,
    format_daily_summary,
    format_fill_notice,
    format_turn_notice,
)
from crytobot.reporting._queue import NotificationQueue, OutgoingMessage


class ReportingService:
    """Bildirim ve raporlama koordinasyon servisi."""

    def __init__(
        self,
        config: TelegramConfig,
        client: TelegramClient | None = None,
        queue: NotificationQueue | None = None,
        transport: Callable[[str, dict[str, Any]], tuple[int, str]] | None = None,
    ) -> None:
        self._config = config
        self._client = client or TelegramClient(config, transport=transport)
        self._queue = queue or NotificationQueue(maxlen=10)

    @property
    def is_active(self) -> bool:
        """Servis ve istemci aktif mi?"""
        return self._client.is_active

    @property
    def queue(self) -> NotificationQueue:
        return self._queue

    def drain_queue(self) -> list[str]:
        """Kuyruktaki bekleyen bildirimleri sırayla iletmeyi dener.

        Ağ hatası devam ederse kuyruğu eritme işlemi durdurulur ve hata adları dönülür.
        """
        if not self.is_active or len(self._queue) == 0:
            return []

        errors: list[str] = []
        while len(self._queue) > 0:
            msg = self._queue.peek()
            if msg is None:
                break
            success, err = self._client.send_message(msg.text, msg.parse_mode)
            if success:
                self._queue.pop()
            else:
                if err:
                    errors.append(err)
                # İletim başarısız olduysa sonraki turlara bırak
                break
        return errors

    def dispatch(self, text: str, parse_mode: str | None = "HTML") -> str | None:
        """Kuyruğu eritmeyi dener ve yeni mesajı gönderir. Ağ hatasında kuyruğa ekler."""
        if not self._config.enabled:
            return None

        # Önce varsa kuyruktaki eski mesajları eritmeyi dene
        self.drain_queue()

        if not self.is_active:
            return "reporting_disabled"

        success, err = self._client.send_message(text, parse_mode=parse_mode)
        if success:
            return None

        # İletilemedi: 401 kimlik hatası değilse yeniden denemek üzere kuyruğa al
        if err != "http_401_unauthorized":
            self._queue.enqueue(OutgoingMessage(text=text, parse_mode=parse_mode))
        return err

    def send_turn_notice(
        self,
        kind: str,
        subject: str,
        entering: bool,
        message: str,
    ) -> str | None:
        """TurnNotice durum bildirimini gönderir veya kuyruğa alır."""
        text = format_turn_notice(kind, subject, entering, message)
        return self.dispatch(text)

    def send_fill_notice(
        self,
        pair: str,
        side: str,
        amount: Decimal,
        price: Decimal,
        stop: Decimal | None = None,
    ) -> str | None:
        """İşlem dolum bildirimini gönderir veya kuyruğa alır."""
        text = format_fill_notice(pair, side, amount, price, stop)
        return self.dispatch(text)

    def send_close_notice(
        self,
        pair: str,
        reason: str,
        realized_pnl: Decimal,
        pnl_pct: Decimal,
    ) -> str | None:
        """Pozisyon kapanış bildirimini gönderir veya kuyruğa alır."""
        text = format_close_notice(pair, reason, realized_pnl, pnl_pct)
        return self.dispatch(text)

    def send_daily_summary(
        self,
        day: date,
        start_equity: Decimal,
        end_equity: Decimal,
        realized_pnl: Decimal,
        pnl_pct: Decimal,
        open_positions_count: int,
        closed_trades_count: int,
    ) -> str | None:
        """UTC gün dönümü özet raporunu gönderir veya kuyruğa alır."""
        text = format_daily_summary(
            day,
            start_equity,
            end_equity,
            realized_pnl,
            pnl_pct,
            open_positions_count,
            closed_trades_count,
        )
        return self.dispatch(text)
