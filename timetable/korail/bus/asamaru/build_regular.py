"""다섯 주(공휴일・추석 빼고) 운행으로 요일 다시 정하기 → asamaru/regular-days.json
· 요일마다 다닌 몫 p 가 반 넘으면 그 요일에 다님 (또는 나중 두 주(10/17∼31)의 그 요일에 빠짐없이 다녔으면: 새로 생긴 차)
· 그런 요일이 없는 차는 임시편: 목록에 싣지 않고 구간 머리에 「임시편 일 9편」(날마다 편수가 ±1 안이면 많은 쪽 하나), 아니면 「금・토에도 있음」"""
import json, os, collections, datetime
CB = os.path.expanduser('~/.cache/tago-bus')
EXP = sorted({(a, b) for k, a, b in json.load(open('/home/claude/korail/bus/tools/need-pairs.json')) if k == 'ExpBusInfo'})
ALL = ['20260928', '20260929', '20260930', '20261001', '20261002', '20261004', '20261006', '20261007', '20261008'] + ['202610%02d' % k for k in range(10, 32)]
LATE = set('202610%02d' % k for k in range(17, 32))
WD = '월화수목금토일'
GR = {'우등': '우', '고속': '일', '프리미엄': '프', '심야우등': '심', '심야프리미엄': '심프', '심야고속': '심일'}
wd = lambda d: datetime.date(int(d[:4]), int(d[4:6]), int(d[6:])).weekday()
G = collections.defaultdict(dict); pdays = collections.defaultdict(set)
for a, b in EXP:
    for d in ALL:
        f = os.path.join(CB, 'p-%s-%s-%s.json' % (d, a, b))
        if not os.path.exists(f): continue
        for r in json.load(open(f)):
            if r['depPlaceNm'] == r['arrPlaceNm']: continue
            k = (r['depPlaceNm'], r['arrPlaceNm'], str(r['depPlandTime'])[8:12])
            G[k][d] = GR.get(r.get('gradeNm', ''), r.get('gradeNm', '')); pdays[k[:2]].add(d)
out, spor = {}, collections.defaultdict(dict)
st = collections.Counter()
for k, dg in G.items():
    obs = pdays[k[:2]]
    if min(collections.Counter(wd(d) for d in obs).get(w, 0) for w in range(7)) < 3: continue
    keep = []
    for w in range(7):
        ow = [d for d in obs if wd(d) == w]; rw = [d for d in ow if d in dg]
        lw = [d for d in ow if d in LATE]
        if len(rw) / len(ow) > 0.5 or (len(lw) >= 2 and all(d in dg for d in lw)): keep.append(w)
    if keep:
        days = []
        for w in range(7):
            gs = collections.Counter(dg[d] for d in dg if wd(d) == w)
            days.append(gs.most_common(1)[0][0] if (w in keep and gs) else (collections.Counter(dg.values()).most_common(1)[0][0] if w in keep else 0))
        out['%s|%s|%s' % k] = {'days': days}; st['정기'] += 1
    else:
        out['%s|%s|%s' % k] = {'sporadic': True}; st['임시'] += 1
        for d in dg: spor[k[:2]].setdefault(wd(d), collections.Counter())[d] += 1
notes = {}
nst = collections.Counter()
for pr, byw in spor.items():
    fixed, loose = [], []
    for w in sorted(byw):
        days = sorted(d for d in pdays[pr] if wd(d) == w)
        ns = [byw[w].get(d, 0) for d in days]
        if sum(ns) >= 2 and max(ns) - min(ns) <= 1: fixed.append('%s %d편' % (WD[w], max(ns))); nst['편수'] += 1
        else: loose.append(WD[w]); nst['있음'] += 1
    def rng(ws):
        ws = sorted(WD.index(x) for x in ws)
        if len(ws) >= 3:
            for s0 in ws:
                if sorted((s0 + k) % 7 for k in range(len(ws))) == ws: return WD[s0] + '∼' + WD[(s0 + len(ws) - 1) % 7]
        return ''.join(WD[w] for w in ws)
    t = '임시편 ' + '・'.join(fixed + ([rng(loose) + ' 수시'] if loose else []))
    notes['%s|%s' % pr] = t
json.dump({'trips': out, 'notes': notes}, open('/home/claude/korail/bus/asamaru/regular-days.json', 'w'), ensure_ascii=False)
print(dict(st), dict(nst), len(notes))
for k in list(notes)[:12]: print(k, notes[k])
