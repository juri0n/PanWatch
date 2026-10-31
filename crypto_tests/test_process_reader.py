import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from src.modules.crypto.adapter import DataUnavailable
from src.modules.crypto.process_reader import ProcessSpotReader
from src.modules.crypto.public_rpc import handle_request


@pytest.mark.parametrize('payload', [
    {'operation': 'create_order', 'exchange': 'okx', 'symbol': 'BTC/USDT'},
    {'operation': 'withdraw', 'exchange': 'okx', 'symbol': 'BTC/USDT'},
    {'operation': 'quote', 'exchange': 'okx', 'symbol': 'BTC/USDT', 'apiKey': 'forbidden'},
    {'operation': 'quote', 'exchange': 'okx', 'symbol': 'BTC/USDT', 'params': {}},
    {'operation': 'quote', 'exchange': 'https://example.com', 'symbol': 'BTC/USDT'},
    {'operation': 'quote', 'exchange': 'okx', 'symbol': 'BTC/USDT:USDT'},
])
def test_worker_rejects_private_operations_before_creating_an_exchange(payload):
    def forbidden_factory(exchange):
        pytest.fail('invalid request reached exchange')
    with pytest.raises(ValueError):
        handle_request(payload, forbidden_factory)


def test_actual_child_process_rejects_execution_without_host_dependencies():
    reply = subprocess.run([sys.executable, '-m', 'src.modules.crypto.public_rpc'],
        input=json.dumps({'operation': 'withdraw', 'exchange': 'okx', 'symbol': 'BTC/USDT'}),
        capture_output=True, text=True, cwd=Path(__file__).parents[1], timeout=10)
    assert reply.returncode == 2
    assert json.loads(reply.stdout) == {'error_type': 'ValueError'}
    assert not reply.stderr


def test_process_boundary_strips_credentials_and_retains_decimal_strings(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'must-not-cross')
    monkeypatch.setenv('AUTH_PASSWORD', 'must-not-cross')
    monkeypatch.setenv('PYTHONPATH', 'must-not-cross')
    seen = []
    now = int(time.time() * 1000)
    row = {'exchange': 'okx', 'symbol': 'BTC/USDT', 'quote_currency': 'USDT',
           'price': '0.0000000000123456789', 'source_ms': now, 'observed_ms': now}
    def run(args, **kwargs):
        seen.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({'result': row}))
    monkeypatch.setattr(subprocess, 'run', run)
    reader = ProcessSpotReader('okx', sys.executable)
    quote = reader.quote('BTC/USDT')
    assert str(quote.price) == '1.23456789E-11'
    env = seen[0][1]['env']
    assert not {'OPENAI_API_KEY', 'AUTH_PASSWORD', 'PYTHONPATH'} & env.keys()
    assert json.loads(seen[0][1]['input']) == {'operation': 'quote', 'exchange': 'okx', 'symbol': 'BTC/USDT'}
    assert seen[0][1]['timeout'] == 45
    row['source_ms'] -= 121000
    with pytest.raises(DataUnavailable):
        reader.quote('BTC/USDT')


def test_timeout_does_not_leak_child_stderr(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('public-reader', 45, stderr='sensitive upstream error')
    monkeypatch.setattr(subprocess, 'run', timeout)
    with pytest.raises(DataUnavailable, match='unavailable') as error:
        ProcessSpotReader('okx', sys.executable).quote('BTC/USDT')
    assert 'sensitive' not in str(error.value)


def test_batch_reuses_one_reader_and_parent_quotes_do_not_start_more_children(monkeypatch):
    from decimal import Decimal
    from src.modules.crypto.adapter import Quote
    created = []
    now = int(time.time() * 1000)
    class Reader:
        def __init__(self, exchange):
            created.append(exchange)
        def quote(self, symbol):
            return Quote('okx', symbol, 'USDT', Decimal('1.2345'), now, now)
    payload = {'operation': 'quotes', 'exchange': 'okx', 'symbols': ['BTC/USDT', 'ETH/USDT']}
    rows = handle_request(payload, Reader)
    assert created == ['okx'] and len(rows) == 2
    calls = []
    def run(args, **kwargs):
        calls.append(json.loads(kwargs['input']))
        return SimpleNamespace(returncode=0, stdout=json.dumps({'result': rows}))
    monkeypatch.setattr(subprocess, 'run', run)
    reader = ProcessSpotReader('okx', sys.executable)
    reader.prepare(payload['symbols'])
    assert reader.quote('BTC/USDT').price == Decimal('1.2345')
    assert reader.quote('ETH/USDT').price == Decimal('1.2345')
    assert calls == [payload]
