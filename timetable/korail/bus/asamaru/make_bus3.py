#!/usr/bin/env python3
"""이레치 TAGO 고속버스 배차(캐시) → 책의 고속버스 목록 bus.json.
출발 터미널마다(가나다) 행선지마다(가나다): 소요(중앙값)·요금, 발차 시각마다 등급과 운행 요일.
날마다 다니면 요일 없음. 아니면 요일 묶음마다 표지(a, b, …)를 달고 행선지 밑 주에 「a 금・토・일」.
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
            T[o][x][t].add(wd[d]); GD[(o, x, t)].add(r.get('gradeNm', ''))
            info[o][x].append((du, r.get('charge') or 0))
def wdl(ws):
    ws = sorted(ws)
    if ws == [0, 1, 2, 3, 4]: return '월∼금'
    if len(ws) >= 3 and ws == list(range(ws[0], ws[-1] + 1)): return WD[ws[0]] + '∼' + WD[ws[-1]]
    return '・'.join(WD[w] for w in ws)
ALL = set(wd.values())
origins = []
for o in sorted(T):
    dests = []
    for x in sorted(T[o]):
        marks, lab = {}, []
        times = []
        for t, ws in sorted(T[o][x].items()):
            gs = GD[(o, x, t)]
            g = G.get(next(iter(gs)), '') if len(gs) == 1 else '/'.join(sorted({G.get(z, '') or '우' for z in gs}))   # 날에 따라 등급이 바뀌면 「우/프」
            m = ''
            if ws != ALL:
                k = wdl(ws)
                if k not in marks: marks[k] = (lambda n: 'abcdefghijklmnopqrstuvwxyz'[n] if n < 26 else 'z%d' % n)(len(marks)); lab.append([marks[k], k])
                m = marks[k]
            times.append(['%d%02d' % (t // 60 % 24, t % 60), g, m])
        ds = [du for du, _ in info[o][x]]; fs = [c for _, c in info[o][x] if c]
        dests.append({'to': x, 'dur': int(statistics.median(ds)), 'fare': [min(fs), max(fs)] if fs else None, 'times': times, 'notes': lab})
    origins.append({'from': o, 'dests': dests})
json.dump({'days': days, 'origins': origins}, sys.stdout, ensure_ascii=False, indent=0)
print('origins', len(origins), 'dests', sum(len(o['dests']) for o in origins), 'times', sum(len(x['times']) for o in origins for x in o['dests']),
      'daily', sum(1 for o in origins for x in o['dests'] for t in x['times'] if not t[2]), 'missing files', dict(miss), file=sys.stderr)
