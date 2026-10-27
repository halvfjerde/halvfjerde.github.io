#!/usr/bin/env python3
"""icn.json(fetch_icn.py, 이레치) → 국제선 덩이를 air.json 에 덧붙인다: python3 make_icn.py air.json icn.json > air2.json
인천 쪽 시각만 있다 (상대 공항 시각은 자료에 없음). 공동운항 편명(Slave)·화물·국내 연결편은 뺀다.
운항요일은 받은 이레에서: 날마다면 비우고, 아니면 요일. 같은 편이 요일마다 시각이 조금 다르면 괄호에"""
import json, sys, collections, datetime
air = json.load(open(sys.argv[1])); d = json.load(open(sys.argv[2]))
WD = '월화수목금토일'
days = sorted({x['_day'] for x in d})
wd = lambda s: datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8])).weekday()
def wdl(ws):
    ws = sorted(ws)
    if len(ws) == 7: return ''
    if ws == [0, 1, 2, 3, 4]: return '월∼금'
    if len(ws) == 6: return '%s 빼고' % WD[next(w for w in range(7) if w not in ws)]
    if len(ws) >= 3 and ws == list(range(ws[0], ws[-1] + 1)): return WD[ws[0]] + '∼' + WD[ws[-1]]
    return '・'.join(WD[w] for w in ws)
mm = lambda x: int(x[:2]) * 60 + int(x[2:])
hh_ = lambda x: str(int(x[:2])) + x[2:]
P = [x for x in d if x['passengerOrCargo'] == 'Passenger' and x.get('codeshare') != 'Slave' and x.get('typeOfFlight') == 'I']
by = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(set)))   # (공항, io) → 편명 → 시각 → 요일
name = {}
for x in P:
    by[(x['airportCode'], x['_io'])][x['flightId']][x['scheduleDatetime'][8:12]].add(wd(x['_day']))
    nm_ = x['airport'].replace(' ', '')
    if '/' in nm_: a_, b_ = nm_.split('/', 1); nm_ = '%s(%s)' % (a_, b_)        # 도쿄/나리타 → 도쿄(나리타)
    name[x['airportCode']] = nm_
def rows_of(v, io):
    rows = []
    for no, ts in v.items():
        groups = []
        for t, ws in sorted(ts.items(), key=lambda kv: -len(kv[1])):
            g = next((g for g in groups if abs(mm(g[0]) - mm(t)) <= 30 or (1440 - abs(mm(g[0]) - mm(t))) <= 30), None)
            if g: g[1].append((t, ws))
            else: groups.append((t, [(t, ws)]))
        for t0, gs in groups:
            allw = set().union(*(w for _, w in gs))
            lab = wdl(allw)
            for t2, w2 in gs[1:]:
                lab = (lab + ' ' if lab else '') + '(%s{%s}%s)' % ((wdl(w2) + ' ') if wdl(w2) else '', hh_(t2), '발' if io == 'dep' else '착')
            rows.append((no, t0, '', lab.strip()))
    rows.sort(key=lambda r: (r[1], r[0]))
    return rows
def notes_of(rows):
    g = collections.OrderedDict()
    for no, t, a, lab in rows:
        if lab: g.setdefault(lab, []).append(no)
    return [(nos, lab) for lab, nos in g.items()]
codes = sorted({c for c, _ in by}, key=lambda c: -(sum(len(v) for v in by[(c, 'dep')].values()) + sum(len(v) for v in by[(c, 'arr')].values())))
n0 = max([p['no'] for p in air['pairs']] + [0])
for k, c in enumerate(codes, 1):
    o, i = rows_of(by[(c, 'dep')], 'dep'), rows_of(by[(c, 'arr')], 'arr')
    air['pairs'].append({'no': n0 + k, 'a': '인천', 'b': name[c], 'intl': True, 'out': o, 'in': i, 'notes': notes_of(o) + notes_of(i), 'fare': None})
json.dump(air, sys.stdout, ensure_ascii=False, indent=0)
print('intl', len(codes), 'rows', sum(len(p['out']) + len(p['in']) for p in air['pairs'] if p.get('intl')),
      'notes', sum(len(p['notes']) for p in air['pairs'] if p.get('intl')), 'days', days[0], days[-1], file=sys.stderr)
