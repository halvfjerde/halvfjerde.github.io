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
# 시외버스(TAGO 시외버스정보, 한도가 따로): 책의 고속 구간과 그 반대, 전환시외 노선의 터미널 짝. 터미널 이름을 책 이름으로
SUB = os.path.expanduser('~/.cache/tago-sub')
SUBNM = {'서울고속버스터미널(경부)': '서울경부', '인천공항2터미널': '인천공항T2', '노포': '부산', '부산서부(사상)': '부산사상', '대구동부': '동대구', '대구서부': '서대구',
         '안산터미널': '안산', '수원터미널': '수원', '통영터미널': '통영', '거제(고현)': '고현', '전주시외터미널': '전주', '아산(온양)': '아산', '개양(진주)': '진주개양',
         '진주(경전)': '진주', '진주(경남)': '진주', '진주(경원)': '진주', '진주(부산교통)': '진주', '경주시외': '경주', '경주고속': '경주', '시흥': '시흥시화',
         '동광양(중마)': '동광양', '임자(대광)': '임자(진리)', '청주북부터미널': '청주북부', '청주': '청주(센트럴)', '교통대학': '교통대', '경북도청(신)': '경북도청',
         '고한사북공영': '고한사북', '울산(태화)': '울산', '수락산역(직통)': '수락산역', '김해공항국제(세인공항리무진)': '김해공항', '김해공항(태화)국제': '김해공항'}
SG = {'심야프리': '심야프리미엄', '일반': '고속', '심야일반': '심야고속'}
SUBT = set()                                              # 시외로 받은 편 (출발, 도착, 분)
# 시외는 전환시외(나무위키 목록) 노선과 사람이 확인한 노선(force-links·list-chains 등)의 터미널 짝만 — 보통 시외는 싣지 않는다
SUBD = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'suburb')
HERE_ = os.path.dirname(os.path.abspath(__file__))
ALLOWED = {tuple(p) for p in json.load(open(os.path.join(SUBD, 'jeonhwan-jobs.json')))}
if os.path.exists(os.path.join(SUBD, 'extra-jobs.json')): ALLOWED |= {tuple(p) for p in json.load(open(os.path.join(SUBD, 'extra-jobs.json')))}
_map = json.load(open(os.path.join(SUBD, 'map.json')))
_seqs = json.load(open(os.path.join(HERE_, 'force-links.json'))) + json.load(open(os.path.join(HERE_, 'list-chains.json')))
_sb = json.load(open(os.path.join(HERE_, 'same-bus.json')))
_seqs += [x[:2] for x in _sb['drop'] + _sb['board']] + json.load(open(os.path.join(HERE_, 'partial-stops.json')))
for q in _seqs:
    q = [y for x in q for y in (x if isinstance(x, list) else [x])]      # 갈래 끝(["김해", "진해"])은 펼쳐서
    for a_ in q:
        for b_ in q:
            if a_ != b_:
                for _, ia in _map.get(a_, []):
                    for _, ib in _map.get(b_, []): ALLOWED.add((ia, ib))
SUBDROP = collections.Counter()
def sub_records(d):
    import glob as _g
    for f in _g.glob(os.path.join(SUB, d + '-*.json')):
        ids = tuple(os.path.basename(f)[:-5].split('-')[1:3])
        if ids not in ALLOWED: SUBDROP['보통 시외'] += 1; continue
        for r in json.load(open(f)):
            if str(r['depPlandTime'])[8:12] == '2359': SUBDROP['2359'] += 1; continue      # 23:59 발은 시각을 모르는 편(자료 잘못)으로 본다
            if r['depPlaceNm'] == '광주(경기)': r = dict(r, depPlaceNm='경기광주')            # 경기 광주: 책의 광주(유·스퀘어)와 다른 곳
            if r['arrPlaceNm'] == '광주(경기)': r = dict(r, arrPlaceNm='경기광주')
            r = dict(r, depPlaceNm=SUBNM.get(r['depPlaceNm'], r['depPlaceNm']), arrPlaceNm=SUBNM.get(r['arrPlaceNm'], r['arrPlaceNm']),
                     gradeNm=SG.get(r.get('gradeNm', ''), r.get('gradeNm', '')))
            yield r
