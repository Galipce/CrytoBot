"""İletilemeyen bildirimler için sınırlı bellek kuyruğu (spec 0029 R-7, AC-7).

Bellek içi kuyruk en fazla 10 mesaj tutar (maxlen=10). Kuyruk taştığında en eski mesaj atılır
(FIFO drop-oldest). Bot yeniden başlatıldığında kuyruk sıfırlanır.
"""

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class OutgoingMessage:
    """Kuyruğa alınan iletilecek bildirim."""

    text: str
    parse_mode: str | None = "HTML"


class NotificationQueue:
    """En fazla `maxlen` (varsayılan 10) mesaj tutan bellek içi yeniden deneme kuyruğu."""

    def __init__(self, maxlen: int = 10) -> None:
        self._maxlen = maxlen
        self._queue: deque[OutgoingMessage] = deque(maxlen=maxlen)
        self._dropped_count: int = 0

    @property
    def maxlen(self) -> int:
        return self._maxlen

    @property
    def dropped_count(self) -> int:
        """Kuyruk doluluğundan dolayı atılan mesaj sayısı."""
        return self._dropped_count

    def enqueue(self, message: OutgoingMessage) -> bool:
        """Mesajı kuyruğa ekler. Kuyruk doluysa en eski mesaj atılır ve True döner."""
        dropped = len(self._queue) >= self._maxlen
        if dropped:
            self._dropped_count += 1
        self._queue.append(message)
        return dropped

    def pop(self) -> OutgoingMessage | None:
        """Sıradaki mesajı kuyruktan çıkarıp döner; boşsa None."""
        if self._queue:
            return self._queue.popleft()
        return None

    def peek(self) -> OutgoingMessage | None:
        """Sıradaki mesajı kuyruktan çıkarmadan döner; boşsa None."""
        if self._queue:
            return self._queue[0]
        return None

    def drain(self) -> list[OutgoingMessage]:
        """Kuyruktaki tüm mesajları sırasıyla boşaltıp liste olarak döner."""
        items = list(self._queue)
        self._queue.clear()
        return items

    def clear(self) -> None:
        """Kuyruğu temizler."""
        self._queue.clear()

    def __len__(self) -> int:
        return len(self._queue)
