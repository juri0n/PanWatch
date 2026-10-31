import asyncio
from dataclasses import asdict
from types import SimpleNamespace
import time

import pytest

from src.modules.crypto.opportunities import OpportunityService
from src.modules.crypto.workflow import Store
from src.modules.crypto.strategy_profile import CryptoProfile
from src.modules.crypto.scan_worker import run_probe
from src.modules.crypto.technical_scan import score_probe
from crypto_tests.test_universe import Reader, config


def make(tmp_path,runner=None):
    holdings={'exchange':'okx','positions':[{'symbol':'BTC/USDT','quantity':'0.001'}]}
    def compute(cfg,cancel):
        pytest.importorskip('httpx')
        class VolumeReader(Reader):
            def bars(self,*a,**kw):
                rows=super().bars(*a,**kw);rows[-1]['volume']='50';return rows
        probe=run_probe(cfg,reader_factory=VolumeReader,include_bars=True)
        result=score_probe(probe,CryptoProfile(),at_ms=probe['finished_ms'])
        result['scan_config']=asdict(cfg)
        return result
    return OpportunityService(Store(tmp_path/'opportunities.sqlite3'),lambda:holdings,lambda _:None,runner or compute),holdings


def value():
    import json
    return json.loads(json.dumps(config().as_dict()))


def test_job_persistence_filters_and_holdings_are_separate(tmp_path):
    async def run():
        service,holdings=make(tmp_path)
        await service.start(value());await service.task
        assert service.view()['job']['status']=='complete'
        assert len(service.view()['items'])==2
        assert len(service.view(holding='held')['items'])==1
        assert service.view(holding='unheld')['items'][0]['symbol']=='ETH/USDT'
        assert len(service.view(timeframe='1h',strategy='volume_breakout')['items'])==2
        assert not service.view(min_score=100)['items']
        assert not service.view(state='matched')['items']
        holdings['exchange']='binance'
        assert not service.view(holding='held')['items']
        restart,_=make(tmp_path)
        assert len(restart.view()['items'])==2
        assert restart.view()['settings']==service.view()['settings']
        for kwargs in ({'risk':'low'},{'strategy':'unknown'},{'min_score':float('nan')},{'timeframe':'5m'}):
            with pytest.raises(ValueError):service.view(**kwargs)
    asyncio.run(run())


def test_cancel_duplicate_start_and_restart_do_not_resume(tmp_path):
    def wait(cfg,cancel):
        while not cancel.wait(.01):pass
        raise InterruptedError()
    async def run():
        service,_=make(tmp_path,wait)
        await service.start(value())
        with pytest.raises(RuntimeError):await service.start(value())
        await service.cancel();await service.stop()
        assert service.view()['job']['status']=='cancelled'
        assert not service.view()['items']
        with pytest.raises(RuntimeError):await service.start(value())
        service.store.put('job',{'status':'running','started':0})
        restarted,_=make(tmp_path,wait)
        assert restarted.view()['job']['status']=='interrupted' and restarted.task is None
    asyncio.run(run())


def test_failed_refresh_keeps_previous_captured_data(tmp_path):
    async def run():
        service,_=make(tmp_path)
        await service.start(value());await service.task
        previous=service.store.get('result')
        service.store.put('job',{'started':0})
        service.runner=lambda *a:(_ for _ in ()).throw(RuntimeError('private proxy secret'))
        await service.start(value());await service.task
        assert service.view()['job']['status']=='failed'
        assert service.store.get('result')==previous
        assert 'private proxy secret' not in str(service.view())
        invalid=value();invalid['limit']=11
        with pytest.raises(ValueError):await service.start(invalid)
    asyncio.run(run())


def test_api_authentication_and_rejected_filters(tmp_path):
    pytest.importorskip('fastapi')
    from fastapi import FastAPI, Depends, Header, HTTPException
    from fastapi.testclient import TestClient
    from src.modules.crypto.api import router
    async def auth(authorization:str|None=Header(default=None)):
        if authorization!='Bearer qa-only':raise HTTPException(401)
    app=FastAPI();app.state.crypto_workflow=SimpleNamespace(opportunities=make(tmp_path)[0])
    app.include_router(router,prefix='/api/crypto',dependencies=[Depends(auth)])
    with TestClient(app) as client:
        assert client.get('/api/crypto/opportunities').status_code==401
        assert client.post('/api/crypto/opportunities/scans',json=value()).status_code==401
        headers={'Authorization':'Bearer qa-only'}
        assert client.get('/api/crypto/opportunities',headers=headers).status_code==200
        assert client.get('/api/crypto/opportunities?risk=low',headers=headers).status_code==422
        assert client.post('/api/crypto/opportunities/scans',headers=headers,json={**value(),'apiKey':'forbidden'}).status_code==422
