#!/usr/bin/env python3
"""이레치 TAGO 고속버스 배차(캐시) → 책의 고속버스 목록 bus.json.
출발 터미널마다(가나다) 행선지마다(가나다): 소요(중앙값)·요금, 발차마다 [발, 착, 요일 일곱 칸].
요일 칸은 안 다니면 0, 다니면 그날의 등급(우·일·프·심·심프·심일). 착은 발 + 소요(TAGO 의 착 시각은 노선마다 소요가 하나).
휴게소 환승 정류소를 오가는 짝, 이름이 같은 짝은 뺀다. python3 make_bus3.py 20261024 … 20261030 > bus.json"""
import json, sys, os, collections, statistics, datetime
C = os.path.expanduser('~/.cache/tago-bus')
days = sys.argv[1:]
WD = '월화수목금토일'
wd = {d: datetime.date(int(d[:4]), int(d[4:6]), int(d[6:])).weekday() for d in days}
pairs = json.load(open('pairs-live.json'))
G = {'우등': '', '고속': '일', '프리미엄': '프', '심야우등': '심', '심야프리미엄': '심프', '심야고속': '심일'}
mins = lambda x: int(str(x)[8:10]) * 60 + int(str(x)[10:12])
T = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(set)))   # 출발이름 → 도착이름 → 시각 → 요일
GD = collections.defaultdict(set)                                                                    # (출발, 도착, 시각) → 등급들 (날에 따라 다르기도 함)
GD2 = {}
info = collections.defaultdict(lambda: collections.defaultdict(list))                                 # 소요·요금
miss = collections.Counter()
for a, b, ia, ib in pairs:
    if '휴게소' in a or '휴게소' in b: continue
    for d in days:
        f = os.path.join(C, 'p-%s-%s-%s.json' % (d, ia[0], ib[0]))
        if not os.path.exists(f): miss[d] += 1; continue
        for r in json.load(open(f)):
            o, x = r['depPlaceNm'], r['arrPlaceNm']
            if o == x: continue
            t = mins(r['depPlandTime']); du = (mins(r['arrPlandTime']) - t) % 1440
            T[o][x][t].add(wd[d]); GD[(o, x, t)].add(r.get('gradeNm', '')); GD2.setdefault((o, x, t, wd[d]), set()).add(r.get('gradeNm', ''))
            info[o][x].append((du, r.get('charge') or 0))
def wdl(ws):
    ws = sorted(ws)
    if ws == [0, 1, 2, 3, 4]: return '월∼금'
    if len(ws) >= 3 and ws == list(range(ws[0], ws[-1] + 1)): return WD[ws[0]] + '∼' + WD[ws[-1]]
    return '・'.join(WD[w] for w in ws)
origins = []
for o in sorted(T):
    dests = []
    for x in sorted(T[o]):
        ds = [du for du, _ in info[o][x]]; fs = [c for _, c in info[o][x] if c]
        dur = int(statistics.median(ds))
        times = []
        for t, ws in sorted(T[o][x].items()):
            w = [0] * 7
            for d in days:
                if wd[d] in ws:
                    gs = GD2.get((o, x, t, wd[d]), {''})
                    w[wd[d]] = G.get(next(iter(gs)), '') or '우'
            hm = lambda m: '%d%02d' % (m // 60 % 24, m % 60)
            times.append([hm(t), hm(t + dur), w])
        dests.append({'to': x, 'dur': dur, 'fare': [min(fs), max(fs)] if fs else None, 'times': times})
    origins.append({'from': o, 'dests': dests})
json.dump({'days': days, 'origins': origins}, sys.stdout, ensure_ascii=False, indent=0)
print('origins', len(origins), 'dests', sum(len(o['dests']) for o in origins), 'times', sum(len(x['times']) for o in origins for x in o['dests']),
      'daily', sum(1 for o in origins for x in o['dests'] for t in x['times'] if all(t[2])), 'missing files', dict(miss), file=sys.stderr)
