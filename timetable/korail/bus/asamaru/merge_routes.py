#!/usr/bin/env python3
"""bus.json(make_bus3) → 같은 차를 한 덩이로. 발차 시각·요일이 모두 같은 짝은 같은 차로 본다 (발차 둘 이상일 때만).
1) 한 터미널에서 여러 곳으로: 가장 먼 곳(소요가 가장 긴 곳)의 덩이에 나머지를 「경유」(via: 이름·소요·요금)로. 나머지 자리에는 참조 줄(see).
2) 여러 터미널에서 한 곳으로: TAGO 는 중간 승차지에도 첫 터미널의 발차 시각을 붙이므로, 소요가 가장 긴 곳(같으면 발차가 많은 터미널)을 본 덩이로 두고
   나머지는 「승차」(board) 목록에. 그 터미널들에는 참조 줄(seeFrom).
python3 merge_routes.py bus.json [ORDER.json] > bus-routes.json"""
import json, sys, collections
b = json.load(open(sys.argv[1]))
order = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else {}       # 실제로 확인한 승차 차례: {"평택→서울경부": ["평택", "평택굿모닝병원", "평택대"]}
sig = lambda X: ' '.join(t[0] for t in X['times'])           # 발차 시각만 (요일·등급은 날마다 받은 자료가 조금씩 어긋나기도 한다)
size = {O['from']: sum(len(X['times']) for X in O['dests']) for O in b['origins']}
n1 = n2 = 0
for O in b['origins']:                                      # 1) 내리는 곳 여럿
    g = collections.defaultdict(list)
    for X in O['dests']:
        if len(X['times']) >= 2: g[sig(X)].append(X)
    out = []
    drop = {}
    for xs in g.values():
        if len(xs) < 2: continue
        xs.sort(key=lambda X: (X['dur'], size.get(X['to'], 0)))          # 소요가 같으면 큰 터미널을 끝으로
        rv = next((list(reversed(v)) for v in order.values() if set(v) >= {X['to'] for X in xs[:-1]} and xs[-1]['to'] in v), None)
        if rv: xs[:-1] = sorted(xs[:-1], key=lambda X: rv.index(X['to']))   # 실제로 확인한 차례를 거꾸로 (돌아오는 길)
        last = xs[-1]
        last['via'] = [[X['to'], X['dur'], X.get('fare')] for X in xs[:-1]]
        for X in xs[:-1]: drop[X['to']] = last['to']; n1 += 1
    O['dests'] = [({'to': X['to'], 'see': drop[X['to']]} if X['to'] in drop else X) for X in O['dests']]
idx = collections.defaultdict(list)                         # 2) 타는 곳 여럿: (끝 행선지, 시각, 경유) 가 같은 덩이
for O in b['origins']:
    for X in O['dests']:
        if 'times' in X and len(X['times']) >= 2:
            idx[(X['to'], sig(X), json.dumps([v[0] for v in X.get('via', [])], ensure_ascii=False))].append((O['from'], X))
for (to, _, _), vs in idx.items():
    if len(vs) < 2: continue
    key = '%s→%s' % (vs[0][0], to)
    ords = next((v for k, v in order.items() if k.split('→')[1] == to and set(v) >= {o for o, _ in vs}), None)
    if ords: vs.sort(key=lambda v: ords.index(v[0]))
    else: vs.sort(key=lambda v: (-v[1]['dur'], -size[v[0]], v[0]))
    host, hx = vs[0]
    hx['board'] = [o for o, _ in vs[1:]]
    hx['boardKnown'] = bool(ords)
    for o, X in vs[1:]:
        X.clear(); X.update({'to': to, 'seeFrom': host}); n2 += 1
json.dump(b, sys.stdout, ensure_ascii=False, indent=0)
print('drop-merged', n1, 'board-merged', n2, file=sys.stderr)
