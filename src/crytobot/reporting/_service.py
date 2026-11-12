"""Reporting servisi: bildirim dağıtımı, kuyruk eritme ve fail-safe izolasyonu.

Spec 0029 (R-7, AC-7, AC-8); spec 0039 (Telegram güvenilirliği, plan A-1).

Bu servis botun ana döngüsünden (`app`) olayları alır ve Telegram istemcisine iletir. Döngü
her turu `begin_turn` / `end_turn` ile çevreler; turda Telegram isteklerinde harcanan süre
`turn_budget_s`'yi aşamaz (CB-4). Gönderim kapısı her istekten önce bakar: kapalı (CB-1), hız
sınırı beklemesi (CB-6), turda geçici hata (CB-5), bütçe bitti (CB-4), terk edilmiş istek
sürüyor (plan Risk 4). Kapı kapalıysa mesaj sırayla kuyruğa girer; kuyruk döngüyü durdurmaz.
Açık tur yokken gelen `dispatch` kendi tek çağrılık turunu açıp kapatır (plan Risk 2).

Spec 0041 CB-5 (G-4): `label` verilirse (testnet koşusu: `[TESTNET]`) her mesajın metni gönderimde
değil oluşturulurken öneklenir; kuyruktaki ve 400 sonrası düz metin yedeği de öneki taşır.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from crytobot.reporting._client import Attempt, Outcome, TelegramClient
from crytobot.reporting._config import TelegramConfig
from crytobot.reporting._formatter import (
    format_close_notice,
    format_daily_summary,
    format_fill_notice,
    format_turn_notice,
)
from crytobot.reporting._queue import NotificationQueue, OutgoingMessage

_BUDGET_SPENT = "telegram_turn_budget"  # CB-4: turun Telegram süresi bitti


@dataclass(frozen=True)
class _Delivery:
    """Bir mesajın tur içindeki sonucu.

    `done`: mesaj kuyrukta beklemez (iletildi, atıldı ya da Telegram kapandı).
    `keep`: bekleyecekse kuyruktaki hâli (biçim hatasından sonra düz metin; plan Risk 5).
    """

    done: bool
    error: str | None = None
    keep: OutgoingMessage | None = None


class ReportingService:
    """Bildirim ve raporlama koordinasyon servisi."""

    def __init__(
        self,
        config: TelegramConfig,
        client: TelegramClient | None = None,
        queue: NotificationQueue | None = None,
        transport: Callable[[str, dict[str, Any]], tuple[int, str]] | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        turn_budget_s: float = 5.0,
        label: str | None = None,
    ) -> None:
        self._config = config
        self._label = label
        self._client = client or TelegramClient(config, transport=transport)
        self._queue = queue or NotificationQueue(maxlen=10)
        self._monotonic = monotonic
        self._turn_budget_s = turn_budget_s
        self._turn_open = False
        self._spent = 0.0
        self._turn_error: str | None = None  # CB-5: turda görülen ilk geçici hata
        self._blocked_until: float | None = None  # CB-6: 429 beklemesinin bittiği an
        self._disabled_reason: str | None = None  # CB-2: bir kez alınır
        self._dropped: list[str] = []  # CB-3: kuyruktan atılanların hata adları, bir kez alınır

    @property
    def is_active(self) -> bool:
        """Servis ve istemci aktif mi?"""
        return self._client.is_active

    @property
    def queue(self) -> NotificationQueue:
        return self._queue

    # --- tur penceresi ------------------------------------------------------------------------
    def begin_turn(self) -> list[str]:
        """Turun Telegram bütçesini açar, kuyruğu sırayla iletmeyi dener (CB-4, CB-5).

        Dönüş: kuyruktan atılan mesajların hata adları (CB-3: loga yazılır).
        """
        self._open_turn()
        if not self._config.enabled:
            return []
        self._flush()
        return self.take_dropped()

    def _open_turn(self) -> None:
        self._turn_open = True
        self._spent = 0.0
        self._turn_error = None

    def end_turn(self) -> None:
        self._turn_open = False

    def take_disabled_reason(self) -> str | None:
        """Telegram kapandıysa gerekçesi; yalnız bir kez döner (CB-2)."""
        reason = self._disabled_reason
        self._disabled_reason = None
        return reason

    def take_dropped(self) -> list[str]:
        """Kuyruktan atılan mesajların hata adları; her biri yalnız bir kez döner (CB-3)."""
        dropped = self._dropped
        self._dropped = []
        return dropped

    # --- gönderim kapısı ----------------------------------------------------------------------
    def _gate(self) -> str | None:
        """İstek gidebilirse `None`; gidemezse kuyruğa alınma nedeninin hata adı."""
        if self._blocked_until is not None:
            if self._monotonic() < self._blocked_until:
                return "http_429"
            self._blocked_until = None
        if self._turn_error is not None:
            return self._turn_error
        if self._turn_budget_s - self._spent <= 0:
            return _BUDGET_SPENT
        if self._client.busy:  # plan Risk 4: en fazla bir askıda istek
            self._turn_error = "timeout"
            return self._turn_error
        return None

    def _attempt(self, message: OutgoingMessage) -> Attempt:
        """Tek istek, kalan bütçeyle sınırlı; süresi harcanana eklenir (plan A-1)."""
        started = self._monotonic()
        result = self._client.attempt(
            message.text, message.parse_mode, self._turn_budget_s - self._spent
        )
        self._spent += max(0.0, self._monotonic() - started)
        return result

    def _shut(self, result: Attempt) -> _Delivery:
        """Kalıcı hata: Telegram bu çalışma boyunca kapanır, kuyruk boşalır (CB-1)."""
        self._client.disable()
        self._queue.clear()
        self._disabled_reason = result.reason
        return _Delivery(done=True)

    def _wait(self, result: Attempt, message: OutgoingMessage) -> _Delivery:
        """Geçici hata ya da 429: mesaj bekler (CB-5, CB-6)."""
        if result.outcome is Outcome.RATE_LIMITED and result.retry_after is not None:
            self._blocked_until = self._monotonic() + result.retry_after  # üst sınır yok (G-5)
        else:
            self._turn_error = result.error
        return _Delivery(done=False, error=result.error, keep=message)

    def _deliver(self, message: OutgoingMessage) -> _Delivery:
        """Kapı açıkken bir mesajı iletir; bir mesaj için turda en fazla 2 istek (CB-3)."""
        result = self._attempt(message)
        if result.outcome is Outcome.FORMAT and message.parse_mode is not None:
            message = OutgoingMessage(text=message.text, parse_mode=None)
            gate = self._gate()
            if gate is not None:
                return _Delivery(done=False, error=gate, keep=message)
            result = self._attempt(message)
        if result.outcome is Outcome.OK:
            return _Delivery(done=True)
        if result.outcome is Outcome.PERMANENT:
            return self._shut(result)
        if result.outcome in (Outcome.FORMAT, Outcome.REJECTED):
            return _Delivery(done=True, error=result.error)  # atılır, kuyruğa girmez
        return self._wait(result, message)

    def _flush(self) -> str | None:
        """Kuyruğu sırayla iletir; durma nedeni. Atılanlar `take_dropped`'a birikir (CB-3)."""
        while len(self._queue) > 0 and self.is_active:
            gate = self._gate()
            if gate is not None:
                return gate
            head = self._queue.peek()
            if head is None:
                break
            delivery = self._deliver(head)
            if delivery.done:
                if self.is_active:  # kapanınca kuyruk zaten boşaldı
                    self._queue.pop()
                if delivery.error is not None:
                    self._dropped.append(delivery.error)
                continue
            if delivery.keep is not None and delivery.keep != head:
                self._queue.replace_head(delivery.keep)
            return delivery.error
        return None

    def drain_queue(self) -> list[str]:
        """Kuyruktaki bekleyen bildirimleri sırayla iletmeyi dener; hata adlarını döner."""
        if not self._config.enabled:
            return []
        stopped = self._flush()
        dropped = self.take_dropped()
        return dropped + ([stopped] if stopped is not None and len(self._queue) > 0 else [])

    def dispatch(self, text: str, parse_mode: str | None = "HTML") -> str | None:
        """Yeni mesajı kuyruktakilerden sonra iletir; iletilemezse sırayla kuyruğa alır.

        Dönüş: tur hatalarına yazılacak hata adı ya da `None` (iletildi veya Telegram kapalı).
        """
        if not self._config.enabled:
            return None
        if self._label:  # CB-5: on creation, so the queue and the plain-text fallback carry it
            text = f"{self._label} {text}"
        own_turn = not self._turn_open
        if own_turn:
            self._open_turn()  # kuyruğu `_dispatch` iletir; atılanlar çağırana kalır (F-1)
        try:
            return self._dispatch(OutgoingMessage(text=text, parse_mode=parse_mode))
        finally:
            if own_turn:
                self.end_turn()

    def _dispatch(self, message: OutgoingMessage) -> str | None:
        stopped = self._flush()
        if not self.is_active:
            return None  # plan Risk 6: kapanma satırı tektir (CB-2)
        if len(self._queue) > 0:  # yeni mesaj öne geçmez (PB-2)
            self._queue.enqueue(message)
            return stopped  # kuyruk yalnız kapı kapalıyken durur: neden doludur (F-2)
        gate = self._gate()
        if gate is not None:
            self._queue.enqueue(message)
            return gate
        delivery = self._deliver(message)
        if not self.is_active:
            return None
        if not delivery.done and delivery.keep is not None:
            self._queue.enqueue(delivery.keep)
        return delivery.error

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
