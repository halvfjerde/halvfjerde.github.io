#!/usr/bin/env python3
"""TAGO 열차정보로 착발역 도착 시각을 찾는다.  python3 tago.py need-arrivals.json arrivals.json
열쇠는 /root/.config/tago.key (저장소에 넣지 않는다)"""
import json, sys, time, urllib.request, urllib.parse, collections, os
KEY = open('/root/.config/tago.key').read().strip()
BASE = 'https://apis.data.go.kr/1613000/TrainInfo/'          # 옛 TrainInfoService 는 폐기 (2026년에 새 경로, 기능 이름은 대문자로 시작)
CACHE = '/root/.cache/tago'; os.makedirs(CACHE, exist_ok=True)
calls = 0
def api(op, **kw):
    global calls
    kw.update(serviceKey=KEY, _type='json', numOfRows=kw.get('numOfRows', 500), pageNo=1)
    q = urllib.parse.urlencode(kw)
    ck = os.path.join(CACHE, op + '-' + urllib.parse.quote(urllib.parse.urlencode(sorted((k, v) for k, v in kw.items() if k != 'serviceKey')), safe=''))[:250]
    if os.path.exists(ck): return json.load(open(ck))
    for tries in range(3):
        try:
            with urllib.request.urlopen(BASE + op[0].upper() + op[1:] + '?' + q, timeout=30) as r: raw = r.read().decode('utf-8')
            j = json.loads(raw); calls += 1
            json.dump(j, open(ck, 'w'), ensure_ascii=False)
            time.sleep(0.15)
            return j
        except Exception as e:
            err = e; time.sleep(2)
    raise SystemExit('API 오류: %s %s' % (op, err))
def items(j):
    b = j.get('response', {}).get('body', {})
    it = (b.get('items') or {})
    it = it.get('item', []) if isinstance(it, dict) else []
    return it if isinstance(it, list) else [it]

need = json.load(open(sys.argv[1]))
# 역 이름 → 역 ID
st = {}
for c in items(api('getCtyCodeList')):
    for s in items(api('getCtyAcctoTrainSttnList', cityCode=c['citycode'])):
        st.setdefault(s['nodename'], s['nodeid'])
names = {n[1] for n in need} | {n[2] for n in need}
alias = lambda n: n if n in st else n.replace('(경기)', '').replace('(오대산)', '') if n.replace('(경기)', '').replace('(오대산)', '') in st else None
miss = sorted(n for n in names if not alias(n))
if miss: print('역 ID 못 찾음:', miss)
pairs = collections.defaultdict(dict)
for n in need: pairs[(n[1], n[2])][n[0]] = n[3] if len(n) > 3 else None   # 열차번호 → 시발 시각(분)
DATES = sys.argv[3].split(',') if len(sys.argv) > 3 else ['20261104', '20261107']
arr = {}
for (o, x), nos in sorted(pairs.items()):
    if not alias(o) or not alias(x): continue
    for d in DATES:
        if all(f'{n}@{x}' in arr for n in nos): break
        for it in items(api('getStrtpntAlocFndTrainInfo', depPlaceId=st[alias(o)], arrPlaceId=st[alias(x)], depPlandTime=d)):
            no = str(it.get('trainno', '')).lstrip('0')
            if no in nos and f'{no}@{x}' not in arr:
                dt = str(it['depplandtime'])[8:12]; t = str(it['arrplandtime'])[8:12]
                # 시발 시각이 시각표와 같은 날의 열차만 (개정 전 날짜·다른 요일판 거르기)
                if nos[no] is not None and int(dt[:2]) * 60 + int(dt[2:]) != nos[no] % 1440: continue
                arr[f'{no}@{x}'] = int(t[:2]) * 60 + int(t[2:])
json.dump(arr, open(sys.argv[2], 'w'), ensure_ascii=False, indent=0)
left = [n for n in need if f'{n[0]}@{n[2]}' not in arr]
json.dump(left, open(sys.argv[2] + '.left', 'w'), ensure_ascii=False)
print('찾음', len(arr), '/', len(need), '· 호출', calls, '· 남음', left[:20])
