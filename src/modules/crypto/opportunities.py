"""Authenticated manual scan jobs; independent persistence and no notifications."""
import asyncio
from dataclasses import asdict
import sys
import threading
import time
import uuid
from collections import Counter

from .adapter import number
from .read_coordinator import COORDINATOR
from .scan_contracts import UniverseConfig
from .strategy_profile import CryptoProfile, LABELS
from .technical_scan import score_probe, current_view
from .universe_probe import collect_probe


class OpportunityService:
    def __init__(self,store,holdings,reader_factory,runner=None):
        self.store,self.holdings,self.reader_factory=store,holdings,reader_factory
        self.runner=runner or self.compute
        self.task=None
        self.cancel_event=threading.Event()
        job=store.get('job',{})
        if job.get('status') in ('running','cancelling'):
            store.put('job',{**job,'status':'interrupted'})

    def settings(self):
        default=UniverseConfig(self.holdings().get('exchange','okx'),'USDT',10,'10000000','0.3',('BTC','ETH'),180)
        return self.store.get('settings',asdict(default))

    async def start(self,value):
        config=UniverseConfig.from_dict(value)
        if config.limit>10:raise ValueError('Initial production trial supports at most ten pairs')
        if self.task and not self.task.done():raise RuntimeError('A scan is already active')
        previous=self.store.get('job',{})
        if time.time()-previous.get('started',0)<60:raise RuntimeError('Wait before starting another scan')
        self.cancel_event=threading.Event()
        job={'id':uuid.uuid4().hex,'status':'running','started':time.time()}
        self.store.put('settings',asdict(config));self.store.put('job',job)
        self.task=asyncio.create_task(self.run(config,job))
        return job

    def compute(self,config,cancel):
        reader=self.reader_factory(config.exchange)
        probe=collect_probe(config,getattr(reader,'python',sys.executable),https_proxy=getattr(reader,'proxy',None),
                            include_bars=True,coordinator=COORDINATOR,cancel=cancel)
        if cancel.is_set():raise InterruptedError('scan cancelled')
        result=score_probe(probe,CryptoProfile(),at_ms=int(time.time()*1000))
        result['scan_config']=asdict(config)
        result['probe_coverage']={**probe['coverage'],'accepted_at_capture':probe['accepted_count']}
        reasons=Counter(row['reason'] for row in probe['selection']['exclusions'])
        for row in probe['selection']['exclusions']:
            if row.get('native_turnover_reported') is False:reasons['native_turnover_missing']+=1
            if row.get('source_timestamp_present') is False:reasons['statistics_time_missing']+=1
        for row in probe['entries']:
            reasons.update(row['reasons'])
            if row.get('book_source_timestamp_present') is False:reasons['book_time_missing']+=1
        result['exclusions']=dict(reasons)
        return result

    async def run(self,config,job):
        try:
            result=await asyncio.to_thread(self.runner,config,self.cancel_event)
            if self.cancel_event.is_set():raise InterruptedError('scan cancelled')
            self.store.put('result',result)
            job.update(status='complete',finished=time.time())
        except InterruptedError:job.update(status='cancelled',finished=time.time())
        except Exception as exc:job.update(status='failed',error_type=type(exc).__name__,finished=time.time())
        finally:self.store.put('job',job)

    async def cancel(self):
        if self.task and not self.task.done():
            self.cancel_event.set()
            self.store.put('job',{**self.store.get('job'),'status':'cancelling'})
        return self.store.get('job',{})

    async def stop(self):
        await self.cancel()
        if self.task:await asyncio.wait_for(asyncio.shield(self.task),timeout=10)

    def view(self,*,timeframe='1d',strategy='all',holding='all',state='all',freshness='all',risk='all',min_score=0):
        if (timeframe not in ('1d','1h') or strategy not in ('all',*LABELS) or holding not in ('all','held','unheld')
                or state not in ('all','matched','watch','excluded') or freshness not in ('all','current','historical')
                or risk not in ('all','unknown') or type(min_score) not in (int,float) or not 0<=min_score<=100):
            raise ValueError('invalid opportunity filters')
        result=self.store.get('result')
        now=int(time.time()*1000)
        current_keys=set()
        if result and result.get('scan_config')==self.settings():
            current_keys={row['instrument_key'] for row in current_view(result,CryptoProfile(),at_ms=now)['items']}
        held=self.holdings()
        held_keys={f"CRYPTO:{held['exchange']}:{p['symbol']}" for p in held.get('positions',[]) if number(p['quantity'])>0}
        items=[]
        for row in (result or {}).get('items',[]):
            period=row['periods'].get(timeframe,{})
            if period.get('status')!='ok':continue
            is_held=row['instrument_key'] in held_keys
            fresh=row['instrument_key'] in current_keys
            if (period['technical_score']<min_score or (strategy!='all' and strategy not in period['strategy_tags'])
                    or (holding=='held' and not is_held) or (holding=='unheld' and is_held)
                    or (state!='all' and period['state']!=state) or (freshness=='current' and not fresh) or (freshness=='historical' and fresh)):
                continue
            items.append({'instrument_key':row['instrument_key'],'symbol':row['symbol'],'exchange':row['exchange'],
                'held':is_held,'fresh':fresh,'liquidity':row['liquidity'],'period':period,
                'snapshot':result['technical_snapshots'][period['snapshot_id']]})
        items.sort(key=lambda row:(-row['period']['technical_score'],row['instrument_key']))
        return {'settings':self.settings(),'job':self.store.get('job',{}),'items':items,'asof_ms':(result or {}).get('asof_ms'),
                'coverage':(result or {}).get('coverage',{}),'probe_coverage':(result or {}).get('probe_coverage',{}),
                'scan_config':(result or {}).get('scan_config'),'captured_count':len((result or {}).get('items',[])),
                'current_count':len(current_keys),'risk_level':'unknown','calibrated':False,
                'exclusions':(result or {}).get('exclusions',{}),'probe_status':(result or {}).get('universe_status')}
