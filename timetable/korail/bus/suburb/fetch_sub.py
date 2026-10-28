#!/usr/bin/env python3
"""책에 실린 고속버스 구간(과 그 반대)마다 TAGO 시외버스정보를 받는다 (시외는 고속과 한도가 따로).
python3 fetch_sub.py 20261017 … 20261030   (열쇠: /root/.config/tago.key, 한도가 차면 tago.key2)"""
import json, sys, os, re, time, urllib.request, urllib.parse, concurrent.futures as cf, itertools
KEYS = [open('/root/.config/tago.key').read().strip(), open('/root/.config/tago.key2').read().strip()]
ki = [0]
C = os.path.expanduser('~/.cache/tago-sub'); os.makedirs(C, exist_ok=True)
days = sys.argv[1:]
m = json.load(open('map.json'))
b = json.load(open('/home/claude/korail/bus/asamaru/bus.json'))
pairs = {(o['from'], x['to']) for o in b['origins'] for x in o['dests']}
pairs |= {(d, a) for a, d in pairs}
jobs = [(a, d, ia, idd, day) for a, d in sorted(pairs) if a in m and d in m for (_, ia), (_, idd) in itertools.product(m[a], m[d]) if ia != idd for day in days]
if os.environ.get('JOBS'): jobs = [('', '', x, y, day) for x, y in json.load(open(os.environ['JOBS'])) for day in days]      # 전환시외 노선의 터미널 짝
def get(j):
    a, d, ia, idd, day = j
    ck = os.path.join(C, '%s-%s-%s.json' % (day, ia, idd))
    if os.path.exists(ck): return 'c'
    for t in range(5):
        q = urllib.parse.urlencode(dict(serviceKey=KEYS[ki[0]], _type='json', numOfRows=300, pageNo=1, depTerminalId=ia, arrTerminalId=idd, depPlandTime=day))
        try:
            raw = urllib.request.urlopen('https://apis.data.go.kr/1613000/SuburbsBusInfo/GetStrtpntAlocFndSuberbsBusInfo?' + q, timeout=40).read().decode()
            if 'LIMITED_NUMBER' in raw:
                if ki[0] + 1 < len(KEYS): ki[0] += 1; continue
                return 'q'
            jj = json.loads(raw); bd = jj['response']['body']; it = bd.get('items') or {}
            it = it.get('item', []) if isinstance(it, dict) else []
            it = it if isinstance(it, list) else [it]
            json.dump(it, open(ck, 'w'), ensure_ascii=False); return 'ok'
        except Exception:
            time.sleep(1 + 2 * t)
    return 'f'
import collections
cnt = collections.Counter()
with cf.ThreadPoolExecutor(6) as ex:
    for k, r in enumerate(ex.map(get, jobs)):
        cnt[r] += 1
        if k % 500 == 0: print(k, len(jobs), dict(cnt), file=sys.stderr, flush=True)
print('done', len(jobs), dict(cnt), file=sys.stderr)
