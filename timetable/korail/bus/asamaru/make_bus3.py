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
# 두 주(이레 × 2)를 맞대어:
# · 다니는 요일: 나중 주에 한 번이라도 다니는 편만 싣고, 두 주 가운데 한 번이라도 다닌 요일은 다니는 날로 (하루 빠진 것은 거의 임의 결행)
# · 등급: 같은 요일인데 주마다 다르면 편마다 정해진 등급이 아니라 차가 돌아가며 바뀌는 것 → 등급 칸 ※, 행선지 밑에 「※ 가운데 날마다 1편 프리미엄」
LAST = set(days[-7:])                                      # 나중 주
GN = {'우등': '우등', '고속': '일반', '프리미엄': '프리미엄', '심야우등': '심야우등', '심야프리미엄': '심야프리미엄', '심야고속': '심야일반'}
PD = collections.defaultdict(dict)                         # (출발, 도착, 시각) → 날짜 → 등급
for (o, x, t, w_), gs in GD2.items(): pass
for a, b_, ia, ib in pairs:
    if '휴게소' in a or '휴게소' in b_: continue
    for d in days:
        f = os.path.join(C, 'p-%s-%s-%s.json' % (d, ia[0], ib[0]))
        if not os.path.exists(f): continue
        for r in json.load(open(f)):
            o, x = r['depPlaceNm'], r['arrPlaceNm']
            if o == x: continue
            PD[(o, x, mins(r['depPlandTime']))][d] = r.get('gradeNm', '')
origins = []
nvar = 0
for o in sorted(T):
    dests = []
    for x in sorted(T[o]):
        ds = [du for du, _ in info[o][x]]; fs = [c for _, c in info[o][x] if c]
        dur = int(statistics.median(ds))
        times, var_t = [], []
        for t in sorted(T[o][x]):
            pd = PD[(o, x, t)]
            if not (set(pd) & LAST): continue                # 나중 주에 없는 편 (철이 바뀌어 없어진 편)
            byw = collections.defaultdict(set)
            for d, g in pd.items(): byw[wd[d]].add(g)
            gvar = any(len(v) > 1 for v in byw.values())
            w = [0] * 7
            for w_, gs in byw.items():
                w[w_] = '◆' if gvar else (G.get(next(iter(gs)), '') or '우')
            hm = lambda m: '%d%02d' % (m // 60 % 24, m % 60)
            times.append([hm(t), hm(t + dur), w])
            if gvar: var_t.append(t)
        X = {'to': x, 'dur': dur, 'fare': [min(fs), max(fs)] if fs else None, 'times': times}
        if var_t:                                           # 돌아가는 등급: 날마다 몇 편이 무슨 등급인지
            nvar += len(var_t)
            cnt = collections.defaultdict(collections.Counter)
            for t in var_t:
                for d, g in PD[(o, x, t)].items(): cnt[d][g] += 1
            gall = collections.Counter(g for c in cnt.values() for g in c.elements())
            major = gall.most_common(1)[0][0]
            parts, ok = [], True
            for g in sorted(gall, key=lambda g: -gall[g]):
                if g == major: continue
                ks = sorted(cnt[d][g] for d in cnt)
                lo_, hi_ = ks[len(ks) // 10], ks[-1 - len(ks) // 10]        # 드문 튀는 날(임의 결행 등)은 빼고
                if lo_ == hi_ and lo_ > 0: parts.append('날마다 %d편 %s' % (lo_, GN.get(g, g)))
                elif hi_ - lo_ == 1 and lo_ > 0: parts.append('날마다 %d∼%d편 %s' % (lo_, hi_, GN.get(g, g)))
                elif hi_ - lo_ == 1: parts.append('어떤 날 %d편 %s' % (hi_, GN.get(g, g)))
                else: ok = False
            if len(var_t) == 1 and len(gall) == 2: X['gnote'] = '◆ 날에 따라 %s' % ' 또는 '.join(GN.get(g, g) for g in sorted(gall, key=lambda g: -gall[g]))
            elif ok and len(parts) == 1 and len(gall) == 2: X['gnote'] = '◆ 가운데 ' + ', '.join(parts) + ', 나머지 %s' % GN.get(major, major)
            elif len(gall) == 2: X['gnote'] = '◆ 날에 따라 %s 또는 %s' % tuple(GN.get(g, g) for g in sorted(gall, key=lambda g: -gall[g]))
            else: X['gnote'] = '◆ 날마다 등급이 바뀜'                  # 등급이 셋 넘으면 늘어놓지 않는다
        if times: dests.append(X)
    if dests: origins.append({'from': o, 'dests': dests})
print('grade-rotating times', nvar, file=sys.stderr)
json.dump({'days': days, 'origins': origins}, sys.stdout, ensure_ascii=False, indent=0)
print('origins', len(origins), 'dests', sum(len(o['dests']) for o in origins), 'times', sum(len(x['times']) for o in origins for x in o['dests']),
      'daily', sum(1 for o in origins for x in o['dests'] for t in x['times'] if all(t[2])), 'missing files', dict(miss), file=sys.stderr)
