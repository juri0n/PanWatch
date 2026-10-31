"""Explicit standalone CLI; never starts a scheduler or alters production settings."""
import argparse
from contextlib import closing
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from .scan_contracts import UniverseConfig
from .scan_worker import valid_entry
from .universe import statistics, spread
from .adapter import number, TIMEFRAMES, utc_ms
from .contracts import Instrument


def collect_probe(config, python, *, https_proxy=None):
    env={key:os.environ[key] for key in ('SystemRoot','WINDIR','TEMP','TMP','PATH','HOME','USERPROFILE') if key in os.environ}
    env['PYTHONUTF8']='1'
    proxy=https_proxy or os.environ.get('PANWATCH_CRYPTO_HTTPS_PROXY')
    if proxy:
        env['PANWATCH_CRYPTO_HTTPS_PROXY']=proxy
    result=subprocess.run([str(Path(python).resolve(strict=True)),'-m','src.modules.crypto.scan_worker'],
        input=json.dumps(config.as_dict()),capture_output=True,text=True,encoding='utf-8',
        env=env,cwd=Path(__file__).resolve().parents[3],timeout=config.deadline_seconds+20,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode or len(result.stdout)>8000000:
        raise RuntimeError('isolated universe probe failed')
    envelope=json.loads(result.stdout)
    if set(envelope)!={'result'}:
        raise ValueError('invalid public probe response')
    data=envelope['result']
    received_ms=int(time.time()*1000)
    if not utc_ms(data['started_ms'])<=utc_ms(data['finished_ms'])<=received_ms or data['finished_ms']-data['started_ms']>(config.deadline_seconds+20)*1000:
        raise ValueError('invalid probe observation times')
    received=UniverseConfig.from_dict(data['config'])
    if received!=config or data['settings_version']!=config.version:
        raise ValueError('probe configuration identity mismatch')
    symbols=[row['symbol'] for row in data['entries']]
    if len(symbols)!=len(set(symbols)) or len(symbols)>config.limit:
        raise ValueError('probe coverage identity mismatch')
    selected={row['symbol'] for row in data['selection']['selected']}
    if set(symbols)!=selected or data['schema_version']!=1 or data['mode']!='public-universe-probe':
        raise ValueError('probe selection mismatch')
    for item in data['entries']:
        if (item['exchange']!=config.exchange or item['quote_currency']!=config.quote_currency
                or item['instrument_key']!=Instrument(config.exchange,item['symbol']).key):
            raise ValueError('probe instrument identity mismatch')
    accepted=[]
    for item in data['accepted']:
        if item not in data['entries'] or item['status']!='eligible' or item['reasons']:
            raise ValueError('unverified accepted entry')
        stat=statistics({'symbol':item['symbol'],'source_ms':item['source_ms'],'last':item['price'],
                         'quote_volume':item['quote_volume'],'quote_volume_source':item['quote_volume_source']},
                        item['symbol'],config,now_ms=data['finished_ms'])
        book=spread({'symbol':item['symbol'],'source_ms':item['book_source_ms'],'bid':item['bid'],'ask':item['ask']},
                    item['symbol'],now_ms=data['finished_ms'])
        if not stat['liquid'] or Decimal(book['spread_pct'])>number(config.max_spread_pct) or book['spread_pct']!=item['spread_pct'] or not valid_entry(item,at_ms=data['finished_ms']):
            raise ValueError('accepted entry failed host validation')
        accepted.append(item['symbol'])
    if len(accepted)!=len(set(accepted)) or data['accepted_count']!=len(accepted):
        raise ValueError('accepted coverage mismatch')
    data['received_ms']=received_ms
    data['accepted_asof_ms']=data['finished_ms']
    return data


def save_run(path, result):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables-{'universe_runs'}:
            raise ValueError('use a dedicated universe database')
        db.execute('CREATE TABLE IF NOT EXISTS universe_runs (id TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.execute('INSERT INTO universe_runs VALUES (?,?)',(result['run_id'],json.dumps(result,allow_nan=False)))
        db.execute('DELETE FROM universe_runs WHERE rowid NOT IN (SELECT rowid FROM universe_runs ORDER BY rowid DESC LIMIT 20)')


def load_run(path, run_id, *, at_ms):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        row=db.execute('SELECT value FROM universe_runs WHERE id=?',(run_id,)).fetchone()
    if row is None:
        raise KeyError(run_id)
    result=json.loads(row[0])
    original_count=len(result['accepted'])
    result['accepted']=[item for item in result['accepted'] if valid_entry(item,at_ms=at_ms)]
    for item in result['entries']:
        if item['status']=='eligible' and not valid_entry(item,at_ms=at_ms):
            item['status']='stale'
        for history in item['history']:
            if history['status']=='ok' and history['source_close_ms']!=at_ms//TIMEFRAMES[history['timeframe']]*TIMEFRAMES[history['timeframe']]:
                history['status']='stale'
    result['accepted_count']=len(result['accepted'])
    result['view_asof_ms']=at_ms
    result['historical']=at_ms>result['finished_ms']+15000 or original_count!=result['accepted_count']
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    parser.add_argument('--python',required=True,help='Administrator-selected isolated CCXT interpreter')
    parser.add_argument('--store',required=True,help='Dedicated probe SQLite file; never crypto.sqlite3/panwatch.db')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    if Path(args.store).resolve().name.lower() in {'crypto.sqlite3','panwatch.db'}:
        parser.error('use a dedicated probe database')
    output=Path(args.output)
    if output.exists() or output.resolve() in {Path(args.store).resolve(),Path(args.config).resolve()}:
        parser.error('output must be a new file separate from config and database')
    try:
        config=UniverseConfig.from_dict(json.loads(Path(args.config).read_text(encoding='utf-8')))
        result=collect_probe(config,args.python)
        save_run(args.store,result)
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('x',encoding='utf-8') as handle:
            json.dump(result,handle,ensure_ascii=False,indent=2,allow_nan=False)
        print(json.dumps({'run_id':result['run_id'],'status':result['status'],'selected':result['selection']['selected_count'],'eligible':result['accepted_count']}))
        return 0
    except Exception as exc:
        print(json.dumps({'error_type':type(exc).__name__}),file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
