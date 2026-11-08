"""Spec 0029 (AC-7, R-7): NotificationQueue bellek kuyruğu testleri."""

from crytobot.reporting._queue import NotificationQueue, OutgoingMessage


def test_retry_queue_maxlen_and_network_isolation() -> None:
    queue = NotificationQueue(maxlen=10)
    assert len(queue) == 0
    assert queue.dropped_count == 0

    # 1. 10 mesaj ekle: hiçbiri atılmamalı
    for i in range(10):
        dropped = queue.enqueue(OutgoingMessage(text=f"Message {i}"))
        assert not dropped
    assert len(queue) == 10
    assert queue.dropped_count == 0

    # İlk mesaj "Message 0" olmalı
    peeked = queue.peek()
    assert peeked is not None
    assert peeked.text == "Message 0"

    # 2. 11. mesajı ekle: en eski mesaj (Message 0) atılmalı
    dropped = queue.enqueue(OutgoingMessage(text="Message 10"))
    assert dropped
    assert len(queue) == 10
    assert queue.dropped_count == 1

    # Sıradaki mesaj artık "Message 1" olmalı (Message 0 atıldı)
    peeked2 = queue.peek()
    assert peeked2 is not None
    assert peeked2.text == "Message 1"

    # 3. 5 mesaj daha ekle
    for i in range(11, 16):
        queue.enqueue(OutgoingMessage(text=f"Message {i}"))
    assert len(queue) == 10
    assert queue.dropped_count == 6

    # 4. drain() ile tüm kuyruğu boşalt
    messages = queue.drain()
    assert len(messages) == 10
    assert len(queue) == 0
    assert messages[0].text == "Message 6"
    assert messages[-1].text == "Message 15"

    # 5. Boş kuyrukta pop() None dönmeli
    assert queue.pop() is None
