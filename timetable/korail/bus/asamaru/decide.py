#!/usr/bin/env python3
"""확인한 편을 review-decisions.json 에 적는다. 책의 노선(표 이름이나 「목록 X 발 Y 행」)과 차(첫 정류장 시각)로 고르면
그 차가 지나는 구간 (출발, 도착, 시각)을 모두 찾아 적는다. make_bus3.py 가 이 파일을 읽어 그대로 따른다.
  python3 decide.py daily '고창・담양 ― 인천공항2터미널' '담양 1115' '시각표는 매일, 같은 요일 결행이 이어짐'
  python3 decide.py drop '광주・전주 ― 고양백석' '전주 1550' '없는 편'
"""
import runpy, sys, io, contextlib, json, os, re
what, route, bus, why = sys.argv[1:5]
assert what in ('daily', 'drop', 'keep', 'alt')      # alt: 이틀씩 번갈아 다니는 편 (alt-routes.json 으로 따로 싣는다, 요일은 손대지 않음)
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE)
S = '/tmp/claude-0/-home-claude/f0c8a077-152e-527e-9fb9-53dee448f1fc/scratchpad/'
sys.argv = ['routes2.py', 'bus.json', '/dev/null', S + 'rr.json', S + 'rs.md']
with contextlib.redirect_stderr(io.StringIO()): g = runpy.run_path('routes2.py')
both, TTL, nm = g['both'], g['TTL'], g['nm']
b0 = json.load(open('bus.json'))
m_ = lambda s: int(s[:-2]) * 60 + int(s[-2:])
have = {(O['from'], X['to'], m_(tg[0])) for O in b0['origins'] for X in O['dests'] for tg in X['times']}
fn, tm = bus.rsplit(' ', 1); tm = m_(tm)
trips = []
for T, U in both:
    for X in (T, U):
        if not X: continue
        title = TTL.get(id(X)) or TTL.get(id(T)) or X.get('title') or ''
        if title != route: continue
        st = X['stops'] if X is T else list(reversed(T['stops']))
        for c in X['cols']:
            sv = [s for s in st if s in c]
            if not sv or nm(sv[0]) != fn or c[sv[0]][1] != tm: continue
            for i, A in enumerate(sv):
                if c[A][0] != 'd': continue
                for D in sv[i + 1:]:
                    for t in range(c[A][1], c[A][1] - 31, -1):      # 승차 분수를 더해 둔 칸은 자료 시각이 그보다 앞
                        if (A, D, t) in have: trips.append([A, D, t]); break
mt = re.match(r'목록 (\S+) 발 (\S+) 행', route)
if mt and not trips:
    nmr = {nm(s): s for O in b0['origins'] for s in [O['from']] + [X['to'] for X in O['dests']]}
    o, x = nmr.get(mt.group(1), mt.group(1)), nmr.get(mt.group(2), mt.group(2))
    trips = [[o, x, tm]] if (o, x, tm) in have else []
if not trips: sys.exit('못 찾음: %s / %s' % (route, bus))
F = 'review-decisions.json'
D = json.load(open(F)) if os.path.exists(F) else {}
L = D.setdefault(what, [])
L[:] = [e for e in L if not (e['route'] == route and e['bus'] == bus)]
L.append({'route': route, 'bus': bus, 'why': why, 'trips': sorted(trips)})
json.dump(D, open(F, 'w'), ensure_ascii=False, indent=1)
print(what, route, bus, '→', len(trips), '구간'); [print('  ', t) for t in sorted(trips)]
