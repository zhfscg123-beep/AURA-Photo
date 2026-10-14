"""One worker, latest request wins. No Tk objects cross the thread boundary."""
import copy, threading, traceback
import numpy as np

class Value:
    def __init__(self, value=None): self.value=value
    def get(self): return self.value
    def set(self, value): self.value=value

def detached(value, memo=None):
    """Clone containers/analysis objects; immutable image buffers use read-only views."""
    memo={} if memo is None else memo
    if id(value) in memo:return memo[id(value)]
    if isinstance(value,np.ndarray):
        out=value.view();out.flags.writeable=False;memo[id(value)]=out;return out
    if isinstance(value,dict):
        out={};memo[id(value)]=out;out.update((k,detached(v,memo)) for k,v in value.items());return out
    if isinstance(value,list):
        out=[];memo[id(value)]=out;out.extend(detached(v,memo) for v in value);return out
    if isinstance(value,tuple):return tuple(detached(v,memo) for v in value)
    if hasattr(value,'__dict__') and type(value).__module__ in ('core','photo_document','damo_engine','editing','ai_engine'):
        out=copy.copy(value);memo[id(value)]=out;out.__dict__={k:detached(v,memo) for k,v in vars(value).items()};return out
    return value

class LatestRenderer:
    def __init__(self):
        self.condition=threading.Condition();self.generation=0;self.pending=None;self.running=False;self.result=None;self.closed=False
        self.thread=threading.Thread(target=self._run,name='AURA-render',daemon=True);self.thread.start()
    def submit(self,fn):
        with self.condition:
            if self.closed:raise RuntimeError('Render queue is closed')
            self.generation+=1;self.pending=(self.generation,fn);self.result=None;self.condition.notify_all();return self.generation
    def invalidate(self):
        with self.condition:
            self.generation+=1;self.pending=None;self.result=None;self.condition.notify_all()
    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.pending is not None or self.closed)
                if self.closed:return
                generation,fn=self.pending;self.pending=None;self.running=True
            try:result=(generation,fn(),None)
            except Exception:result=(generation,None,traceback.format_exc())
            with self.condition:
                if generation==self.generation:self.result=result
                self.running=False;self.condition.notify_all()
            del fn,result
    def take(self,wait=False):
        with self.condition:
            if wait:self.condition.wait_for(lambda:self.pending is None and not self.running)
            result=self.result;self.result=None;return result
    def close(self):
        with self.condition:self.closed=True;self.pending=None;self.condition.notify_all()
