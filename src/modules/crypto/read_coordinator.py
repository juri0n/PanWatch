"""Host-wide public-request priority: holdings/alerts before background scans."""
from contextlib import contextmanager
import threading
import time

from .adapter import EXCHANGES


class ReadCoordinator:
    def __init__(self,minimum_gap=1.0):
        self.gap=minimum_gap
        self.condition=threading.Condition()
        self.waiters=[]
        self.active=set()
        self.next_allowed={}
        self.sequence=0

    @contextmanager
    def lease(self,exchange,priority,*,cancel=None,deadline=None):
        if exchange not in EXCHANGES or priority not in (0,1):
            raise ValueError('invalid public request priority')
        acquired=False
        with self.condition:
            self.sequence+=1
            token=(priority,self.sequence,exchange)
            self.waiters.append(token)
            try:
                while True:
                    now=time.monotonic()
                    if cancel is not None and cancel.is_set():raise InterruptedError('request cancelled')
                    if deadline is not None and now>=deadline:raise TimeoutError('request budget expired')
                    first=min(row for row in self.waiters if row[2]==exchange)
                    if first==token and exchange not in self.active and now>=self.next_allowed.get(exchange,0):
                        self.waiters.remove(token)
                        self.active.add(exchange)
                        acquired=True
                        break
                    self.condition.wait(.05)
            finally:
                if not acquired:self.waiters.remove(token)
        try:
            yield
        finally:
            with self.condition:
                self.active.remove(exchange)
                self.next_allowed[exchange]=time.monotonic()+self.gap
                self.condition.notify_all()


COORDINATOR=ReadCoordinator()
