"""pairs-ids.json 의 구간마다 TAGO 고속버스 운행을 받는다: python3 fetch_pairs.py 20261029 > trips.json"""
import json, sys, os, time, urllib.request, urllib.parse, concurrent.futures as cf
KEY = open(os.environ.get('TAGO_KEY', '/root/.config/tago.key')).read().strip()
day = sys.argv[1]
CACHE = os.path.expanduser('~/.cache/tago-bus'); os.makedirs(CACHE, exist_ok=True)
def get(dep, arr):
    ck = os.path.join(CACHE, 'p-%s-%s-%s.json' % (day, dep, arr))
    if os.path.exists(ck): return json.load(open(ck))
    q = urllib.parse.urlencode(dict(serviceKey=KEY, _type='json', numOfRows=300, pageNo=1, depTerminalId=dep, arrTerminalId=arr, depPlandTime=day))
    for t in range(4):
        try:
            j = json.loads(urllib.request.urlopen('https://apis.data.go.kr/1613000/ExpBusInfo/GetStrtpntAlocFndExpbusInfo?' + q, timeout=40).read().decode())
            b = j['response']['body']; it = b.get('items') or {}
            it = it.get('item', []) if isinstance(it, dict) else []
            it = it if isinstance(it, list) else [it]
            json.dump(it, open(ck, 'w'), ensure_ascii=False); return it
        except Exception as e:
            err = e; time.sleep(1 + 2 * t)
    return None
todo = [(a, b, x, y) for a, b, ia, ib in json.load(open(sys.argv[2] if len(sys.argv) > 2 else 'pairs-ids.json')) for x in ia for y in ib]
out, miss = [], 0
with cf.ThreadPoolExecutor(6) as ex:
    for (a, b, x, y), it in zip(todo, ex.map(lambda t: get(t[2], t[3]), todo)):
        if it is None: miss += 1; continue
        for r in it: out.append(dict(r, depId=x, arrId=y, depSite=a, arrSite=b))
print('calls', len(todo), 'trips', len(out), 'failed', miss, file=sys.stderr)
json.dump(out, sys.stdout, ensure_ascii=False)