for d in days:                                            # 시외: 고속과 같은 편(같은 구간·같은 분)이면 고속 쪽을 둔다
    for r in sub_records(d):
        o, x = r['depPlaceNm'], r['arrPlaceNm']
        if o == x: continue
        t = mins(r['depPlandTime']); du = (mins(r['arrPlandTime']) - t) % 1440
        SUBT.add((o, x, t))
        T[o][x][t].add(wd[d]); GD[(o, x, t)].add(r.get('gradeNm', '')); GD2.setdefault((o, x, t, wd[d]), set()).add(r.get('gradeNm', ''))
        info[o][x].append((du, r.get('charge') or 0))
EXPT = set()
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
            EXPT.add((o, x, t))
SUBT -= EXPT
def wdl(ws):
    ws = sorted(ws)
    if ws == [0, 1, 2, 3, 4]: return '월∼금'
    if len(ws) >= 3 and len(ws) < 7:                     # 이어진 요일은 「금∼월」처럼 (주를 넘어 이어져도)
        for s0 in ws:
            if sorted((s0 + k) % 7 for k in range(len(ws))) == ws: return WD[s0] + '∼' + WD[(s0 + len(ws) - 1) % 7]
    return '・'.join(WD[w] for w in ws)
# 두 주(이레 × 2)를 맞대어:
# · 다니는 요일: 나중 주에 한 번이라도 다니는 편만 싣고, 두 주 가운데 한 번이라도 다닌 요일은 다니는 날로 (하루 빠진 것은 거의 임의 결행)
# · 등급: 같은 요일인데 주마다 다르면 편마다 정해진 등급이 아니라 차가 돌아가며 바뀌는 것 → 등급 칸 ※, 행선지 밑에 「※ 가운데 날마다 1편 프리미엄」
LAST = set(days[-7:])                                      # 나중 주
GN = {'우등': '{우}', '고속': '{일}', '프리미엄': '{프}', '심야우등': '{심}', '심야프리미엄': '{심프}', '심야고속': '{심일}'}      # 책에서 등급 네모 표지로
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
for d in days:
    for r in sub_records(d):
        o, x = r['depPlaceNm'], r['arrPlaceNm']
        if o != x: PD[(o, x, mins(r['depPlandTime']))].setdefault(d, r.get('gradeNm', ''))
