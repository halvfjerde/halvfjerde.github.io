"""기준 없이: 차마다 요일 칸마다 다닌 몫 p (그 요일을 본 날 가운데 다닌 날). 칸의 흔들림 = 4p(1−p) (늘 다님・늘 안 다님 0, 반반 1).
차의 불일치 지수 = 일곱 칸 흔들림의 평균. 차의 유형 = 반 넘게 다닌 요일들. 유형마다 지수 평균과 요일마다 p 평균"""
import json, os, collections, datetime, sys
CB = os.path.expanduser('~/.cache/tago-bus')
EXP = sorted({(a, b) for k, a, b in json.load(open('/home/claude/korail/bus/tools/need-pairs.json')) if k == 'ExpBusInfo'})
ALL = ['20260928', '20260929', '20260930', '20261001', '20261002', '20261004', '20261006', '20261007', '20261008'] + ['202610%02d' % k for k in range(10, 32)]
WD = '월화수목금토일'
wd = lambda d: datetime.date(int(d[:4]), int(d[4:6]), int(d[6:])).weekday()
def dtext(ws):
    ws = sorted(ws)
    if len(ws) == 7: return '매일'
    if not ws: return '(반 넘는 날 없음)'
    if ws == [0, 1, 2, 3, 4]: return '월∼금'
    if len(ws) >= 3:
        for s0 in ws:
            if sorted((s0 + k) % 7 for k in range(len(ws))) == ws: return WD[s0] + '∼' + WD[(s0 + len(ws) - 1) % 7]
    return ''.join(WD[w] for w in ws)
G = collections.defaultdict(set); pdays = collections.defaultdict(set)
for a, b in EXP:
    for d in ALL:
        f = os.path.join(CB, 'p-%s-%s-%s.json' % (d, a, b))
        if not os.path.exists(f): continue
        for r in json.load(open(f)):
            if r['depPlaceNm'] == r['arrPlaceNm']: continue
            G[(r['depPlaceNm'], r['arrPlaceNm'], str(r['depPlandTime'])[8:12])].add(d); pdays[(r['depPlaceNm'], r['arrPlaceNm'])].add(d)
grp = collections.defaultdict(list); nobs = collections.Counter()
for k, ds in G.items():
    obs = pdays[k[:2]]
    av = collections.Counter(wd(d) for d in obs)
    if min(av.get(w, 0) for w in range(7)) < 3: continue          # 요일마다 세 번은 본 구간만
    p = [sum(1 for d in ds if wd(d) == w) / av[w] for w in range(7)]
    ix = sum(4 * x * (1 - x) for x in p) / 7
    grp[dtext([w for w in range(7) if p[w] > 0.5])].append((ix, p))
    for w in range(7): nobs[av[w]] += 1
rows = sorted(grp.items(), key=lambda kv: -sum(x[0] for x in kv[1]) / len(kv[1]))
print('| 유형(반 넘게 다닌 요일) | 차 | 불일치 지수 | 흔들림 없는 차 | ' + ' | '.join(WD) + ' |')
print('|---|---:|---:|---:|' + '---:|' * 7)
oth = []
for t, v in rows:
    if len(v) < 30: oth += v; continue
    n = len(v)
    print('| %s | %d | %.2f | %d%% | ' % (t, n, sum(x[0] for x in v) / n, round(100 * sum(1 for x in v if x[0] == 0) / n)) + ' | '.join('%.2f' % (sum(x[1][w] for x in v) / n) for w in range(7)) + ' |')
if oth:
    n = len(oth)
    print('| 그 밖 (30편 안 되는 유형들) | %d | %.2f | %d%% | ' % (n, sum(x[0] for x in oth) / n, round(100 * sum(1 for x in oth if x[0] == 0) / n)) + ' | '.join('%.2f' % (sum(x[1][w] for x in oth) / n) for w in range(7)) + ' |')
print('관측 횟수(요일 칸)', dict(sorted(nobs.items())), file=sys.stderr)
