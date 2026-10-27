#!/usr/bin/env python3
"""trips-날짜.json → 책의 고속버스 목록 bus.json: 출발 터미널마다(가나다), 행선지마다(가나다) 소요·요금과 발차 시각.
휴게소 환승 정류소를 오가는 짝은 뺀다 (승객이 타고 내리는 구간이 아님)"""
import json, sys, collections, statistics
d = json.load(open(sys.argv[1]))
mins = lambda x: int(str(x)[8:10]) * 60 + int(str(x)[10:12])
G = {'우등': '', '고속': '일', '프리미엄': '프', '심야우등': '심', '심야프리미엄': '심프', '심야고속': '심일'}
skip = lambda s: '휴게소' in s
T = collections.defaultdict(lambda: collections.defaultdict(dict))
nm = {}
for r in d:
    if skip(r['depSite']) or skip(r['arrSite']): continue
    t, a = mins(r['depPlandTime']), mins(r['arrPlandTime'])
    T[r['depId']][r['arrId']][t] = ((a - t) % 1440, G.get(r.get('gradeNm', ''), ''), r.get('charge') or 0)
    nm[r['depId']] = r['depPlaceNm']; nm[r['arrId']] = r['arrPlaceNm']
# 이름이 같은 여러 ID (동대구 등)는 한 터미널로
byname = collections.defaultdict(lambda: collections.defaultdict(dict))
for o, dd in T.items():
    for x, v in dd.items():
        if nm[o] == nm[x]: continue
        byname[nm[o]][nm[x]].update(v)
origins = []
for o in sorted(byname):
    dests = []
    for x in sorted(byname[o]):
        v = byname[o][x]
        ds = [du for du, _, _ in v.values()]; fs = [c for _, _, c in v.values() if c]
        dests.append({'to': x, 'dur': int(statistics.median(ds)), 'fare': [min(fs), max(fs)] if fs else None,
                      'times': [['%d%02d' % (t // 60 % 24, t % 60), g] for t, (_, g, _) in sorted(v.items())]})
    origins.append({'from': o, 'dests': dests})
json.dump({'day': sys.argv[1][-13:-5], 'origins': origins}, sys.stdout, ensure_ascii=False, indent=0)
print('origins', len(origins), 'dests', sum(len(o['dests']) for o in origins), 'trips', sum(len(x['times']) for o in origins for x in o['dests']), file=sys.stderr)
