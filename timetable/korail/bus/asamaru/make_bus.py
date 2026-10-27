#!/usr/bin/env python3
"""trips-날짜.json → 고속버스 덩이 bus.json (항공 덩이 꼴). 같은 시각에 떠나 먼저 닿는 곳은 그 버스의 정차지로 묶는다.
덩이 = 출발 터미널 O 와 종점 X 의 쌍: 가는 편 O→X, 오는 편 X→O. 정차지는 주로."""
import json, sys, collections, re
d = json.load(open(sys.argv[1]))
mins = lambda x: int(str(x)[8:10]) * 60 + int(str(x)[10:12])
dur = lambda t, a: (a - t) % 1440
nm = {}
D = collections.defaultdict(lambda: collections.defaultdict(dict))      # O → X → {출발: (도착, 등급, 요금)}
for r in d:
    D[r['depId']][r['arrId']][mins(r['depPlandTime'])] = (mins(r['arrPlandTime']), r.get('gradeNm', ''), r.get('charge'))
    nm[r['depId']] = r['depPlaceNm']; nm[r['arrId']] = r['arrPlaceNm']
def avgd(v): return sum(dur(t, a) for t, (a, _, _) in v.items()) / len(v)
routes = {}                                # (O, X) → 정차지 [S]
for O, dd in D.items():
    av = {x: avgd(v) for x, v in dd.items()}
    parent = {}
    for s, vs in dd.items():
        cands = [x for x, vx in dd.items() if x != s and len(vs) and set(vs) <= set(vx) and all(dur(t, vs[t][0]) < dur(t, vx[t][0]) and vs[t][1] == vx[t][1] for t in vs)]
        cands.sort(key=lambda x: av[x] - av[s])
        for x in cands[:3]:
            sx = D.get(s, {}).get(x)
            if sx:                              # S→X 버스가 따로 있으면 소요가 맞아야 같은 노선
                if abs(av[s] + avgd(sx) - av[x]) > 25: continue
            elif av[x] - av[s] > 70: continue
            parent[s] = x; break
    def root(x):
        seen = set()
        while x in parent and x not in seen: seen.add(x); x = parent[x]
        return x
    for x in dd:
        if x not in parent: routes[(O, x)] = []
    for s in parent: routes.setdefault((O, root(s)), []).append(s)
# 덩이: 두 방향을 한 쌍으로
blocks, seen = [], set()
GR = {'우등': '', '고속': '일반', '프리미엄': '프리미엄', '심야우등': '심야', '심야프리미엄': '심야 프리미엄', '심야고속': '심야 일반'}
for (O, X), stops in sorted(routes.items(), key=lambda kv: -len(D[kv[0][0]][kv[0][1]])):
    key = frozenset((O, X))
    if key in seen: continue
    seen.add(key)
    def rows(o, x):
        v = D.get(o, {}).get(x, {})
        return [(GR.get(g, g), '%02d%02d' % (t // 60 % 24, t % 60), '%02d%02d' % (a // 60 % 24, a % 60), '') for t, (a, g, _) in sorted(v.items())]
    out_, in_ = rows(O, X), rows(X, O)
    fares = [c for o, x in ((O, X), (X, O)) for (_, _, c) in D.get(o, {}).get(x, {}).values() if c]
    notes = []
    st_o = [nm[s] for s in sorted(stops, key=lambda s: avgd(D[O][s]))]
    st_i = [nm[s] for s in sorted(routes.get((X, O), []), key=lambda s: avgd(D[X][s]))]
    blocks.append({'a': nm[O], 'b': nm[X], 'out': out_, 'in': in_, 'stops': [st_o, st_i],
                   'fare': [min(fares), max(fares)] if fares else None})
for k, b in enumerate(blocks, 1): b['no'] = k
json.dump({'blocks': blocks}, sys.stdout, ensure_ascii=False, indent=0)
n = [len(b['out']) for b in blocks] + [len(b['in']) for b in blocks]
print('blocks', len(blocks), 'rows', sum(max(len(b['out']), len(b['in'])) for b in blocks), 'big(>30)', sum(1 for b in blocks if max(len(b['out']), len(b['in'])) > 30), file=sys.stderr)
