"""AC-7: testler ağa çıkamaz; bağlantı denemesi engellenir."""

import socket

import pytest
from pytest_socket import SocketBlockedError

# pytest-socket warns before raising; the raise is what this test asserts
pytestmark = pytest.mark.filterwarnings("ignore:A test tried to use socket:UserWarning")


def test_socket_connection_is_blocked() -> None:
    with pytest.raises(SocketBlockedError):
        socket.create_connection(("example.com", 443), timeout=1)


def test_raw_socket_to_ip_is_blocked() -> None:
    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("1.1.1.1", 443))
