#!/usr/bin/env python3
"""확인용 편(5·6·8·13)을 책에 실린 긴 노선(노선표 하나, 목록 덩이 하나)마다 모은다. python3 review_by_route.py > bus-review-routes.md"""
import runpy, sys, io, contextlib, json, collections, re
S = '/tmp/claude-0/-home-claude/f0c8a077-152e-527e-9fb9-53dee448f1fc/scratchpad/'
sys.argv = ['routes2.py', 'bus.json', '/dev/null', S + 'rr.json', S + 'rs.md']
with contextlib.redirect_stderr(io.StringIO()): g = runpy.run_path('routes2.py')
b0 = json.load(open('bus.json')); R = json.load(open('bus-review-data.json'))
import os
DEC = json.load(open('review-decisions.json')) if os.path.exists('review-decisions.json') else {}
DONE = {tuple(t) for v in DEC.values() for e in v for t in e['trips']}      # 사람이 확인한 편은 빼고
rest = g['b']; both = g['both']; TTL = g['TTL']; nm = g['nm']
WD = '월화수목금토일'
m_ = lambda s: int(s[:-2]) * 60 + int(s[-2:])
hm = lambda v: '%d%02d' % (v // 60 % 24, v % 60)
# 1) 노선표의 마디 (타는 곳, 시각, 내리는 곳) → (표 이름, 그 차의 첫 정류장·시각)
node = {}
for T, U in both:
    for X in (T, U):
        if not X: continue
        title = TTL.get(id(X)) or TTL.get(id(T)) or X.get('title') or ''
        st = X['stops'] if X is T else list(reversed(T['stops']))
        for c in X['cols']:
            sv = [s for s in st if s in c]
            if not sv: continue
            lab = '%s %s' % (nm(sv[0]), hm(c[sv[0]][1]))
            for i, A in enumerate(sv):
                if c[A][0] != 'd': continue
                for D in sv[i + 1:]: node[(A, c[A][1], D)] = ('표 「%s」' % title, lab, c[sv[0]][1])
# 2) 목록 덩이: 참조 줄이면 그 덩이로 (seeFrom 은 승차 δ 만큼 앞 시각으로)
blk = {(O['from'], X['to']): X for O in rest['origins'] for X in O['dests']}
def route_of(o, x, t):
    if (o, t, x) in node: return node[(o, t, x)]
    X = blk.get((o, x))
    if X is None: return ('(없음)', '%s→%s %s' % (nm(o), nm(x), hm(t)), t)
    if 'see' in X: return route_of(o, X['see'], t)
    if 'seeFrom' in X:
        A = X['seeFrom']; Y = blk.get((A, x), {})
        d = 0
        for bb in Y.get('board', []):
            mt = re.match(r'(\S+)(?: \+(?:(\d+)시간)? ?(?:(\d+)분)?)?', bb)
            if mt and mt.group(1) == o: d = int(mt.group(2) or 0) * 60 + int(mt.group(3) or 0)
        return route_of(A, x, (t - d) % 1440)
    via = '・'.join(nm(v[0]) for v in X.get('via', []))
    return ('목록 %s 발 %s 행%s' % (nm(o), nm(x), (' (경유 %s)' % via) if via else ''), '%s %s' % (nm(o), hm(t)), t)
items = collections.defaultdict(lambda: collections.defaultdict(list))
def add(o, x, t, tag):
    if (o, x, t) in DONE: return
    r, lab, t0 = route_of(o, x, t)
    items[r][(t0, lab)].append(tag)
def contig(ws):
    ws = sorted(ws)
    if len(ws) in (0, 7): return True
    return any(sorted((s0 + k) % 7 for k in range(len(ws))) == ws for s0 in ws)
for O in b0['origins']:
    for X in O['dests']:
        for tg in X['times']:
            ws = [i for i in range(7) if tg[2][i]]
            if not contig(ws): add(O['from'], X['to'], m_(tg[0]), '5 요일 %s' % ''.join(WD[i] for i in ws))
            if '시' in tg[3:] and len(ws) <= 2: add(O['from'], X['to'], m_(tg[0]), '13 시외 %s만' % ''.join(WD[i] for i in ws))
for o, x, t, miss in R['filled']: add(o, x, t, '6 %s 채움' % ''.join(WD[i] for i in miss))
for o, x, t, ws in R['firstonly']: add(o, x, t, '8 앞 주만 %s' % ''.join(WD[i] for i in ws))
L = ['# 확인할 편: 긴 노선마다', '',
     '책에 실린 노선표(「표」)나 목록 덩이(「목록 … 발 … 행」)마다, 그 노선의 차(첫 정류장 발 시각)로 모았다. 한 차가 여러 구간에 걸쳐 나오던 것은 한 줄로.',
     '표지: 5 이어지지 않는 요일 · 6 빠진 요일을 매일로 채움 · 8 앞 주에만 있어 다시 실음 · 13 하루 이틀만 다닌 시외', '']
for r in sorted(items, key=lambda r: (not r.startswith('표'), r)):
    L.append('**%s**' % r)
    for (t0, lab), tags in sorted(items[r].items(), key=lambda kv: (kv[0][0] + (1440 if kv[0][0] < 240 else 0), kv[0][1])):
        L.append('- %s: %s' % (lab, ', '.join(sorted(set(tags)))))
    L.append('')
print('\n'.join(L))
print(len(items), sum(len(v) for v in items.values()), file=sys.stderr)
