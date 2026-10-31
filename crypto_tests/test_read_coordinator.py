import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.modules.crypto.read_coordinator import ReadCoordinator


def test_waiting_holdings_precede_waiting_scan_and_requests_never_overlap():
    coordinator=ReadCoordinator(0)
    events=[]
    with ThreadPoolExecutor(2) as pool:
        with coordinator.lease('okx',1):
            def request(priority):
                with coordinator.lease('okx',priority):events.append(priority)
            low=pool.submit(request,1)
            high=pool.submit(request,0)
            deadline=time.monotonic()+2
            while len(coordinator.waiters)<2 and time.monotonic()<deadline:time.sleep(.01)
            assert len(coordinator.waiters)==2 and events==[]
        low.result(timeout=2);high.result(timeout=2)
    assert events==[0,1] and not coordinator.active


def test_cancelled_waiter_does_not_leak_or_block_holdings():
    coordinator=ReadCoordinator(0)
    cancelled=threading.Event()
    with ThreadPoolExecutor(1) as pool:
        with coordinator.lease('okx',0):
            def pending():
                with coordinator.lease('okx',1,cancel=cancelled):raise AssertionError('must not acquire')
            future=pool.submit(pending)
            cancelled.set()
            with pytest.raises(InterruptedError):future.result(timeout=2)
        with coordinator.lease('okx',0):pass
    assert not coordinator.waiters and not coordinator.active


def test_exchanges_are_independent_and_spacing_is_shared():
    coordinator=ReadCoordinator(.03)
    with coordinator.lease('okx',1):
        with coordinator.lease('binance',0):pass
    start=time.monotonic()
    with coordinator.lease('okx',0):assert time.monotonic()-start>=.02
    with pytest.raises(TimeoutError):
        with coordinator.lease('okx',1,deadline=time.monotonic()-1):pass


def test_every_pinned_sdk_transport_call_is_gated(monkeypatch):
    import ccxt
    from contextlib import contextmanager
    from src.modules.crypto.adapter import SpotReader
    calls=[]
    @contextmanager
    def gate():
        calls.append('acquire')
        try:yield
        finally:calls.append('release')
    monkeypatch.setattr(ccxt.okx,'fetch',lambda *a,**k:calls.append('http'))
    reader=SpotReader('okx',request_gate=gate)
    reader._SpotReader__client.fetch('https://example.invalid')
    assert calls==['acquire','http','release']


def test_real_child_protocol_can_finish_without_network():
    # Empty/invalid requests are rejected by the real public module. No fixture
    # child, shell, network, credential or host configuration is involved.
    from src.modules.crypto.worker_io import execute
    coordinator=ReadCoordinator(0)
    with pytest.raises(RuntimeError):
        execute(sys.executable,'public_rpc',{'operation':'withdraw'},exchange='okx',coordinator=coordinator,priority=1,timeout=10)
    assert not coordinator.active
