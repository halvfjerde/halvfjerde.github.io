#!/usr/bin/env python3
"""TAGO 국내항공운항정보로 한 달치 운항을 받는다: python3 fetch.py 202611 > flights.json
공항 쌍마다 그달 1일에 편이 있으면 그 달의 모든 날을 받는다. 받은 것은 ~/.cache/tago-air 에"""
import json, sys, os, time, urllib.request, urllib.parse, calendar, concurrent.futures as cf
KEY = open('/root/.config/tago.key').read().strip()
BASE = 'https://apis.data.go.kr/1613000/DmstcFlightNvgInfo/'
CACHE = os.path.expanduser('~/.cache/tago-air'); os.makedirs(CACHE, exist_ok=True)
def api(op, **kw):
    kw.update(serviceKey=KEY, _type='json', numOfRows=kw.get('numOfRows', 500), pageNo=1)
    ck = os.path.join(CACHE, op + '-' + '-'.join('%s=%s' % (k, v) for k, v in sorted(kw.items()) if k not in ('serviceKey', '_type', 'pageNo')))
    if os.path.exists(ck): return json.load(open(ck))
    u = BASE + op + '?' + urllib.parse.urlencode(kw)
    for t in range(5):
        try:
            j = json.loads(urllib.request.urlopen(u, timeout=40).read().decode())
            if 'response' in j: json.dump(j, open(ck, 'w'), ensure_ascii=False); return j
        except Exception: pass
        time.sleep(1 + 2 * t)
    return None
def items(j):
    if not j: return None
    b = j.get('response', {}).get('body', {}); it = b.get('items') or {}
    it = it.get('item', []) if isinstance(it, dict) else []
    return it if isinstance(it, list) else [it]
ym = sys.argv[1]; y, m = int(ym[:4]), int(ym[4:])
days = ['%s%02d' % (ym, d) for d in range(1, calendar.monthrange(y, m)[1] + 1)]
aps = {a['airportId']: a['airportNm'] for a in items(api('GetArprtList'))}
pairs = [(a, b) for a in aps for b in aps if a != b]
def probe(p):
    hits = 0
    for d in (days[0], days[7], days[14]):        # 세 날 가운데 하나라도 편이 있으면
        r = items(api('GetFlightOpratInfoList', depAirportId=p[0], arrAirportId=p[1], depPlandTime=d))
        if r: return p
    return None
with cf.ThreadPoolExecutor(4) as ex: live = [p for p in ex.map(probe, pairs) if p]
print('pairs', len(live), file=sys.stderr)
out = {'airports': aps, 'month': ym, 'flights': []}
def day_pair(arg):
    (a, b), d = arg
    r = items(api('GetFlightOpratInfoList', depAirportId=a, arrAirportId=b, depPlandTime=d))
    return a, b, d, r
miss = []
with cf.ThreadPoolExecutor(4) as ex:
    for a, b, d, r in ex.map(day_pair, [(p, d) for p in live for d in days]):
        if r is None: miss.append((a, b, d)); continue
        for f in r:
            out['flights'].append({'dep': a, 'arr': b, 'day': d, 'no': f.get('vihicleId'), 'air': f.get('airlineNm'),
                                   't': str(f['depPlandTime'])[8:12], 'a': str(f['arrPlandTime'])[8:12]})
out['missing'] = miss
print('flights', len(out['flights']), 'missing', len(miss), file=sys.stderr)
json.dump(out, sys.stdout, ensure_ascii=False)
