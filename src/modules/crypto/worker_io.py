"""Bounded request/release protocol. Only the host grants network permits."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time


@contextmanager
def child_permit():
    child_permit.sequence+=1
    token=child_permit.sequence
    print(json.dumps({'permit':token}),flush=True)
    if json.loads(sys.stdin.readline(65))!={'grant':token}:
        raise InterruptedError('invalid public request permit')
    try:yield
    finally:print(json.dumps({'release':token}),flush=True)


child_permit.sequence=0


def execute(python,module,payload,*,exchange,coordinator,priority,timeout,proxy=None,cancel=None,options=()):
    if module not in ('public_rpc','scan_worker') or options not in ((),('--with-bars',)):
        raise ValueError('invalid public worker')
    env={key:os.environ[key] for key in ('SystemRoot','WINDIR','TEMP','TMP','PATH','HOME','USERPROFILE') if key in os.environ}
    env['PYTHONUTF8']='1'
    if proxy:env['PANWATCH_CRYPTO_HTTPS_PROXY']=proxy
    deadline=time.monotonic()+timeout
    stop=threading.Event()
    messages=queue.Queue(maxsize=4)
    process=subprocess.Popen([str(Path(python).resolve(strict=True)),'-m','src.modules.crypto.'+module,*options,'--coordinated'],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',env=env,
        cwd=Path(__file__).resolve().parents[3],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    def read():
        while not stop.is_set():
            line=process.stdout.readline(8000001)
            while not stop.is_set():
                try:messages.put(line,timeout=.05);break
                except queue.Full:pass
            if not line or len(line)>8000000:return
    thread=threading.Thread(target=read,daemon=True)
    thread.start()
    lease=None
    token=None
    sequence=0
    try:
        process.stdin.write(json.dumps(payload)+'\n');process.stdin.flush()
        while True:
            if cancel is not None and cancel.is_set():raise InterruptedError('public worker cancelled')
            if time.monotonic()>=deadline:raise TimeoutError('public worker deadline')
            try:line=messages.get(timeout=.05)
            except queue.Empty:continue
            if not line or len(line)>8000000:raise ValueError('invalid public worker response size')
            event=json.loads(line)
            if set(event)=={'permit'}:
                if lease is not None or type(event['permit']) is not int or event['permit']!=sequence+1 or sequence>=1024:
                    raise ValueError('invalid permit sequence')
                token=event['permit'];sequence=token
                context=coordinator.lease(exchange,priority,cancel=cancel,deadline=deadline)
                context.__enter__();lease=context
                process.stdin.write(json.dumps({'grant':token})+'\n');process.stdin.flush()
            elif set(event)=={'release'}:
                if lease is None or event['release']!=token:raise ValueError('invalid release')
                lease.__exit__(None,None,None);lease=None
            elif set(event) in ({'result'},{'error_type'}):
                if lease is not None:raise ValueError('result before request release')
                code=process.wait(timeout=2)
                if code or 'result' not in event:raise RuntimeError('public worker failed')
                return event
            else:raise ValueError('unrecognized public worker message')
    finally:
        # Do not give another reader this lease until the owned worker is stopped.
        if process.poll() is None:
            if os.name=='nt':
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            else:process.kill()
            process.wait(timeout=3)
        stop.set()
        if lease is not None:lease.__exit__(None,None,None)
        process.stdin.close();process.stdout.close();thread.join(timeout=1)
