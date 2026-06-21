from __future__ import annotations

import socket

import pytest

from src.data.adapters import baostock_adapter


def test_fail_closed_socket_rejects_peer_disconnect():
    reader, writer = socket.socketpair()
    guarded_reader = baostock_adapter._FailClosedSocket(fileno=reader.detach())
    writer.close()
    try:
        with pytest.raises(ConnectionError, match="closed the connection"):
            guarded_reader.recv(16)
    finally:
        guarded_reader.close()


def test_socket_guard_sets_timeout_and_restores_connect(monkeypatch):
    import baostock.common.contants as constants
    import baostock.common.context as context
    import baostock.util.socketutil as socketutil

    created = []

    class FakeSocket:
        def __init__(self, *_args, **_kwargs):
            self.timeout = None
            self.closed = False
            created.append(self)

        def settimeout(self, value):
            self.timeout = value

        def connect(self, address):
            self.address = address

        def close(self):
            self.closed = True

    original_connect = socketutil.SocketUtil.connect
    monkeypatch.setattr(baostock_adapter, "_FailClosedSocket", FakeSocket)

    with baostock_adapter._baostock_socket_guard(2.5):
        socketutil.SocketUtil().connect()
        assert created[0].timeout == 2.5
        assert created[0].address == (
            constants.BAOSTOCK_SERVER_IP,
            constants.BAOSTOCK_SERVER_PORT,
        )
        assert context.default_socket is created[0]

    assert created[0].closed is True
    assert socketutil.SocketUtil.connect is original_connect
    assert not hasattr(context, "default_socket")
