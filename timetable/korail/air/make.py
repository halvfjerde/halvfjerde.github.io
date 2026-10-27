#!/usr/bin/env python3
"""flights-YYYYMM.json(fetch.py) → 책에 싣는 항공 목록 air.json: 공항 쌍마다 가는 편·오는 편, 편마다 운항일
python3 make.py flights-202611.json > air.json"""
import json, sys, collections, datetime
d = json.load(open(sys.argv[1]))
ym = d['month']; y, m = int(ym[:4]), int(ym[4:])
import calendar
N = calendar.monthrange(y, m)[1]
alld = set(range(1, N + 1))
WD = '월화수목금토일'
wd = lambda day: datetime.date(y, m, day).weekday()
def short(nm):
    nm = nm.replace('국제공항', '').replace('공항', '')
    return {'포항경주': '포항', '광주': '광주'}.get(nm, nm)
def wdl(ws):
    ws = sorted(ws)
    if ws == [0, 1, 2, 3, 4]: return '월∼금'
    if len(ws) == 6: return '%s 빼고' % WD[next(w for w in range(7) if w not in ws)]
    if len(ws) >= 3 and ws == list(range(ws[0], ws[-1] + 1)): return WD[ws[0]] + '∼' + WD[ws[-1]]
    return '・'.join(WD[w] for w in ws)
def label(days):
    """운항일: 매일이면 비우고, 요일·기간·날짜로. 맞는 꼴이 없으면 요일에 더하고 빼는 날을 붙인다"""
    days = set(days)
    if days == alld: return ''
    if len(alld - days) <= 3: return '%s일 빼고' % '・'.join(str(x) for x in sorted(alld - days))
    ws = {wd(x) for x in days}
    full = {x for x in alld if wd(x) in ws}
    if days == full: return wdl(ws)
    lo, hi = min(days), max(days)
    if len(days) >= 3 and days == set(range(lo, hi + 1)):
        if lo == 1: return '%d일까지' % hi
        if hi == N: return '%d일부터' % lo
        return '%d∼%d일' % (lo, hi)
    if len(days) <= 5: return '・'.join(str(x) for x in sorted(days)) + '일'
    # 요일 W: 그 요일 날의 절반 넘게 뜨는 요일
    W = {w for w in range(7) if sum(1 for x in days if wd(x) == w) * 2 > sum(1 for x in alld if wd(x) == w)}
    fW = {x for x in alld if wd(x) in W}
    plus, minus = sorted(days - fW), sorted(fW - days)
    if W and len(plus) + len(minus) <= 4:
        base = '매일' if len(W) == 7 else wdl(W)
        return base + ('・%s일' % '・'.join(map(str, plus)) if plus else '') + ('(%s일 빼고)' % '・'.join(map(str, minus)) if minus else '')
    return '・'.join(str(x) for x in sorted(days)) + '일' if len(days) <= 8 else '%d∼%d일 사이 %d일' % (lo, hi, len(days))
fl = collections.defaultdict(lambda: collections.defaultdict(set))     # (dep,arr) → (no,t,a) → days
for f in d['flights']:
    fl[(f['dep'], f['arr'])][(f['no'], f['t'], f['a'])].add(int(f['day'][6:]))
aps = d['airports']
# 공항 쌍: 편이 많은 차례
pairs = {}
for (a, b), v in fl.items():
    k = tuple(sorted((a, b)))
    pairs[k] = pairs.get(k, 0) + sum(len(x) for x in v.values())
blocks = []
for (a, b), _ in sorted(pairs.items(), key=lambda x: -x[1]):
    # 방향: 김포·김해 등 큰 공항에서 나가는 쪽을 먼저 (편 많은 공항 먼저)
    tot = collections.Counter()
    for (p, q), v in fl.items():
        tot[p] += len(v)
    first, second = (a, b) if tot[a] >= tot[b] else (b, a)
    for p, q in ((first, second), (second, first)):
        v = fl.get((p, q))
        if not v: continue
        byno = collections.defaultdict(list)
        for (no, t, aa), ds in v.items(): byno[no].append((t, aa, ds))
        rows = []
        for no, vs in byno.items():
            vs.sort(key=lambda x: -len(x[2]))
            groups = []                     # 15분 안쪽으로 다른 시각은 한 편으로
            for t, aa, ds in vs:
                tm = int(t[:2]) * 60 + int(t[2:])
                g = next((g for g in groups if abs(g[0] - tm) <= 15), None)
                if g: g[2].append((t, aa, ds))
                else: groups.append((tm, None, [(t, aa, ds)]))
            for _, _, gs in groups:
                t, aa, ds = gs[0]
                alls = set().union(*(x[2] for x in gs))
                lab = label(alls)
                for t2, a2, d2 in gs[1:]:
                    lab = (lab + ' ' if lab else '') + '%s %s발' % (label(d2) or '', str(int(t2[:2])) + t2[2:])
                rows.append((no, t, aa, lab.strip()))
        rows.sort(key=lambda r: (r[1], r[0]))
        blocks.append({'title': '%s → %s' % (short(aps[p]), short(aps[q])), 'rows': rows})
json.dump({'month': ym, 'blocks': blocks}, sys.stdout, ensure_ascii=False, indent=0)
print('blocks', len(blocks), 'rows', sum(len(b['rows']) for b in blocks), file=sys.stderr)
