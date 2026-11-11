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
        drain_errors = self.drain_queue()

        if not self.is_active:
            return "reporting_disabled"

        # Kuyruk tamamen eritilemediyse (ağ hala kapalı), sırayı korumak ve
        # mükerrer zaman aşımını önlemek için yeni mesajı doğrudan kuyruğa ekle (F-02)
        if len(self._queue) > 0:
            self._queue.enqueue(OutgoingMessage(text=text, parse_mode=parse_mode))
            return drain_errors[0] if drain_errors else "network_error"

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
        closure_or_pair: Any = None,
        reason: str = "",
        realized_pnl: Decimal | None = None,
        pnl_pct: Decimal | None = None,
        *,
        pair: str = "",
        closure: Any = None,
    ) -> str | None:
        """Pozisyon kapanış bildirimini gönderir veya kuyruğa alır.

        `closure` nesnesi verilebilir veya `pair, reason, realized_pnl, pnl_pct`
        ayrı ayrı geçilebilir.
        """
        cl = (
            closure
            if closure is not None
            else (
                closure_or_pair
                if closure_or_pair is not None and not isinstance(closure_or_pair, str)
                else None
            )
        )
        remaining: Decimal | None = None
        if cl is not None:
            pos = getattr(cl, "position", None)
            actual_realized = getattr(cl, "realized", Decimal(0))
            if pos is not None:
                actual_pair = str(getattr(pos, "pair", ""))
                amount = getattr(pos, "amount", Decimal(0))
                cost_price = getattr(pos, "cost_price", Decimal(0))
                fee = getattr(pos, "fee", Decimal(0))
                cost = amount * cost_price + fee
                part = getattr(cl, "amount", amount)
                if part < amount:
                    # spec 0037 R-3: kısmi kapanış — oran yalnız kapanan kısmın maliyetine
                    # (gelir - kâr/zarar = orantılı maliyet, G-7) bölünür
                    remaining = amount - part
                    cost = getattr(cl, "proceeds", Decimal(0)) - actual_realized
            else:
                actual_pair = ""
                cost = Decimal(0)
            reason_obj = getattr(cl, "reason", None)
            actual_reason = str(getattr(reason_obj, "value", reason_obj))
            if cost > 0:
                actual_pnl_pct = ((actual_realized / cost) * Decimal(100)).quantize(Decimal("0.01"))
            else:
                actual_pnl_pct = Decimal(0)
        else:
            actual_pair = pair or (str(closure_or_pair) if closure_or_pair is not None else "")
            actual_reason = reason
            actual_realized = realized_pnl if realized_pnl is not None else Decimal(0)
            actual_pnl_pct = pnl_pct if pnl_pct is not None else Decimal(0)

        text = format_close_notice(
            actual_pair, actual_reason, actual_realized, actual_pnl_pct, remaining
        )
        return self.dispatch(text)

    def send_daily_summary(
        self,
        day: date,
        start_equity: Decimal,
        end_equity: Decimal,
        realized_pnl_or_open_positions: Decimal | int | None = None,
        pnl_pct_or_closures: Decimal | tuple[Any, ...] | list[Any] | None = None,
        open_positions_count: int | None = None,
        closed_trades_count: int | None = None,
        *,
        closures: tuple[Any, ...] | list[Any] = (),
        realized_pnl: Decimal | None = None,
        pnl_pct: Decimal | None = None,
    ) -> str | None:
        """UTC gün dönümü özet raporunu gönderir veya kuyruğa alır."""
        # 1. closure listesiyle çağrı durumu:
        actual_closures: tuple[Any, ...] | list[Any] = closures
        if isinstance(pnl_pct_or_closures, (tuple, list)):
            actual_closures = pnl_pct_or_closures
            open_pos = int(realized_pnl_or_open_positions or 0)
        elif open_positions_count is not None:
            open_pos = open_positions_count
        else:
            open_pos = 0

        if actual_closures and realized_pnl is None:
            realized_pnl = sum(
                (getattr(c, "realized", Decimal(0)) for c in actual_closures), Decimal(0)
            )
        if actual_closures and closed_trades_count is None:
            closed_trades_count = len(actual_closures)

        if isinstance(realized_pnl_or_open_positions, Decimal):
            actual_realized = realized_pnl_or_open_positions
        else:
            actual_realized = realized_pnl if realized_pnl is not None else Decimal(0)

        if isinstance(pnl_pct_or_closures, Decimal):
            actual_pnl_pct = pnl_pct_or_closures
        elif pnl_pct is not None:
            actual_pnl_pct = pnl_pct
        else:
            if start_equity > 0:
                actual_pnl_pct = (
                    ((end_equity - start_equity) / start_equity) * Decimal(100)
                ).quantize(Decimal("0.01"))
            else:
                actual_pnl_pct = Decimal(0)

        actual_closed_count = closed_trades_count if closed_trades_count is not None else 0

        text = format_daily_summary(
            day,
            start_equity,
            end_equity,
            actual_realized,
            actual_pnl_pct,
            open_pos,
            actual_closed_count,
        )
        return self.dispatch(text)
