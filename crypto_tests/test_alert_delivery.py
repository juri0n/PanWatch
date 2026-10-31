"""Price-alert lifecycle at the production workflow boundary, no external sends."""
import asyncio
from copy import deepcopy
from decimal import Decimal
import time
from types import SimpleNamespace

import pytest

from src.modules.crypto.adapter import Quote
from src.modules.crypto.workflow import CryptoWorkflow


def scenario(tmp_path, *, op='>=', price='100', outcome=None, age=0, enabled=True):
    calls = []
    class Reader:
        max_age_ms = 120000
        def __init__(self, exchange): self.exchange = exchange
        def quote(self, symbol):
            now = int(time.time()*1000)
            return Quote(self.exchange, symbol, 'USDT', Decimal(price), now-age, now)
    async def send(*args):
        calls.append(args)
        if isinstance(outcome, Exception): raise outcome
        return outcome or {'success': True}
    context = SimpleNamespace(notifier=SimpleNamespace(notify_with_result=send))
    def build(): return CryptoWorkflow(tmp_path/'crypto.sqlite3', lambda _:context, reader_factory=Reader)
    config = dict(exchange='okx',interval_seconds=60,positions=[dict(symbol='BTC/USDT',quantity='0.001')],
                  alerts=[dict(symbol='BTC/USDT',op=op,price='100',cooldown_minutes=60,notify=enabled)])
    return build,config,calls


@pytest.mark.parametrize('op,price,triggered',[('>=','99.99',False),('>=','100',True),('>=','100.01',True),
                                             ('<=','100.01',False),('<=','100',True),('<=','99.99',True)])
def test_threshold_boundaries(tmp_path,op,price,triggered):
    async def run():
        build,config,calls=scenario(tmp_path,op=op,price=price)
        service=build()
        await service.save(config)
        await service.refresh()
        assert len(calls)==int(triggered)
        assert len(service.view()['events'])==int(triggered)
        assert service.view()['config']==config
    asyncio.run(run())


@pytest.mark.parametrize('outcome,status',[({'success':True},'sent'),({'success':False,'skipped':'quiet_hours'},'skipped'),
                                         ({'success':False},'failed'),(RuntimeError('secret'),'failed')])
def test_claim_survives_repeats_restart_and_ambiguous_failure(tmp_path,outcome,status):
    async def run():
        build,config,calls=scenario(tmp_path,outcome=outcome)
        service=build()
        await service.save(config)
        await service.refresh()
        await service.refresh()
        restart=build()
        await restart.refresh()
        assert len(calls)==1
        assert len(restart.view()['events'])==1
        assert restart.view()['events'][0]['delivery']['status']==status
        assert 'secret' not in str(restart.view())
    asyncio.run(run())


def test_cooldown_expiry_allows_next_event_without_a_real_wait(tmp_path):
    async def run():
        build,config,calls=scenario(tmp_path)
        service=build()
        await service.save(config)
        await service.refresh()
        cooldowns=service.store.get('cooldowns')
        service.store.put('cooldowns',{k:time.time()-3601 for k in cooldowns})
        await service.refresh()
        assert len(calls)==2 and len(service.view()['events'])==2
    asyncio.run(run())


@pytest.mark.parametrize('age',[120001,-1000])
def test_stale_or_future_quote_cannot_trigger(tmp_path,age):
    async def run():
        build,config,calls=scenario(tmp_path,age=age)
        service=build()
        await service.save(config)
        await service.refresh()
        assert not calls and not service.view()['events']
        assert service.view()['snapshot']['status']=='error'
    asyncio.run(run())


def test_disabled_notification_records_without_sending(tmp_path):
    async def run():
        build,config,calls=scenario(tmp_path,enabled=False)
        service=build()
        await service.save(config)
        await service.refresh()
        assert not calls and service.view()['events'][0]['delivery']['status']=='disabled'
        invalid=deepcopy(config)
        invalid['alerts']*=2
        with pytest.raises(ValueError): await service.save(invalid)
        assert service.view()['config']==config
    asyncio.run(run())
