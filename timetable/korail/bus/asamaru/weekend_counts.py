"""드문 차(어느 요일도 반 넘게 다니지 않은 차)가 날마다 몇 편인지: 시각은 바뀌어도 편수는 일정한가"""
import json, os, collections, datetime
CB = os.path.expanduser('~/.cache/tago-bus')
EXP = sorted({(a, b) for k, a, b in json.load(open('/home/claude/korail/bus/tools/need-pairs.json')) if k == 'ExpBusInfo'})
ALL = ['20260928', '20260929', '20260930', '20261001', '20261002', '20261004', '20261006', '20261007', '20261008'] + ['202610%02d' % k for k in range(10, 32)]
WD = '월화수목금토일'
wd = lambda d: datetime.date(int(d[:4]), int(d[4:6]), int(d[6:])).weekday()
mm = lambda s: int(s[:2]) * 60 + int(s[2:])
G = collections.defaultdict(set); pdays = collections.defaultdict(set)
for a, b in EXP:
    for d in ALL:
        f = os.path.join(CB, 'p-%s-%s-%s.json' % (d, a, b))
        if not os.path.exists(f): continue
        for r in json.load(open(f)):
            if r['depPlaceNm'] == r['arrPlaceNm']: continue
            G[(r['depPlaceNm'], r['arrPlaceNm'], str(r['depPlandTime'])[8:12])].add(d); pdays[(r['depPlaceNm'], r['arrPlaceNm'])].add(d)
spor = {}
for k, ds in G.items():
    av = collections.Counter(wd(d) for d in pdays[k[:2]])
    if min(av.get(w, 0) for w in range(7)) < 3: continue
    p = [sum(1 for d in ds if wd(d) == w) / av[w] for w in range(7)]
    if max(p) <= 0.5: spor[k] = ds
# 구간・요일마다 날짜별 드문 차 편수
cell = collections.defaultdict(lambda: collections.Counter())
for k, ds in spor.items():
    for d in ds: cell[(k[:2], wd(d))][d] += 1
stat = collections.Counter(); ex = collections.defaultdict(list)
for (pr, w), c in cell.items():
    days = sorted(d for d in pdays[pr] if wd(d) == w)
    ns = [c.get(d, 0) for d in days]
    if sum(ns) < 2: stat['한 번뿐'] += 1; continue
    kind = '편수 같음' if max(ns) == min(ns) else ('±1' if max(ns) - min(ns) == 1 else '들쭉날쭉')
    stat[kind] += 1; ex[kind].append((pr, WD[w], ns))
print({k: v for k, v in stat.items()})
for k in ('편수 같음', '±1', '들쭉날쭉'):
    print('##', k)
    for e in sorted(ex[k], key=lambda e: -sum(e[2]))[:8]: print('  ', e)
# 시각이 바뀐 것인가: 드문 차가 다른 주 같은 요일의 드문 차와 ±20분 안에 있는가
near = collections.Counter()
by = collections.defaultdict(list)
for k, ds in spor.items():
    for d in ds: by[(k[:2], wd(d))].append((d, mm(k[2])))
for key, lst in by.items():
    for d, t in lst:
        others = [t2 for d2, t2 in lst if d2 != d]
        near['다른 주 ±20분에 짝 있음' if any(abs(t - t2) <= 20 for t2 in others) else '짝 없음'] += 1
print(dict(near))
