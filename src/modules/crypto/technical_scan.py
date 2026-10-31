"""Standalone technical ranking over an isolated public universe; no host writes."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

from .adapter import DataUnavailable
from .scan_contracts import UniverseConfig
from .scan_worker import valid_entry
from .universe_probe import collect_probe, save_run
from .strategy_profile import CryptoProfile, score_snapshot
from .technical import build_snapshot, public_snapshot, current


def score_probe(probe,profile,*,at_ms,min_score=0):
    if probe.get('schema_version')!=1 or probe.get('includes_bars') is not True:
        raise ValueError('technical ranking requires verified captured bars')
    if type(min_score) not in (int,float) or not 0<=min_score<=100:
        raise ValueError('minimum score must be 0..100')
    rows,errors,snapshots=[],[],{}
    for item in probe['accepted']:
        try:
            if not valid_entry(item,at_ms=at_ms):
                raise DataUnavailable('expired quote, book or history')
            periods={}
            for captured in item['history']:
                timeframe=captured['timeframe']
                if timeframe not in ('1d','1h') or timeframe in periods:
                    raise DataUnavailable('invalid or duplicate timeframe')
                try:
                    snap=build_snapshot(item['exchange'],item['symbol'],timeframe,captured['bars'],now_ms=at_ms)
                    if snap['bars_sha256']!=captured['bars_sha256']:
                        raise DataUnavailable('captured history fingerprint mismatch')
                    periods[timeframe]={'status':'ok',**score_snapshot(snap,profile,at_ms=at_ms)}
                    snapshots[periods[timeframe]['snapshot_id']]=public_snapshot(snap,now_ms=at_ms)
                except (ValueError,KeyError,TypeError) as exc:
                    periods[timeframe]={'status':'unavailable','error_type':type(exc).__name__}
            primary=periods.get(profile.primary_timeframe,{})
            if primary.get('status')!='ok':
                raise DataUnavailable('primary timeframe unavailable')
            expires=min(item['source_ms']+120000,item['book_source_ms']+15000,
                        *(value['valid_until_ms'] for value in periods.values() if value['status']=='ok'))
            rows.append({'instrument_key':item['instrument_key'],'exchange':item['exchange'],'symbol':item['symbol'],
                'technical_score':primary['technical_score'],'state':primary['state'],'strategy_tags':primary['strategy_tags'],
                'strategy_labels':primary['strategy_labels'],'primary_timeframe':profile.primary_timeframe,'periods':periods,
                'liquidity':{key:item[key] for key in ('source_ms','book_source_ms','quote_volume','spread_pct')},
                'valid_until_ms':expires})
        except (ValueError,KeyError,TypeError) as exc:
            errors.append({'symbol':item.get('symbol'),'status':'unavailable','error_type':type(exc).__name__})
    rows.sort(key=lambda row:(-row['technical_score'],row['instrument_key']))
    return {'schema_version':1,'mode':'crypto-technical-scan','source_run_id':probe['run_id'],
            'status':'partial' if errors else 'complete' if rows else 'no_eligible_data','universe_status':probe['status'],
            'coverage':{key:probe['selection'][key] for key in ('directory_count','market_eligible_count','selected_count','not_scanned_budget_count')},
            'asof_ms':at_ms,'universe_settings_version':probe['settings_version'],'profile':asdict(profile),
            'profile_version':profile.version,'min_score':min_score,'calibrated':False,
            'data_eligible_count':len(rows),'below_min_score_count':sum(row['technical_score']<min_score for row in rows),
            'items':[row for row in rows if row['technical_score']>=min_score],'errors':errors,
            'technical_snapshots':snapshots,'not_claimed':['win_probability','low_risk','stock_rank_equivalence','execution']}


def current_view(result,profile,*,at_ms):
    if result['schema_version']!=1 or result['profile_version']!=profile.version:
        return {**result,'items':[],'historical':True}
    items=[row for row in result['items'] if result['asof_ms']<=at_ms<row['valid_until_ms']
           and all(current(result['technical_snapshots'][period['snapshot_id']],now_ms=at_ms)
                   for period in row['periods'].values() if period['status']=='ok')]
    return {**result,'items':items,'historical':len(items)!=len(result['items']),'view_asof_ms':at_ms}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('config','python','store','output'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--profile')
    parser.add_argument('--min-score',type=float,default=0)
    args=parser.parse_args()
    output=Path(args.output)
    inputs={Path(args.config).resolve(),Path(args.store).resolve()}
    if args.profile:inputs.add(Path(args.profile).resolve())
    if output.exists() or output.resolve() in inputs or Path(args.store).resolve().name.lower() in ('panwatch.db','crypto.sqlite3') or not 0<=args.min_score<=100:
        parser.error('use a new output, dedicated store and valid score threshold')
    config=UniverseConfig.from_dict(json.loads(Path(args.config).read_text(encoding='utf-8')))
    profile=CryptoProfile.from_dict(json.loads(Path(args.profile).read_text(encoding='utf-8'))) if args.profile else CryptoProfile()
    probe=collect_probe(config,args.python,include_bars=True)
    result=score_probe(probe,profile,at_ms=int(time.time()*1000),min_score=args.min_score)
    result=current_view(result,profile,at_ms=int(time.time()*1000))
    save_run(args.store,probe)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps({'source_run_id':probe['run_id'],'data_eligible':result['data_eligible_count'],'items':len(result['items']),'historical':result['historical']}))


if __name__=='__main__':
    main()
