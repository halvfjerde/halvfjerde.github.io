"""앞 두 주(10/3∼16)와 뒤 두 주(10/17∼30)의 고속 배차를 견준다: 등급이 같은가, 다니는 요일이 같은가 (공휴일은 뺀다)"""
import json, os, glob, collections, datetime, sys
CB = os.path.expanduser('~/.cache/tago-bus')
pl = json.load(open('/home/claude/korail/bus/asamaru/pairs-live.json'))
EXP = sorted({(a, b) for k, a, b in json.load(open('/home/claude/korail/bus/tools/need-pairs.json')) if k == 'ExpBusInfo'})
HOL = {'20261003', '20261005', '20261009'}            # 개천절, 대체공휴일, 한글날
A = ['20261004', '20261006', '20261007', '20261008'] + ['202610%02d' % k for k in range(10, 17)]
B = ['202610%02d' % k for k in range(17, 31)]
wd = lambda d: datetime.date(int(d[:4]), int(d[4:6]), int(d[6:])).weekday()
G = collections.defaultdict(dict)                   # (o, x, hhmm) → date → grade
miss = collections.Counter()
for a, b in EXP:
    for d in A + B:
        f = os.path.join(CB, 'p-%s-%s-%s.json' % (d, a, b))
        if not os.path.exists(f): miss[d] += 1; continue
        for r in json.load(open(f)):
            if r['depPlaceNm'] == r['arrPlaceNm']: continue
            G[(r['depPlaceNm'], r['arrPlaceNm'], str(r['depPlandTime'])[8:12])][d] = r.get('gradeNm', '')
print('missing files', dict(miss))
stat = collections.Counter(); ex = collections.defaultdict(list)
for k, dg in G.items():
    ga = {dg[d] for d in A if d in dg}; gb = {dg[d] for d in B if d in dg}
    wa = {wd(d) for d in A if d in dg}; wb = {wd(d) for d in B if d in dg}
    if not ga and gb: stat['뒤에만'] += 1; continue
    if ga and not gb: stat['앞에만'] += 1; continue
    if len(gb) == 1 and len(ga) == 1:
        stat['등급 하나: 같음' if ga == gb else '등급 하나: 바뀜'] += 1
        if ga != gb: ex['바뀜'].append((k, ga, gb))
    elif len(gb) > 1 or len(ga) > 1:
        stat['날마다 바뀜(어느 쪽이든)'] += 1
        # 요일마다 등급이 두 주 모두 같은가
        byA = collections.defaultdict(set); byB = collections.defaultdict(set)
        for d in A:
            if d in dg: byA[wd(d)].add(dg[d])
        for d in B:
            if d in dg: byB[wd(d)].add(dg[d])
        same = all(byA[w] == byB[w] for w in set(byA) & set(byB))
        stat['  요일마다 같은 꼴' if same else '  요일과도 안 맞음'] += 1
    stat['요일 같음' if wa == wb else '요일 다름'] += 1
    if wa != wb: ex['요일'].append((k, sorted(wa), sorted(wb)))
for k, v in sorted(stat.items()): print(k, v)
for k, v in ex.items():
    print('##', k, len(v))
    for e in v[:15]: print('  ', e)
# 뒤 두 주에 날마다 다니지 않는 차만: 앞 주와 요일이 같은가 (앞 주에 그 요일이 한 번뿐인 것도 감안: 앞 주에 있는 요일만 견준다)
aw = collections.Counter(wd(d) for d in A)
nd = collections.Counter()
for k, dg in G.items():
    wb = {wd(d) for d in B if d in dg}; wa = {wd(d) for d in A if d in dg}
    if not wb or not wa: continue
    if len(wb) == 7: nd['뒤 날마다: 앞도 날마다' if len(wa) == 7 else '뒤 날마다: 앞은 빠진 날 있음'] += 1; continue
    nd['뒤 요일 한정: 앞과 같음' if wa == wb else ('뒤 요일 한정: 앞이 더 많음' if wa > wb else ('뒤 요일 한정: 앞이 더 적음' if wa < wb else '뒤 요일 한정: 엇갈림'))] += 1
for k, v in sorted(nd.items()): print(k, v)