origins = []
nvar = 0
FILLED = []
FIRSTONLY = []
# 사람이 확인한 편 (decide.py 로 적음): daily 는 매일로, drop 은 빼기
DEC = json.load(open(os.path.join(HERE_, 'review-decisions.json'))) if os.path.exists(os.path.join(HERE_, 'review-decisions.json')) else {}
DEC_DAILY = {tuple(t) for e in DEC.get('daily', []) for t in e['trips']}
DEC_DROP = {tuple(t) for e in DEC.get('drop', []) for t in e['trips']}
DEC_KEEP = {tuple(t) for e in DEC.get('keep', []) for t in e['trips']}      # 요일 그대로가 맞음: 채우지도 목록에 올리지도 않음
MERGED1 = []
for o in sorted(T):
    dests = []
    for x in sorted(T[o]):
        ds = [du for du, _ in info[o][x]]; fs = [c for _, c in info[o][x] if c]
        dur = int(statistics.median(ds))
        times, var_t = [], []
        obs = {t: {wd[d_] for d_ in PD[(o, x, t)]} for t in T[o][x]}       # 편마다 다닌 요일 (자료 그대로)
        for t in sorted(T[o][x]):
            pd = PD[(o, x, t)]
            if (o, x, t) in DEC_DROP: continue
            if not (set(pd) & LAST) and (o, x, t) not in DEC_KEEP | DEC_DAILY: FIRSTONLY.append((o, x, t, sorted({wd[d_] for d_ in pd})))      # 나중 주에 없는 편: 결행했을 수도 있어 싣고 목록에
            byw = collections.defaultdict(set)
            for d, g in pd.items(): byw[wd[d]].add(g)
            gvar = any(len(v) > 1 for v in byw.values())
            miss_ = set(range(7)) - set(byw)                # 다섯 요일 넘게 다니는데 빠진 요일이 주말꼴(금·토·일)이 아니면 임의 결행으로 보고 날마다
            # 같은 구간 한 시간 안에 빠진 요일에만 다니는 편이 있으면 요일별 배차(세종의 월요일 편 따위)로 보고 채우지 않는다
            comp_ = any(u != t and abs(u - t) <= 60 and obs[u] and obs[u] <= miss_ for u in obs)
            if (o, x, t) in DEC_DAILY and miss_:
                g_all = collections.Counter(g for v in byw.values() for g in v).most_common(1)[0][0]
                for w_ in miss_: byw[w_] = {g_all}
            elif (o, x, t) in DEC_KEEP: pass
            elif len(byw) >= 5 and miss_ and not miss_ <= {4, 5, 6} and not comp_:
                g_all = collections.Counter(g for v in byw.values() for g in v).most_common(1)[0][0]
                for w_ in miss_: byw[w_] = {g_all}
                FILLED.append((o, x, t, sorted(miss_)))
            w = [0] * 7
            for w_, gs in byw.items():
                w[w_] = '◆' if gvar else (G.get(next(iter(gs)), '') or '우')
            hm = lambda m: '%d%02d' % (m // 60 % 24, m % 60)
            times.append([hm(t), hm(t + dur), w] + (['시'] if (o, x, t) in SUBT else []))      # 넷째 칸 「시」: 시외버스로 팔리는 편
            if gvar: var_t.append(t)
        # 1분 차이로 붙은 두 편(17:00·17:01 따위)은 한 편으로: 뒤의 것은 TAGO 의 겹친 편(증차·자료 잘못)으로 보고 요일을 앞 편에 합친다.
        # 한쪽만 시외(†)면 고속 쪽을 남긴다
        mm_ = lambda s_: int(s_[:-2]) * 60 + int(s_[-2:])
        times.sort(key=lambda tg: mm_(tg[0]))
        k_ = 0
        while k_ + 1 < len(times):
            a_, c_ = times[k_], times[k_ + 1]
            if mm_(c_[0]) - mm_(a_[0]) == 1:
                keep, drop = (c_, a_) if ('시' in a_[3:] and '시' not in c_[3:]) else (a_, c_)
                keep[2] = [keep[2][i] or drop[2][i] for i in range(7)]
                MERGED1.append((o, x, a_[0], c_[0], keep[0]))
                times[k_:k_ + 2] = [keep]
                continue
            k_ += 1
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
print('grade-rotating times', nvar, 'filled as daily', len(FILLED), 'first-week only', len(FIRSTONLY), 'merged 1-min', len(MERGED1), 'sub dropped', dict(SUBDROP), file=sys.stderr)
_mm = lambda s_: int(s_[:-2]) * 60 + int(s_[-2:])
_gone = {(o, x, _mm(a if k == b else b)) for o, x, a, b, k in MERGED1}     # 1분 차이로 합쳐 없어진 편은 확인 목록에서도 뺀다
FILLED = [e for e in FILLED if tuple(e[:3]) not in _gone]; FIRSTONLY = [e for e in FIRSTONLY if tuple(e[:3]) not in _gone]
json.dump({'filled': FILLED, 'firstonly': FIRSTONLY, 'merged1': MERGED1}, open(os.path.join(HERE_, 'bus-review-data.json'), 'w'), ensure_ascii=False)
json.dump({'days': days, 'origins': origins}, sys.stdout, ensure_ascii=False, indent=0)
print('origins', len(origins), 'dests', sum(len(o['dests']) for o in origins), 'times', sum(len(x['times']) for o in origins for x in o['dests']),
      'daily', sum(1 for o in origins for x in o['dests'] for t in x['times'] if all(t[2])), 'missing files', dict(miss), file=sys.stderr)
