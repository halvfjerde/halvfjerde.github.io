#!/usr/bin/env python3
"""flights-YYYYMM.json(fetch.py) → 책에 싣는 항공 목록 air.json: 공항 쌍마다 가는 편·오는 편, 편마다 운항일
python3 make.py flights-202611.json > air.json"""
import json, sys, collections, datetime, re
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
    return '・'.join(str(x) for x in sorted(days)) + '일'      # 맞는 꼴이 없으면 날짜를 죽
fl = collections.defaultdict(lambda: collections.defaultdict(set))     # (dep,arr) → (no,t,a) → days
for f in d['flights']:
    fl[(f['dep'], f['arr'])][(f['no'], f['t'], f['a'])].add(int(f['day'][6:]))
aps = d['airports']
fare = collections.defaultdict(list)
for f in d['flights']:
    if f.get('c'): fare[tuple(sorted((f['dep'], f['arr'])))].append(f['c'])
def rows_of(v):
    """한 방향의 편 [(편명, 발, 착, 운항일)] (같은 편명이 15분 안쪽으로 시각만 바뀌면 한 줄, 다른 시각은 괄호에)"""
    mm = lambda x: int(x[:2]) * 60 + int(x[2:])
    hh_ = lambda x: str(int(x[:2])) + x[2:]
    byno = collections.defaultdict(list)
    for (no, t, aa), ds in v.items(): byno[no].append((t, aa, ds))
    rows = []
    for no, vs in byno.items():
        vs.sort(key=lambda x: -len(x[2]))
        groups = []
        for t, aa, ds in vs:
            g = next((g for g in groups if abs(g[0] - mm(t)) <= 15), None)
            if g: g[1].append((t, aa, ds))
            else: groups.append((mm(t), [(t, aa, ds)]))
        for _, gs in groups:
            t, aa, ds = gs[0]
            lab = label(set().union(*(x[2] for x in gs)))
            for t2, a2, d2 in gs[1:]:
                same_dur = (mm(a2) - mm(t2)) % 1440 == (mm(aa) - mm(t)) % 1440
                lab = (lab + ' ' if lab else '') + '(%s{%s}발%s)' % ((label(d2) + ' ') if label(d2) else '', hh_(t2), '' if same_dur else ' {%s}착' % hh_(a2))
            rows.append((no, t, aa, lab.strip()))
    rows.sort(key=lambda r: (r[1], r[0]))
    return rows
def notes_of(rows):
    """운항일이 붙은 편: 같은 운항일끼리 모아 「※편명・편명 운항일」"""
    by = collections.OrderedDict()
    for no, t, aa, lab in rows:
        if lab: by.setdefault(lab, []).append(no)
    # 다른 시각 하나뿐이면 괄호 없이: 「※KE1122 수 650발」
    return [(nos, re.sub(r'^\((.*)\)$', r'\1', lab) if lab.count('(') == 1 and lab.startswith('(') else lab) for lab, nos in by.items()]
# 공항 쌍: 편이 많은 차례, 쌍 안에서는 편이 많은 공항에서 나가는 쪽을 왼쪽에
HUB = ['김포', '인천', '김해', '대구', '청주', '광주', '울산', '여수', '사천', '포항', '군산', '원주', '양양', '무안', '제주']   # 앞의 공항이 왼쪽(가는 편)
rank = lambda ap: HUB.index(short(aps[ap])) if short(aps[ap]) in HUB else len(HUB) - 1
pairs = collections.Counter()
for (a, b), v in fl.items(): pairs[tuple(sorted((a, b)))] += sum(len(x) for x in v.values())
blocks = []
for n, ((a, b), _) in enumerate(pairs.most_common(), 1):
    first, second = (a, b) if rank(a) <= rank(b) else (b, a)
    out_ = rows_of(fl.get((first, second), {})); in_ = rows_of(fl.get((second, first), {}))
    fs_ = fare.get((a, b), [])
    blocks.append({'no': n, 'a': short(aps[first]), 'b': short(aps[second]), 'out': out_, 'in': in_,
                   'notes': notes_of(out_) + notes_of(in_), 'fare': [min(fs_), max(fs_)] if fs_ else None})
json.dump({'month': ym, 'pairs': blocks}, sys.stdout, ensure_ascii=False, indent=0)
print('pairs', len(blocks), 'rows', sum(len(b['out']) + len(b['in']) for b in blocks), 'notes', sum(len(b['notes']) for b in blocks), file=sys.stderr)
