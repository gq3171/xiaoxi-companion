"""Stop bounded no-progress loops; new evidence and real mutations reset errors."""
import hashlib,json
from collections import Counter,deque

class ProgressGuard:
    def __init__(self):self.seen=set();self.recent=deque(maxlen=12);self.errors=0;self.navigation_misses={}
    def navigation(self,result):
        if result.get("navigation_observed"):
            self.navigation_misses.clear();return False,False
        if not result.get("no_navigation"):return False,False
        key=result.get("requested_url", "unknown");count=self.navigation_misses.get(key,0)+1;self.navigation_misses[key]=count
        return count>=2,count>=4
    def stalled(self,action,result,code,mutation=False,verified=False):
        if not code and (mutation or verified):
            self.errors=0;self.recent.clear();return False
        digest=hashlib.sha256(json.dumps([action,result],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        repeated=digest in self.seen;self.seen.add(digest);self.recent.append(digest)
        if code:self.errors+=1
        elif mutation or verified or not repeated:self.errors=0
        return self.errors>=4 or Counter(self.recent)[digest]>=4
