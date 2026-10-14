"""Bounded exact filter reuse with pixel content and width in its cache key."""
import hashlib,threading
from collections import OrderedDict
import cv2
_CACHE=OrderedDict();_LOCK=threading.RLock();BUDGET=192*1024**2
def surfaces(source,width):
    key=(source.shape,float(width),hashlib.blake2b(source.tobytes(),digest_size=16).digest())
    with _LOCK:
        if key in _CACHE:
            value=_CACHE.pop(key);_CACHE[key]=value;return value
        fine=cv2.GaussianBlur(source,(0,0),max(.65,width*.0035));low=cv2.bilateralFilter(fine,0,22,max(2,width*.015))
        fine.flags.writeable=False;low.flags.writeable=False
        if fine.nbytes+low.nbytes<=BUDGET:
            _CACHE[key]=(fine,low)
            while sum(a.nbytes+b.nbytes for a,b in _CACHE.values())>BUDGET:_CACHE.popitem(last=False)
        return fine,low
