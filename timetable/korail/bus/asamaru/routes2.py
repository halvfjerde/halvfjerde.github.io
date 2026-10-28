#!/usr/bin/env python3
"""bus.json(make_bus3, 이레치 합친 것) → 정류장이 여럿인 고속버스 노선을 다시 짜서 노선표(모듈:Timetable 원문)와 나머지 목록으로 나눈다.

같은 차를 알아보는 두 가지 단서 (TAGO 는 구간(출발→도착)마다 따로 준다):
· 타는 곳: 같은 행선지 D 로 가는 A 발 시각에 늘 같은 δ(3∼120분)를 더하면 B 발 시각이 된다 → A 에서 탄 차가 B 를 지난다.
· 내리는 곳: 같은 출발지 A 에서 D1 로 가는 시각이 거의 다 D2 로 가는 시각과 같고 D1 소요가 짧다 → D1 을 거쳐 D2 로.
우연(잦은 터미널끼리는 아무 δ 로나 맞기 쉽다)을 거르려고, 다른 δ(또는 그 터미널의 발차 밀도)에서 맞는 비율을 귀무 확률로 두고
이항 꼬리 확률이 아주 작을 때만 받는다. 소요도 맞아야 한다(타는 곳: δ ≈ A 소요 − B 소요).
받은 단서로 (출발지, 시각, 행선지) 마디를 잇고, 이어진 덩이 하나가 버스 한 대.

python3 routes2.py bus.json routes.txt rest.json suspects.txt
  routes.txt   : 노선표 원문 (위키 문서 꼴: == 고속버스 == 밑에 표마다 {{#invoke:Timetable}})
  rest.json    : 노선표에 들지 않은 구간 (bus.json 꼴, 목록용)
  suspects.txt : 사람이 확인할 만한 것 (근거가 약한 단서, 한 차 안에서 시각이 엇갈린 것 등)"""
import json, sys, os, collections, math, re

b = json.load(open(sys.argv[1]))
m_ = lambda s: int(s[:-2]) * 60 + int(s[-2:])
hm = lambda x: '%d%02d' % (x // 60 % 24, x % 60)
hmd = lambda m: ('%d시간' % (m // 60) if m >= 60 else '') + (' ' if m >= 60 and m % 60 else '') + ('%d분' % (m % 60) if m % 60 or m < 60 else '')
WD = '월화수목금토일'
_OTF = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'only-trips.json')
for k_, v_ in (json.load(open(_OTF)) if os.path.exists(_OTF) else {}).items():     # 시각표에 있는 편만 (그 밖의 TAGO 편은 뺀다)・소요 고침
    A_, D_ = k_.split('|')
    for O in b['origins']:
        if O['from'] != A_: continue
        for X in O['dests']:
            if X['to'] != D_: continue
            if 'times' in v_: X['times'] = [t for t in X['times'] if t[0] in v_['times']]
            if 'dur' in v_:
                X['dur'] = v_['dur']
                for t in X['times']:
                    if t[1]: t[1] = '%d%02d' % divmod((m_(t[0]) + v_['dur']) % 1440, 60)
        O['dests'] = [X for X in O['dests'] if X.get('times')]
P = {}                                                   # (A, D) → 소요·요금·{발 분: 요일 칸}
for O in b['origins']:
    for X in O['dests']:
        P[(O['from'], X['to'])] = {'dur': X['dur'], 'fare': X.get('fare'), 't': {m_(t[0]): t[2] for t in X['times']}}
SUBN = {(O['from'], m_(t[0]), X['to']) for O in b['origins'] for X in O['dests'] for t in X['times'] if len(t) > 3}      # 시외버스로 파는 편
byD, byA = collections.defaultdict(list), collections.defaultdict(list)
for A, D in P: byD[D].append(A); byA[A].append(D)

def tail(n, k, p):
    """이항 꼬리 P(X ≥ k), X ~ B(n, p)"""
    p = min(max(p, 1e-9), 1 - 1e-9)
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))

sus = []
LB = []                                                  # 타는 곳 단서 (D, A, B, δ, n, pv)
for D, As in byD.items():
    for A in As:
        ta = P[(A, D)]['t']
        for B in As:
            if A == B: continue
            tb = P[(B, D)]['t']; mB = len(tb)
            if mB < 2: continue
            cnt = [sum(1 for t in ta if (t + d) % 1440 in tb) for d in range(0, 121)]
            d = max(range(3, 121), key=lambda d: cnt[d]); n = cnt[d]
            if n < 2 or n < 0.5 * mB: continue
            oth = [cnt[e] for e in range(0, 121) if abs(e - d) > 2 and (e - d) % 5 == 0]     # 같은 5분 격자 위의 다른 δ (시각이 5분 단위라)
            p0 = max(sum(oth) / len(oth) / mB, 0.004)
            pv = tail(mB, n, p0) * 118
            dd = P[(A, D)]['dur'] - P[(B, D)]['dur']
            if pv > 1e-4 or abs(d - dd) > 25:
                if pv < 1e-2 and abs(d - dd) <= 40: sus.append('버림 타는곳 %s→%s (→%s) δ%d 맞음 %d/%d p=%.1e 소요차 %d' % (A, B, D, d, n, mB, pv, dd))
                continue
            LB.append((D, A, B, d, n, pv))
            if pv > 1e-7 or n < 3: sus.append('약함 타는곳 %s→%s (→%s) δ%d 맞음 %d/%d p=%.1e' % (A, B, D, d, n, mB, pv))
LD = []                                                  # 내리는 곳 단서 (A, D1, D2, n, pv)
for A, Ds in byA.items():
    allt = sorted({t for D in Ds for t in P[(A, D)]['t']})
    slots = max(30, (allt[-1] - allt[0]) // 5 + 1) if allt else 200
    for D1 in Ds:
        t1 = P[(A, D1)]['t']; m1 = len(t1)
        if m1 < 2: continue
        for D2 in Ds:
            if D1 == D2: continue
            t2 = P[(A, D2)]['t']
            n = len(set(t1) & set(t2))
            if n < 0.9 * m1 or n < 2: continue
            if P[(A, D1)]['dur'] > P[(A, D2)]['dur']: continue
            if P[(A, D1)]['dur'] == P[(A, D2)]['dur'] and (len(t2), D2) < (len(t1), D1): continue
            sh = [len({(t + e) % 1440 for t in t1} & set(t2)) / m1 for e in range(-60, 61, 5) if e]
            p0 = max(sum(sh) / len(sh), len(t2) / slots, 0.004)       # 시각을 어긋내도 맞는 비율 (정시·반시 같은 격자 탓)
            pv = tail(m1, n, p0) * len(Ds)
            if pv > 1e-4:
                if pv < 1e-2: sus.append('버림 내리는곳 %s: %s→%s 맞음 %d/%d p=%.1e' % (A, D1, D2, n, m1, pv))
                continue
            LD.append((A, D1, D2, n, pv))
            if pv > 1e-7 or n < 3: sus.append('약함 내리는곳 %s: %s 거쳐 %s 맞음 %d/%d p=%.1e' % (A, D1, D2, n, m1, pv))

# 서로 확인: 실제 노선이면 반대 방향에도 흔적이 있다 (A→B→D 이면 D 에서 B·A 로 가는 시각이 겹친다),
# 아니면 두 정류장 사이를 바로 잇는 구간의 소요가 δ 와 맞는다. 둘 다 없으면 버린다 (먼 두 터미널의 시간표 격자가 우연히 맞는 일)
near = lambda x, y, d: any(abs(P[k]['dur'] - d) <= max(10, 0.35 * d) for k in ((x, y), (y, x)) if k in P)
def rev_drop(D, X, Y):
    """D 에서 X·Y 로 가는 시각이 거의 같은가 (반대 방향의 같은 차). 소요의 앞뒤는 보지 않는다 (TAGO 소요는 가끔 뒤바뀐다)"""
    if (D, X) not in P or (D, Y) not in P: return False
    tx, ty = P[(D, X)]['t'], P[(D, Y)]['t']
    m = min(len(tx), len(ty)); n = len(set(tx) & set(ty))
    if m < 2 or n < 0.8 * m: return False
    sm, bg = (tx, ty) if len(tx) <= len(ty) else (ty, tx)
    sh = [len({(t + e) % 1440 for t in sm} & set(bg)) / len(sm) for e in range(-60, 61, 5) if e]
    return tail(len(sm), n, max(sum(sh) / len(sh), 0.004)) * 20 < 1e-3
def rev_board(A, X, Y):
    """X·Y 에서 A 로 가는 시각이 늘 같은 δ 로 맞물리는가 (반대 방향의 같은 차)"""
    if (X, A) not in P or (Y, A) not in P: return False
    for p, q in ((X, Y), (Y, X)):
        tp_, tq = P[(p, A)]['t'], P[(q, A)]['t']
        cnt = [sum(1 for t in tp_ if (t + d) % 1440 in tq) for d in range(0, 121)]
        d = max(range(0, 121), key=lambda d: cnt[d]); n = cnt[d]; m = min(len(tp_), len(tq))
        if m < 2 or n < 0.8 * m: continue
        oth = [cnt[e] for e in range(0, 121) if abs(e - d) > 2 and (e - d) % 5 == 0]
        if tail(m, n, max(sum(oth) / len(oth) / m, 0.004)) * 120 < 1e-3: return True
    return False
GEO = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'geo.json')))      # 터미널 어림 좌표 (손으로 적은 것, 길에서 벗어났는지만 본다)
def km(x, y):
    (a1, o1), (a2, o2) = GEO[x], GEO[y]
    p = math.radians((a1 + a2) / 2)
    return math.hypot((a1 - a2) * 111.0, (o1 - o2) * 111.0 * math.cos(p))
def on_way(A, B, D):
    """B 가 A 에서 D 로 가는 길목인가: 돌아가는 거리가 짧을 때만"""
    return km(A, B) + km(B, D) <= max(1.12 * km(A, D), km(A, D) + 25)
unconf = []
LB2 = []
for x in LB:
    D, A, B, d, n, pv = x
    if not on_way(A, B, D) or not (0.6 * km(A, B) - 8 <= d <= 2.5 * km(A, B) + 30):     # 시속 100km 보다 빠를 수 없다
        sus.append('버림(길에서 벗어남) 타는곳 %s→%s (→%s) δ%d 맞음 %d' % (A, B, D, d, n)); continue
    LB2.append(x)                                        # 사람이 확인하므로 길목·속도만 맞으면 넣고, 반대 방향 등으로 확인 안 된 것은 목록에
    if not (rev_drop(D, A, B) or near(A, B, d) or pv < 1e-12): unconf.append(((A, B, D), '%s → %s (%d분 뒤) … %s 행, %d번 맞물림' % (A, B, d, D, n)))
LD2 = []
for x in LD:
    A, D1, D2, n, pv = x
    dd = P[(A, D2)]['dur'] - P[(A, D1)]['dur']
    if not on_way(A, D1, D2) or dd < 0.6 * km(D1, D2) - 15:
        sus.append('버림(길에서 벗어남) 내리는곳 %s: %s 거쳐 %s 맞음 %d' % (A, D1, D2, n)); continue
    LD2.append(x)
    if not (pv < 1e-12 or rev_board(A, D1, D2) or near(D1, D2, dd) or (n == len(P[(A, D1)]['t']) == len(P[(A, D2)]['t']) and n >= 3)):
        unconf.append(((A, D1, D2), '%s 발 %s 행이 %s 에 들름, 같은 시각 %d번' % (A, D2, D1, n)))
LB, LD = LB2, LD2
# 일부 편만 서는 정류장(partial-stops.json: [A, B, D])은 표로 잇지 않는다: A 의 편이 아주 많아 우연히도 맞물리고, B 는 다른 노선(노선표)의 정류장이기도 해서
PART = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'partial-stops.json')))
SHARED = {p for A, B_, D in PART for p in ((B_, D), (D, B_))}         # 노선표가 이 구간을 갖지 않고 목록에 다 둔다
LB = [x for x in LB if not any((x[0], x[1], x[2]) == (D, A, B_) for A, B_, D in PART)]
LD = [x for x in LD if not any((x[0], x[1], x[2]) == (D, B_, A) for A, B_, D in PART)]
# 사람이 확인한 같은 차(force-links.json: 정류장 차례): 맞물린 편이 하나뿐이어도 잇는다 (시각이 맞는 δ 로)
# 한 끝이 갈래인 노선은 그 자리에 정류장 목록을 둔다: ["광주", …, "창원", ["김해", "진해"]] — 한 표에 갈래로 (다른 갈래 칸은 ║)
FORCE = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'force-links.json')))
flat_ = lambda q: [y for x in q for y in (x if isinstance(x, list) else [x])]
def lin_(q):
    out_ = [[]]
    for x in q: out_ = [o + [y] for o in out_ for y in (x if isinstance(x, list) else [x])]
    return out_
fpos = lambda q, s_: next(i for i, x in enumerate(q) if x == s_ or (isinstance(x, list) and s_ in x))
FORCE_LIN = [l_ for q in FORCE for l_ in lin_(q)]
# 서로 다른 길(alt-stops.json: 진주개양|진주혁신 따위)은 한 차가 둘 다 들르지 않는다 → 그 둘 사이는 잇지 않는다
ALTP = {(x, y) for A_ in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'alt-stops.json')))
        for g in A_ for g2 in A_ if g2 is not g for x in g for y in g2}
have = {(D, A, B) for D, A, B, *_ in LB}
haved = {(A, D1, D2) for A, D1, D2, *_ in LD}
for seq in FORCE_LIN:
    for i, A in enumerate(seq):
        for B in seq[i + 1:]:
            for D in seq[seq.index(B) + 1:]:                 # 타는 곳: A 다음 B, 둘 다 D 로
                if (A, D) in P and (B, D) in P and (D, A, B) not in have and (A, B) not in ALTP:
                    ta, tb = P[(A, D)]['t'], P[(B, D)]['t']
                    arr_ = {t: t + P[(A, B)]['dur'] for t in ta if (A, B) in P and t in P[(A, B)]['t']}    # 같은 차가 B 에 닿는 때: 그보다 먼저 B 에서 떠날 수는 없다
                    cnt = {d: sum(1 for t in ta if (t + d) % 1440 in tb and (t not in arr_ or arr_[t] - 10 <= t + d <= arr_[t] + 20)) for d in range(0, 421)}   # 닿고 20분 넘게 서 있지도 않는다 (부산 1110 이 순천에서 20분 넘게 서 있다 여천 1319 동네 시외로: 우연)
                    dd_ = P[(A, D)]['dur'] - P[(B, D)]['dur']
                    d = max(cnt, key=lambda d: (cnt[d], -abs(d - dd_)))          # 같으면 소요 차에 가까운 δ
                    # B→D 가 촘촘하면(20편 넘게: 전주→광주, 원주문막→서울경부 따위) 아무 δ 로나 몇 편은 맞는다 → A 의 편이 (거의) 모두 같은 δ 로 맞을 때만
                    ok_ = cnt[d] >= 1 if len(tb) <= 20 else cnt[d] >= max(3, 0.9 * len(ta))
                    if ok_ and abs(d - dd_) <= max(30, 0.2 * abs(dd_)): LB.append((D, A, B, d, cnt[d], 0.0)); have.add((D, A, B))   # 소요 차와 아주 다른 δ 는 우연
            for D2 in seq[i + 1:]:                           # 내리는 곳: A 에서 B(먼저) 거쳐 D2
                if D2 != B and seq.index(D2) > seq.index(B) and (A, B) in P and (A, D2) in P and (A, B, D2) not in haved and (B, D2) not in ALTP:
                    n = len(set(P[(A, B)]['t']) & set(P[(A, D2)]['t']))
                    if n >= 1: LD.append((A, B, D2, n, 0.0)); haved.add((A, B, D2))

# 마디 (A, t, D) 를 단서로 잇는다
par = {}
EDG = []                                                # 이은 단서 (마디, 마디, 착 어긋남)
def f(x):
    par.setdefault(x, x)
    while par[x] != x: par[x] = par[par[x]]; x = par[x]
    return x
def u(x, y): par[f(x)] = f(y)
# 사람이 확인한 노선(force-links)의 정류장 셋(타는 곳 A·B, 행선지 D / 출발 A, 내리는 곳 B·D2)으로 이은 마디는 그 노선의 것:
# 그 마디에는 통계로만 찾은 다른 단서를 잇지 않는다 (배방 605 ← 공주 600 따위 우연)
FLB = {(D, A, B) for q in FORCE_LIN for i_, A in enumerate(q) for B in q[i_ + 1:] for D in q[q.index(B) + 1:]}
FLD = {(A, B, D2) for q in FORCE_LIN for i_, A in enumerate(q) for B in q[i_ + 1:] for D2 in q[q.index(B) + 1:]}
# 그 노선 단서만으로 이은 덩이 가운데 노선의 첫 자리(갈래면 그 정류장들)에서 떠나는 것만 지킨다 (기지시→서산 은 부산 차도 대전복합 차도 탄다)
fp_ = {}
def ff_(x):
    fp_.setdefault(x, x)
    while fp_[x] != x: fp_[x] = fp_[fp_[x]]; x = fp_[x]
    return x
for D, A, B, d, n, pv in LB:
    if (D, A, B) in FLB:
        tb = P[(B, D)]['t']
        for t in P[(A, D)]['t']:
            if (t + d) % 1440 in tb: fp_[ff_((A, t, D))] = ff_((B, (t + d) % 1440, D))
for A, D1, D2, n, pv in LD:
    if (A, D1, D2) in FLD:
        for t in P[(A, D1)]['t']:
            if t in P[(A, D2)]['t']: fp_[ff_((A, t, D1))] = ff_((A, t, D2))
fcomp_ = collections.defaultdict(list)
for x in list(fp_): fcomp_[ff_(x)].append(x)
def head_(q):
    for x in q:
        xs_ = [y for y in (x if isinstance(x, list) else [x]) if any(y in p_ for p_ in P)]
        if xs_: return set(xs_)
    return set()
FHEAD = [(set(flat_(q)), head_(q)) for q in FORCE]
FN = set()
for ns_ in fcomp_.values():
    st_ = {x[0] for x in ns_} | {x[2] for x in ns_}
    t0_ = min(x[1] for x in ns_)
    org_ = {x[0] for x in ns_ if x[1] == t0_}                 # 가장 먼저 떠나는 곳
    if any(st_ <= qs and org_ & hd for qs, hd in FHEAD): FN |= set(ns_)
for D, A, B, d, n, pv in LB:
    tb = P[(B, D)]['t']
    for t in P[(A, D)]['t']:
        if (t + d) % 1440 in tb:
            if (A, B) in P and t in P[(A, B)]['t'] and not (P[(A, B)]['dur'] - 10 <= d <= P[(A, B)]['dur'] + 20): continue      # B 에 닿기 전(또는 한참 뒤) B 발: 다른 차
            x_, y_ = (A, t, D), (B, (t + d) % 1440, D)
            if (D, A, B) not in FLB and (x_ in FN or y_ in FN): continue
            u(x_, y_); EDG.append((x_, y_, abs(d - (P[(A, D)]['dur'] - P[(B, D)]['dur']))))
for A, D1, D2, n, pv in LD:
    t2 = P[(A, D2)]['t']
    for t in P[(A, D1)]['t']:
        if (A, D1, D2) not in FLD and ((A, t, D1) in FN or (A, t, D2) in FN): continue
        if t in t2: u((A, t, D1), (A, t, D2)); EDG.append(((A, t, D1), (A, t, D2), 0))
for la_, lb_ in (json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'manual-links.json'))) if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'manual-links.json')) else []):
    x_, y_ = (la_[0], m_(la_[1]), la_[2]), (lb_[0], m_(lb_[1]), lb_[2])     # 사람이 확인한 같은 차 (진도 1330 = 무안 1440)
    if x_[1] in P.get((x_[0], x_[2]), {}).get('t', {}) and y_[1] in P.get((y_[0], y_[2]), {}).get('t', {}): u(x_, y_); EDG.append((x_, y_, 0))
for (A_, D_), v_ in P.items():                         # 인천공항 버스는 이어지지 않은 한 구간 차도 마디로 (주문진 ⇄ 인천공항2터미널, 공항 발 시외)
    if A_.startswith('인천공항') or D_.startswith('인천공항'):
        for t_ in v_['t']: f((A_, t_, D_))
comp = collections.defaultdict(list)
for x in list(par): comp[f(x)].append(x)
# 한 차에 같은 곳 발이 둘(엇갈림): 버리지 않고, 착이 잘 맞는 단서부터 다시 이어 엇갈리는 단서(착이 10분 넘게 어긋나는 것)는 뺀다
#   경포해변 1340 → 강릉 1400 과 강릉 1420 → 관동대 1425 를 경포해변 → 관동대(δ45, 착 20분 어긋남)가 한 차로 묶던 것
def bad_(ns):
    bd_ = {}
    for A, t, D in ns:
        if bd_.setdefault(A, t) != t: return True
    return False
FSETS = [set(flat_(q)) for q in FORCE]
inch_ = lambda ns: any({x[0] for x in ns} | {x[2] for x in ns} <= q for q in FSETS)
FEDG = {(x_, y_) for x_, y_, dv in EDG if (x_[2], x_[0], y_[0]) in FLB or (x_[0], x_[2], y_[2]) in FLD}
FEN = {x for e in FEDG for x in e}
# 사람이 확인한 두 노선의 차가 한 차로 묶인 것(무안 1440 → 영광 1520 이 임자 ― 함평 ― 영광 차와)도 다시 잇는다: 두 노선을 섞는 단서는 뺀다
BADN = {x for ns in comp.values() if len(ns) > 1 and (bad_(ns) or (not inch_(ns) and any(x in FEN for x in ns))) for x in ns}
if BADN:
    mem_ = {x: [x] for x in BADN}
    for x in BADN: par[x] = x
    for x_, y_, dv in sorted(EDG, key=lambda e: e[2]):
        if x_ not in BADN or dv > 10: continue
        rx, ry = f(x_), f(y_)
        if rx == ry or bad_(mem_[rx] + mem_[ry]): continue
        if inch_(mem_[rx]) and inch_(mem_[ry]) and not inch_(mem_[rx] + mem_[ry]): continue
        par[rx] = ry; mem_[ry] += mem_.pop(rx)
    comp = collections.defaultdict(list)
    for x in list(par): comp[f(x)].append(x)
trips = []
for nodes in comp.values():
    if len(nodes) < 2 and not (nodes[0][0].startswith('인천공항') or nodes[0][2].startswith('인천공항')): continue      # 인천공항 버스는 한 구간뿐인 차도 (주문진 ⇄ 인천공항2터미널)
    board, bad = {}, False
    for A, t, D in nodes:
        if A in board and board[A] != t: bad = True
        board[A] = min(board.get(A, t), t)
    if bad:                                             # 한 차에 같은 곳 발이 둘: 서로 다른 차가 잘못 이어졌다 → 노선표에 넣지 않는다
        sus.append('엇갈림(버림) %s' % ' '.join(sorted('%s%s→%s' % (A, hm(t), D) for A, t, D in nodes)[:12]))
        continue
    drop = {}
    for A, t, D in nodes:                              # 내리는 곳 착: 가장 늦게 탄 곳에서 잰 것
        a = (t + P[(A, D)]['dur']) % 1440
        if D not in drop or t > drop[D][1]: drop[D] = (a, t)
    first = min(board, key=lambda A: (board[A] - min(board.values())) % 1440)
    w = list(P[(first, next(D for A, t, D in nodes if A == first))]['t'][board[first]])
    for A, t, D in nodes:                               # 다니는 요일: 한 차의 어느 구간에서든 그날 다니면 다닌다 (구간마다 팔린 날이 조금씩 빠지기도)
        if A != first and len(P[(A, D)]['t']) > 20: continue      # 다만 촘촘한 구간(원주문막→서울경부 따위)은 다른 차와 시각이 겹치기도 해서 요일을 보태지 않는다
        for d_, g_ in enumerate(P[(A, D)]['t'][t]):
            if g_ and not w[d_]: w[d_] = g_
    trips.append({'board': board, 'drop': {D: a for D, (a, _) in drop.items()}, 'w': w, 'nodes': nodes, 'sub': any(x in SUBN for x in nodes)})

# 전환시외 목록의 구간으로만 받은 시외(sub-jh.json) 가운데 동네 시외는 뺀다: 그 노선의 끝과 끝(어느 방향이든)을 오가는 편,
# 고속(또는 끝과 끝을 오가는 전환시외) 차와 한 차로 이어지는 편만 둔다 (순천 → 여수 50편, 광주 ⇄ 목포 60편 따위 동네 시외는 빼고)
HERE2_ = os.path.dirname(os.path.abspath(__file__))
_jf = os.path.join(HERE2_, 'sub-jh.json')
SUBJ = {(o, t, x) for o, t, x in json.load(open(_jf))} & SUBN if os.path.exists(_jf) else set()
_JHA = {'거제(고현동)': ['고현'], '광주': ['광주(유·스퀘어)'], '광주(유•스퀘어)': ['광주(유·스퀘어)'], '대구': ['동대구', '서대구'], '대구서부': ['서대구'],
        '대전': ['대전복합'], '부산(노포동)': ['부산'], '부산(사상)': ['부산사상'], '부산서부(사상)': ['부산사상'], '서울(경부)': ['서울경부'],
        '서울(호남)': ['센트럴시티(서울)'], '서울호남': ['센트럴시티(서울)'], '시흥(시화)': ['시흥시화'], '안양': ['안양역'], '울산시외': ['울산'],
        '인천공항': ['인천공항T1', '인천공항T2'], '임자도': ['임자(진리)'], '천안(시외)': ['천안'], '포항(시외)': ['포항'], '동광양(중마동)': ['동광양'],
        '청주': ['청주(센트럴)'], '세종': ['세종터미널(연구)']}
_jhn = lambda n: _JHA.get(n.split(':')[0].strip(), [n.split(':')[0].strip()])
JHE = set()
_jj = os.path.join(HERE2_, '..', 'suburb', 'jeonhwan.json')
for q_ in (json.load(open(_jj)) if os.path.exists(_jj) else []):
    for a_ in _jhn(q_[0]):
        for d_ in _jhn(q_[-1]): JHE |= {(a_, d_), (d_, a_)}
_keepJ = lambda x: (x[0], x[2]) in JHE
JDROP = set()
for tr in trips:
    if any(x not in SUBN or _keepJ(x) for x in tr['nodes']): continue          # 고속 차 또는 끝과 끝을 오가는 편과 이어진 차: 둔다
    JDROP |= {x for x in tr['nodes'] if x in SUBJ}
_intr = {x for tr in trips for x in tr['nodes']}
JDROP |= {x for x in SUBJ if x not in _intr and not _keepJ(x)}
if JDROP:
    trips = [tr for tr in trips if not any(x in JDROP for x in tr['nodes'])]
    for A, t, D in JDROP: P[(A, D)]['t'].pop(t, None)
    for O in b['origins']:
        for X in O['dests']: X['times'] = [t for t in X['times'] if (O['from'], m_(t[0]), X['to']) not in JDROP]
        O['dests'] = [X for X in O['dests'] if X['times']]
    b['origins'] = [O for O in b['origins'] if O['dests']]
    for k_ in [k_ for k_, v_ in P.items() if not v_['t']]: del P[k_]
    SUBN -= JDROP
print('전환시외 구간의 동네 시외 뺌', len(JDROP), file=sys.stderr)
SEQ = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stop-order.json')))   # 확인한 차례들
# 표 묶음: 끝 행선지(가장 늦게 닿는 곳)가 같고 타는 곳이 겹치는 차끼리
def last(tr): return max(tr['drop'], key=lambda D: (tr['drop'][D] - min(tr['board'].values())) % 1440)
tp = list(range(len(trips)))
def g(i):
    while tp[i] != i: tp[i] = tp[tp[i]]; i = tp[i]
    return i
seen = {}
KS_ = {x for p_ in P for x in p_}                       # 자료에 있는 정류장 (아산온양처럼 덧붙인 끝 정류장은 빼고 노선의 끝을 본다)
def fkey(tr):
    """사람이 확인한 노선(force-links)의 정류장만 지나는 차: 그 노선(방향)으로 한 표에 (끝 정류장이 달라도)"""
    st = set(tr['board']) | set(tr['drop'])
    dense_ = all(len(P[(A, D)]['t']) > 20 for A, t, D in tr['nodes'])     # 촘촘한 구간끼리만 맞물린 차(광주→전주·호남제일 따위)는 그 노선의 차로 보지 않는다
    first = min(tr['board'], key=lambda A: (tr['board'][A] - min(tr['board'].values())) % 1440)
    ks = [i for i, seq in enumerate(FORCE) if st <= set(flat_(seq))]
    if all(x in SUBN for x in tr['nodes']):              # 시외로만 팔린 차는 그 노선의 첫 정류장에서 떠날 때만 (목포→해남→완도, 여천→광양→동광양 같은 동네 시외는 빼고)
        def starts_(q):                                  # 노선의 첫 자리(갈래면 그 정류장들) — 자료에 있는 것부터
            for x in q:
                xs_ = [y for y in (x if isinstance(x, list) else [x]) if y in KS_]
                if xs_: return set(xs_)
            return set()
        ks = [i for i in ks if first in starts_(FORCE[i])]
    if dense_:                                          # 다만 노선의 두 끝을 다 지나는 차(서울경부 ― 안성풍림 ― 안성공도 ― 안성: 모든 구간이 촘촘)는 그 노선으로
        ends_ = lambda q: [x for x in flat_(q) if x in KS_]
        ks = [i for i in ks if ends_(FORCE[i]) and ends_(FORCE[i])[0] in st and ends_(FORCE[i])[-1] in st]
    agree = lambda q: sum(1 for A in tr['board'] for D in tr['drop'] if A != D and fpos(q, A) < fpos(q, D))      # 타는 곳이 내리는 곳보다 앞인 방향 (TAGO 가 같은 시각을 붙여 첫 정류장이 헷갈려도)
    return min(ks, key=lambda i: (-agree(FORCE[i]), fpos(FORCE[i], first))) if ks else None
for i, tr in enumerate(trips):
    fk = fkey(tr)
    if fk is not None:
        k = ('F', fk)
        if k in seen: tp[g(i)] = g(seen[k])
        else: seen[k] = i
    L = last(tr)
    for A in tr['board']:
        k = (L, A, fk)                                  # 사람이 확인한 노선의 차는 그 밖의 차와, 다른 노선의 차와도 (끝·타는 곳이 같아도) 섞지 않는다 (임자 노선・진도 노선이 영광에서)
        if k in seen: tp[g(i)] = g(seen[k])
        else: seen[k] = i
groups = collections.defaultdict(list)
for i in range(len(trips)): groups[g(i)].append(trips[i])

BJF_ = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'branch-join.json')
BJOIN = json.load(open(BJF_)) if os.path.exists(BJF_) else []
tables, owned = [], set()
SKIPOWN = set()
N2T = {x: tr for tr in trips for x in tr['nodes']}
ABSORB = set()                                          # 사람이 확인한 노선 표가 가져간 다른 묶음의 차
NNF = collections.Counter()                             # 사람이 확인한 노선 표의 구간마다 노선 차 수 (반대 방향과 맞추려고)
for grp in groups.values():
    fks_ = {fkey(tr) for tr in grp}
    if len(fks_) == 1 and None not in fks_:
        for tr in grp:
            for A, t, D in tr['nodes']: NNF[(A, D)] += 1
dense_raw = lambda p: len(P[p]['t']) > 3 * NNF[p] + 5
NNG = collections.defaultdict(collections.Counter)     # 구간 → 확인한 노선마다 그 구간을 다니는 노선 차의 몫: 두 노선 표가 한 구간을 지나면 몫이 큰 노선 표가 그 구간의 다른 차를 갖는다 (서울 → 영광: 임자 노선 표, 무안 노선 표 아님)
for grp in groups.values():
    fks_ = {fkey(tr) for tr in grp}
    if len(fks_) == 1 and None not in fks_:
        fk_ = fks_.pop()
        for p_ in {(A, D) for tr in grp for A, t, D in tr['nodes']}:
            NNG[p_][fk_] += sum(1 for tr in grp if any((A, D) == p_ for A, t, D in tr['nodes'])) / len(grp)     # 노선 차 가운데 그 구간을 다니는 몫
for grp in groups.values():
    span = lambda tr: (tr['drop'][last(tr)] - min(tr['board'].values())) % 1440
    L = last(max(grp, key=span))                      # 끝 행선지가 여럿이면(확인한 노선) 가장 멀리 가는 것
    # 정류장 차례: 끝 행선지 착까지 남은 시간이 긴 차례 (타는 곳), 그다음 내리는 곳은 착이 이른 차례
    rem = collections.defaultdict(list)
    for tr in grp:
        aL = tr['drop'].get(L)
        if aL is None: continue
        for A, t in tr['board'].items(): rem[A].append((aL - t) % 1440)
        for D, a in tr['drop'].items():
            if D not in tr['board']: rem[D].append((aL - a) % 1440 - 0.5)
    stops = sorted(rem, key=lambda s: -sum(rem[s]) / len(rem[s]))
    for seq in SEQ:                                     # 사람이 확인한 정류장 차례 (어느 방향이든)
        idx = [k for k, s_ in enumerate(stops) if s_ in seq]
        if len(idx) < 2: continue
        cur = [stops[k] for k in idx]
        fw = sorted(cur, key=seq.index); bw = fw[::-1]
        agree = lambda o: sum(1 for a in range(len(o)) for b_ in range(a + 1, len(o)) if cur.index(o[a]) < cur.index(o[b_]))
        best = fw if agree(fw) >= agree(bw) else bw
        for k, s_ in zip(idx, best): stops[k] = s_
    fks = {fkey(tr) for tr in grp}
    isforce = len(fks) == 1 and None not in fks
    brs_, brl_ = {}, {}
    if len(fks) == 1 and None not in fks:               # 사람이 확인한 노선: 그 차례대로 (TAGO 가 같은 시각을 붙인 곳도 차례가 맞게)
        sq0_ = FORCE[fks.pop()]; sq_ = flat_(sq0_)
        stops = sorted({s_ for tr in grp for s_ in list(tr['board']) + list(tr['drop'])}, key=lambda s_: sq_.index(s_) if s_ in sq_ else len(sq_))   # 끝까지 가지 않는 차의 정류장도
        brs_ = {s_: j for x in sq0_ if isinstance(x, list) for j, s_ in enumerate(sorted(x)) if s_ in stops}    # 갈래 정류장 → 갈래 번호 (이름 차례로: 두 방향 표를 한 표로 합쳐도 같게)
        # [..., "창원", ["진해", "김해"]]: (창원, 진해) 와 (김해) 로 갈린다 — 줄기 쪽 첫 갈래(진해)와 갈리는 정류장(창원)을 한 덩이로, 덩이마다 위아래 선
        brl_ = dict(brs_)                               # 선 긋기: 갈래마다 한 덩이, 갈리는 정류장은 줄기에 (서산・당진・기지시 | 대전복합 | 청주공항 …)
        for jn_, bs_ in BJOIN:                          # 다만 branch-join.json 에 적은 것은 그 갈래 덩이에: ["창원", "진해"] → (창원, 진해) | (김해)
            if jn_ in stops and bs_ in brs_: brl_[jn_] = brs_[bs_]
    bset = {A for tr in grp for A in tr['board']}
    dset = {D for tr in grp for D in tr['drop']} - bset
    pairs = {(A, D) for tr in grp for A, t, D in tr['nodes']}
    nn = collections.Counter((A, D) for tr in grp for A, t, D in tr['nodes'])
    dense = {p for p in pairs if len(P[p]['t']) > 3 * nn[p] + 5 and not (NNF[p[::-1]] and not dense_raw(p[::-1]))}   # 반대 방향 표가 그 구간을 다 가지면 이쪽도 (서울경부 ⇄ 강릉)      # 이 노선의 차는 몇 편뿐인 촘촘한 구간(광주→목포 따위): 표가 갖지 않고 목록에 둔다
    if isforce: SKIPOWN.update(dense)                    # 그 목록 덩이에서는 표에 실린 편을 빼고 「이 밖에 노선표」
    if isforce: fk0_ = fkey(grp[0]); pairs = {p for p in pairs if NNG[p][fk0_] >= max(NNG[p].values())}
    pairs = {p for p in pairs if p not in owned and p not in SHARED and p not in dense}
    owned |= pairs
    cols = []
    for tr in grp:
        cols.append({s: ('d', tr['board'][s]) if s in tr['board'] else ('a', tr['drop'][s]) for s in stops if s in tr['board'] or s in tr['drop']} | {'_w': tr['w'], '_sub': tr['sub'], '_tid': id(tr)})
    used = {(A, t, D) for tr in grp for A, t, D in tr['nodes']}
    skip_ = set()
    def se_of(q):
        el_ = lambda x: {y for y in (x if isinstance(x, list) else [x]) if y in KS_}
        qs = [el_(x) for x in q if el_(x)]
        return (qs[0], qs[-1]) if qs else (set(), set())
    se_ = se_of(sq0_) if isforce else (set(), set())
    for A, D in sorted(pairs):                         # 그 구간의 다른 차(정류장을 거치지 않는 차)도 이 표에
        for t, w in P[(A, D)]['t'].items():
            x = (A, t, D)
            if x in used: continue
            if x in par and len(comp.get(f(x), [])) > 1:      # 다른 표의 차 — 다만 사람이 확인한 노선 표면 그 노선 정류장만 지나는 차는 여기 싣는다 (대전청사 발 전주 행: 대전복합을 거치지 않아 노선 차로 못 본 것)
                tr2 = N2T.get(x)
                if isforce and tr2 is not None and id(tr2) not in ABSORB and (set(tr2['board']) | set(tr2['drop'])) <= set(stops):
                    cols.append({s: ('d', tr2['board'][s]) if s in tr2['board'] else ('a', tr2['drop'][s]) for s in stops if s in tr2['board'] or s in tr2['drop']} | {'_w': tr2['w'], '_sub': tr2['sub'], '_tid': id(tr2)})
                    used |= set(tr2['nodes']); ABSORB.add(id(tr2))
                continue
            if isforce and x in SUBN and not (A in se_[0] and D in se_[1]): skip_.add((A, D)); continue    # 사람이 확인한 노선 표에는 노선 중간 구간의 시외(목포→해남 따위 동네 시외)를 싣지 않는다 (처음부터 끝까지 가는 시외는 싣는다: 고창 → 인천공항)
            cols.append({A: ('d', t), D: ('a', (t + P[(A, D)]['dur']) % 1440), '_w': w, '_sub': x in SUBN})
    def key(c):
        for k_, s in enumerate(stops):
            if s in c: return (c[s][1] - 0) % 1440 + (0 if c[s][1] >= 240 else 1440), k_
    cols.sort(key=key)
    if skip_: pairs -= skip_; owned -= skip_; SKIPOWN.update(skip_)     # 그 구간은 목록에 (표에 실린 편은 빼고)
    for c in cols:                                     # 갈래 끝 노선: 차마다 제 갈래
        js_ = {brs_[s_] for s_ in c if s_ in brs_}
        if len(js_) == 1: c['_br'] = js_.pop()
    tables.append({'stops': stops, 'board': bset, 'cols': cols, 'pairs': pairs, 'last': L, 'force': isforce} | ({'branch': brs_, 'brline': brl_} if len(set(brs_.values())) > 1 else {}))

# 이틀씩 번갈아 다니는 노선(alt-routes.json): 등급마다 서는 곳이 다르다 (수원 ― 삼척: 프리미엄은 강원대, 우등은 삼척해변).
# 한 시각에 한 칸: 등급마다 들르는 곳을 모두 싣고 시각은 느린 쪽, 비고에 등급마다 들르는 곳. 자동으로 만든 표 가운데 이 정류장들만 쓰는 것은 버리고 새로 짠다
ALTF = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'alt-routes.json')
for R_ in (json.load(open(ALTF)) if os.path.exists(ALTF) else []):
    seq_, S_ = R_['seq'], set(R_['seq'])
    for T in [T for T in tables if set(T['stops']) <= S_]: tables.remove(T); owned -= T['pairs']
    vst_ = {s_ for v in R_['variants'].values() for s_ in v}
    for path0 in (seq_, seq_[::-1]):
        if (path0[0], path0[-1]) not in P: continue
        cols, prs_ = [], set()
        for t in sorted(P[(path0[0], path0[-1])]['t'], key=lambda t: t + (1440 if t < 240 else 0)):
            m_c = {}
            for v, mine in R_['variants'].items():
                path = [s_ for s_ in path0 if s_ not in vst_ or s_ in mine]
                c, brd = {path[0]: ('d', t)}, [(path[0], t)]
                for k, B in enumerate(path[1:], 1):
                    cand = sorted((not set(x for x in w if x) <= {v}, (tb - t) % 1440, tb) for X in path[k + 1:] if (B, X) in P
                                  for tb, w in P[(B, X)]['t'].items() if 0 < (tb - t) % 1440 <= 90 and set(x for x in w if x) <= {v, '◆'})
                    if cand: c[B] = ('d', cand[0][2]); brd.append((B, cand[0][2])); continue          # 그 등급의 차가 타는 곳
                    for S2, ts in reversed(brd):                                                       # 내리는 곳: 가장 늦게 탄 곳에서 잰 착
                        if (S2, B) in P and ts in P[(S2, B)]['t']: c[B] = ('a', (ts + P[(S2, B)]['dur']) % 1440); break
                for A, ta in brd:
                    prs_ |= {(A, D) for D in path[path.index(A) + 1:] if D in c and (A, D) in P}
                for s_, x in c.items():
                    if s_ not in m_c or (x[1] - t) % 1440 > (m_c[s_][1] - t) % 1440: m_c[s_] = x
            m_c.update({'_w': ['◆'] * 7, '_sub': False, '_note': R_['note']})
            cols.append(m_c)
        tables.append({'stops': [s_ for s_ in path0 if any(s_ in c for c in cols)], 'board': {s_ for c in cols for s_, x in c.items() if not s_.startswith('_') and x[0] == 'd'},
                       'cols': cols, 'pairs': prs_, 'last': path0[-1], 'force': True})
        owned |= prs_
GR = {'우': '우등', '일': '일반', '프': '프리', '심': '심우', '심프': '심프', '심일': '심일'}
def wdl(ws):
    ws = sorted(ws)
    if len(ws) == 7: return '_'
    if ws == [0, 1, 2, 3, 4]: return '월∼금'
    if len(ws) >= 3 and len(ws) < 7:                     # 이어진 요일은 「금∼월」처럼 (주를 넘어 이어져도)
        for s0 in ws:
            if sorted((s0 + k) % 7 for k in range(len(ws))) == ws: return WD[s0] + '∼' + WD[(s0 + len(ws) - 1) % 7]
    return ''.join(WD[w] for w in ws)
# 노선표에 실을 것만 고른다: 타는 곳이 둘 이상이고 그 시각이 실제로 다른(δ>0) 노선 — 목록으로는 보여 줄 수 없는 것.
# 정류장이 많은 차례로, 표 칸(차 수)의 합이 CAP 안에서 (두 쪽 안팎)
CAP = int(os.environ.get('CAP', '40'))           # 한 쪽에 드는 만큼 (조판해 보고 정함)
def real_board(T):
    return sum(1 for s_ in T['board'] if any(c.get(s_, ('', 0))[0] == 'd' for c in T['cols'])) >= 2 and \
        any(len({c[s_][1] for s_ in T['board'] if s_ in c and c[s_][0] == 'd'}) >= 2 for c in T['cols'])
cand = sorted([T for T in tables if real_board(T)], key=lambda T: (-len(T['stops']), len(T['cols'])))
isF = lambda T: T.get('force')
pick, tot = [T for T in tables if isF(T)], 0             # 사람이 확인한 노선(force-links)은 늘 싣고, 아래 몫에는 세지 않는다
# 자동으로 고르는 표는 지금까지 실어 온 것(auto-pick.json: 정류장 묶음)으로 묶어 둔다 — 다른 표가 바뀔 때마다 몫이 흔들려 표가 들고 나지 않게
APF_ = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'auto-pick.json')
APIN = {frozenset(x) for x in json.load(open(APF_))} if os.path.exists(APF_) else None
pinok = lambda T: APIN is None or frozenset(T['stops']) in APIN
for T in cand:
    if T in pick: continue
    if not pinok(T): continue
    if len(T['cols']) <= int(os.environ.get('MAXC', '16')) and tot + len(T['cols']) <= CAP: pick.append(T); tot += len(T['cols'])
# 주요·긴 노선: 정류장이 넷 넘는 표를 차 수가 많은 차례로 CAP2 안에서 (한 쪽 폭에 안 들면 접어 아래로)
CAP2 = int(os.environ.get('CAP2', '80'))
tot2 = 0
W1 = int(os.environ.get('W1', '20'))                # 한 쪽 폭에 드는 편 수 (어림)
fits = lambda n: n <= W1 or n % W1 == 0 or n % W1 >= W1 // 2      # 접었을 때 끝 띠가 너무 짧지 않게
for T in sorted([T for T in tables if T not in pick and len(T['stops']) >= 4 and fits(len(T['cols']))],
                key=lambda T: (-len(T['cols']) * len(T['stops']))):       # 주요(차가 많고) 긴(정류장이 많은) 노선부터
    if pinok(T) and tot2 + len(T['cols']) <= CAP2: pick.append(T); tot2 += len(T['cols'])
for T in tables:                                        # 사람이 확인한 노선(force-links)은 늘 싣는다
    if T not in pick and isF(T): pick.append(T)
for T in tables:
    if not T.get('force'): T['cols'] = [c for c in T['cols'] if c.get('_tid') not in ABSORB]
print('candidates', len(cand), 'picked', len(pick), 'cols', tot, '+', tot2, file=sys.stderr)
# 상하 병기: 반대 방향 표(겹치는 정류장이 둘 넘고 차례가 거꾸로인 것)가 있으면 웬만하면 한 표로 (고르지 않았어도 반대 방향은 곁들인다).
# 정류장은 두 방향을 합친 것 (방향마다 서는 곳이 다르기도 하다)
ALL = tables
def rev_ok(T, U):
    cm = [s_ for s_ in T['stops'] if s_ in U['stops']]
    if len(cm) < 2 or len(cm) < 0.5 * min(len(T['stops']), len(U['stops'])): return 0
    _ap = lambda X: any(s_.startswith('인천공항') for s_ in X['stops'])
    if _ap(T) != _ap(U) or (_ap(T) and all(s_.startswith('인천공항') for s_ in cm)): return 0     # 인천공항 버스: 공항 밖 정류장이 겹치는 반대 방향끼리만
    if not ({T['stops'][0], T['stops'][-1]} & set(U['stops']) and {U['stops'][0], U['stops'][-1]} & set(T['stops'])): return 0   # 끝 정류장을 서로 나눠 가져야
    ui = [U['stops'].index(s_) for s_ in cm]
    return len(cm) if all(ui[k] > ui[k + 1] for k in range(len(ui) - 1)) else 0
def merge_stops(a, b):
    """두 차례 a, b(같은 방향)를 하나로: 겹치는 정류장의 차례는 지키고, 한쪽에만 있는 정류장은 제자리에"""
    out, i, j = [], 0, 0
    while i < len(a) or j < len(b):
        if i < len(a) and j < len(b) and a[i] == b[j]: out.append(a[i]); i += 1; j += 1
        elif i < len(a) and (j >= len(b) or a[i] not in b[j:]): out.append(a[i]); i += 1
        elif j < len(b) and (i >= len(a) or b[j] not in a[i:]): out.append(b[j]); j += 1
        else: out.append(a[i]); i += 1
    seen_ = set()
    return [x for x in out if not (x in seen_ or seen_.add(x))]
both = []
used_ = set()
for T in pick:
    if id(T) in used_: continue
    cands = [(rev_ok(T, U), len(U['cols']), U) for U in ALL if U is not T and id(U) not in used_]
    cands = [c for c in cands if c[0]]
    if cands:
        U = max(cands, key=lambda c: (c[0], c[1]))[2]
        st_ = merge_stops(T['stops'], list(reversed(U['stops'])))
        M = dict(T, stops=st_, title=T.get('title') or None)
        both.append((M, U)); used_ |= {id(T), id(U)}
    else:
        both.append((T, None)); used_.add(id(T))
SHORT = {'센트럴시티(서울)': '서울호남', '광주(유·스퀘어)': '광주', '대전청사(샘머리)': '대전청사', '세종터미널(연구)': '세종터미널', '청주(센트럴)': '청주',
         '배방정류소': '배방', '동천(호남)': '동천', '임자(진리)': '임자', '가톨릭관동대강릉': '가톨릭관동대', '아산탕정사무소': '아산탕정', '천안종합운동장': '천안운동장',
         '평택굿모닝병원': '평택굿모닝', '원주의료진흥원': '원주의료원'}           # 책에 쓰는 짧은 터미널 이름
NM = dict(SHORT, **{'인천공항T1': '인천공항1터미널', '인천공항T2': '인천공항2터미널'})        # 노선표 굵은 글꼴에는 로마자가 없어 한글로
nm = lambda x: NM.get(x, x)
out = ["{{시각표테마}}", "'''고속버스''' 노선표. 국토교통부 TAGO 고속버스정보(2026년 10월 17∼30일) 기준.", '', '== 고속버스 ==']
# 차례: 접어 싣는 큰 표(한 쪽 폭을 넘는 것)를 먼저 — 그 띠들이 한 쪽에 위아래로 모이게
title_merge = {}
apt = lambda T: any(s_.startswith('인천공항') for s_ in T['stops'])          # 공항 노선끼리 모은다
# 공항으로 가는 작은 표(끝 정류장들이 같은 것)는 한 표로: 갈래마다 타는 곳을 위에서부터, 다른 갈래 칸은 ║
grp_ = collections.defaultdict(list)
for p in both:
    T, U = p
    if False and U is None and apt(T) and len(T['cols']) <= 8 and T['stops'][-1].startswith('인천공항'):     # 인천공항 버스는 따로 떼어 노선마다 제 표로 (합치지 않는다)
        tail = tuple(s_ for s_ in T['stops'] if s_.startswith('인천공항'))
        grp_[tail].append(p)
for tail, ps in grp_.items():
    if len(ps) < 2: continue
    Ts = sorted([p[0] for p in ps], key=lambda T: T['stops'][0])
    stops = [s_ for T in Ts for s_ in T['stops'] if s_ not in tail] + list(tail)
    br = {s_: i for i, T in enumerate(Ts) for s_ in T['stops'] if s_ not in tail}
    M = {'title': '%s ― %s' % ('・'.join(nm(T['stops'][0]) for T in Ts), nm(tail[-1])), 'stops': stops, 'board': set().union(*(T['board'] for T in Ts)), 'pairs': set().union(*(T['pairs'] for T in Ts)), 'last': tail[-1],
         'cols': [dict(c, _br=i) for i, T in enumerate(Ts) for c in T['cols']], 'branch': br}
    for p in ps: both.remove(p)
    both.append((M, None))
    for T in Ts: title_merge[id(T)] = M
SEOUL = {'서울경부', '센트럴시티(서울)', '동서울', '서울남부'}
# 구간별 표: 끝 구간(줄기, 정류장 둘 넘게)을 함께 쓰고 그 줄기가 노선의 반 넘는 표들은 한 표로 — 갈래마다 제 정류장, 다른 갈래 칸은 화살표.
# 줄기를 끝(아래)에 두도록 표마다 방향을 맞추고(상하 병기면 하행·상행을 바꿔), 나중에 서울·줄기 쪽을 위로 돌린다
def trunk_of(seq):
    return [tuple(seq[-k:]) for k in range(len(seq) - 1, 1, -1)] + [tuple(seq[:k][::-1]) for k in range(len(seq) - 1, 1, -1)]
pool = [p for p in both if not p[0].get('branch') and not apt(p[0])]      # 인천공항 버스 표는 노선마다 따로 (줄기로 합치지 않는다)
while True:
    cnt_ = collections.defaultdict(list)
    for p in pool:
        seq = p[0]['stops']
        fz_ = bool(p[0].get('force') or (p[1] and p[1].get('force')))     # 사람이 확인한 노선 표는 자동으로 고른 표와 섞지 않는다
        for tr_ in set(trunk_of(seq)):
            if 2 * len(tr_) >= len(seq): cnt_[(tr_, fz_)].append(p)
    best_ = max(((tr_, ps) for tr_, ps in cnt_.items() if len(ps) >= 2), key=lambda kv: (len(kv[1]), len(kv[0][0])), default=None)
    if not best_: break
    (tr_, _), ps = best_
    tr_ = list(tr_)
    mem = []
    for p in ps:
        T, U = p
        if list(T['stops'][-len(tr_):]) == tr_: mem.append((T['stops'], T, U))                 # 줄기가 끝: 그대로
        else: mem.append((list(reversed(T['stops'])), U, T))                                  # 줄기가 앞: 거꾸로 (하행 자리에 상행 표)
    mem.sort(key=lambda m: (not any(s_ in SEOUL for s_ in m[0]), m[0][0]))
    stops = [s_ for sq, _, _ in mem for s_ in sq if s_ not in tr_]
    stops = list(dict.fromkeys(stops)) + tr_
    br = {}
    for i, (sq, _, _) in enumerate(mem):
        for s_ in sq:
            if s_ not in tr_: br.setdefault(s_, i)
    head_ = sum(1 for p in ps if list(p[0]['stops'][:len(tr_)]) == tr_[::-1])        # 원래 줄기가 위였던 표 수
    D = {'stops': stops, 'board': set().union(*(X['board'] for _, X, _ in mem if X)), 'pairs': set().union(*(X['pairs'] for _, X, _ in mem if X)),
         'cols': [dict(c, _br=i) for i, (_, X, _) in enumerate(mem) if X for c in X['cols']], 'branch': br}
    Uc = [dict(c, _br=i) for i, (_, _, Y) in enumerate(mem) if Y for c in Y['cols']]
    UM = {'stops': list(reversed(stops)), 'board': set().union(*(Y['board'] for _, _, Y in mem if Y)), 'pairs': set().union(*(Y['pairs'] for _, _, Y in mem if Y)),
          'cols': Uc, 'branch': br} if Uc else None
    if not D['cols'] and UM: D, UM = dict(UM, stops=stops[::-1]), None; D['stops'] = list(reversed(stops))
    # 보이는 방향: 서울이 갈래에 있으면 갈래를 위로(지금대로), 줄기에 있으면 줄기를 위로, 없으면 원래 표들이 많이 쓰던 쪽
    up_trunk = any(s_ in SEOUL for s_ in tr_) or (not any(s_ in SEOUL for s_ in stops) and 2 * head_ > len(ps))
    if up_trunk and UM: D, UM = UM, D
    for p in ps: both.remove(p); pool.remove(p)
    both.append((D, UM))
for k_, (T, U) in enumerate(both):                     # 서울이 있으면 서울 쪽을 위로 (서울에서 나가는 방향을 하행으로)
    if not U: continue
    st = T['stops']
    ks = [i for i, s_ in enumerate(st) if s_ in SEOUL]
    if ks and ks[0] > (len(st) - 1) / 2:
        rv_ = list(reversed(st))
        T2 = dict(U, stops=rv_); T2.pop('title', None)
        U2 = dict(T); U2['stops'] = st
        both[k_] = (T2, U2)
# TAGO 에 없는 끝 정류장(extra-stops.json): after 가 끝인 노선표에 stop 을 이어 붙인다 (착은 +min, 반대 방향 발은 −min)
EXTRA = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'extra-stops.json'))) if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'extra-stops.json')) else []
EXREF = []
for E_ in EXTRA:
    if E_.get('lists') and not E_.get('tables'): continue     # 목록에만 쓰는 것은 아래에서
    af_, sp_, mn_ = E_['after'], E_['stop'], E_['min']
    for T_, U_ in both:
        st_ = T_['stops']
        if af_ not in st_: continue
        i_ = st_.index(af_)
        if sp_ not in st_:                               # 끝에 이어 붙인다
            if i_ == len(st_) - 1: st_.append(sp_)
            elif i_ == 0: st_.insert(0, sp_)
            else: continue
            if U_ and U_['stops'] is not st_: U_['stops'] = [sp_] + U_['stops'] if U_['stops'][0] == af_ else U_['stops'] + [sp_]
        j_ = st_.index(sp_); i_ = st_.index(af_)
        if abs(j_ - i_) != 1: continue                   # 이미 있으면(반대 방향 자료로) after 바로 옆일 때만
        for X_, up_ in ((T_, False), (U_, True)):
            if not X_: continue
            sp_after = (j_ > i_) != up_                   # 이 방향으로 달릴 때 stop 이 after 뒤
            for c in X_['cols']:
                if af_ not in c or sp_ in c: continue
                k_, t_ = c[af_]
                ss_ = [s_ for s_ in (st_[::-1] if up_ else st_) if s_ in c]
                if k_ == 'a' and sp_after and ss_[-1] == af_: c[sp_] = ('a', (t_ + mn_) % 1440)
                elif k_ == 'd' and not sp_after and ss_[0] == af_:      # 그 차가 after 에서 떠난다 → stop 에서 mn 분 앞에
                    c[sp_] = ('d', (t_ - mn_) % 1440); X_['board'] = set(X_['board']) | {sp_}
            for A, D in list(X_['pairs']):
                if (A, sp_) in P or (sp_, D) in P: continue
                if D == af_ and sp_after: EXREF.append((A, sp_, id(X_), P[(A, D)]['dur'] + mn_))
                if A == af_ and not sp_after: EXREF.append((sp_, D, id(X_), P[(A, D)]['dur'] + mn_))
# 지나기만 하는 정류장(through-stops.json): 거기서 끝나거나 비롯하는 차는 없다 → 그 정류장까지만 아는 편은 노선 끝까지, 표에 없던 그 구간 편도 표에
_THF = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'through-stops.json')
for TS_ in (json.load(open(_THF)) if os.path.exists(_THF) else []):
    sq_, sp_ = TS_['seq'], TS_['stop']
    for T_, U_ in both:
        if not set(sq_) <= set(T_['stops']): continue
        for X_, fw_ in ((T_, True), (U_, False)):
            if not X_: continue
            q_ = [s_ for s_ in (X_['stops'] if fw_ else list(reversed(T_['stops']))) if s_ in sq_]       # 이 방향으로 지나는 차례
            k_ = q_.index(sp_); before, after = q_[:k_], q_[k_ + 1:]
            def offs_(a_):
                c_ = collections.Counter((c[a_][1] - c[sp_][1]) % 1440 for c in X_['cols'] if a_ in c and sp_ in c)
                return c_.most_common(1)[0][0] if c_ else None
            ob_ = {a_: offs_(a_) for a_ in before + after}
            for c in X_['cols']:
                if sp_ not in c: continue
                if not any(a_ in c for a_ in after):          # 여기서 끝나는 편 → 끝까지
                    for a_ in after:
                        if ob_[a_] is not None: c[a_] = ('a', (c[sp_][1] + ob_[a_]) % 1440)
                if not any(a_ in c for a_ in before):         # 여기서 비롯하는 편 → 처음부터
                    for a_ in before:
                        if ob_[a_] is not None: c[a_] = ('d', (c[sp_][1] + ob_[a_]) % 1440)
            # 표에 없던 그 정류장 구간 편 (여기서 비롯하거나 끝나는 것으로 보이던 편)
            have_ = {(A_, c[A_][1], D_) for c in X_['cols'] for A_ in c if not A_.startswith('_') and c[A_][0] == 'd' for D_ in c if not D_.startswith('_') and D_ != A_}
            for (A_, D_), v_ in list(P.items()):
                if sp_ not in (A_, D_) or A_ not in q_ or D_ not in q_ or q_.index(A_) > q_.index(D_): continue
                if not (A_ in before or D_ in before or A_ in after or D_ in after): continue
                for t_, w_ in v_['t'].items():
                    if (A_, t_, D_) in have_: continue
                    t0_ = t_ if A_ == sp_ else (t_ + P[(A_, D_)]['dur']) % 1440       # 그 정류장의 시각
                    c = {A_: ('d', t_), D_: ('a', (t_ + v_['dur']) % 1440), '_w': w_, '_sub': (A_, t_, D_) in SUBN}
                    if A_ == sp_:
                        for a_ in before:
                            if ob_[a_] is not None: c[a_] = ('d', (t0_ + ob_[a_]) % 1440)
                    else:
                        for a_ in after:
                            if ob_[a_] is not None: c[a_] = ('a', (t0_ + ob_[a_]) % 1440)
                    X_['cols'].append(c); have_.add((A_, t_, D_))
                X_['pairs'].add((A_, D_)); X_['board'] = set(X_['board']) | ({A_} | ({a_ for a_ in before} if A_ == sp_ else set()))
            X_['cols'].sort(key=lambda c: next(((c[s_][1] - 0) % 1440 + (0 if c[s_][1] >= 240 else 1440) for s_ in (X_['stops'] if fw_ else list(reversed(T_['stops']))) if s_ in c), 0))
BOFF_ = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'board-offsets.json')))
for T_, U_ in both:                                    # 노선표: TAGO 가 같은 시각을 붙인 타는 곳은 아는 분수만큼 뒤로
    for X_ in (T_, U_):
        if not X_: continue
        for c in X_['cols']:
            for k_, dv in BOFF_.items():
                a_, b_ = k_.split('|')
                if a_ in c and b_ in c and c[a_][0] == 'd' and c[b_][0] == 'd' and c[a_][1] == c[b_][1]:
                    c[b_] = ('d', (c[b_][1] + dv) % 1440)
                if a_ in c and b_ in c and c[a_][0] == 'a' and c[b_][0] == 'a' and c[a_][1] == c[b_][1]:      # 내리는 곳도: 같은 착이면 그만큼 앞 (광주 → 진주개양・진주 가 다 120분)
                    c[b_] = ('a', (c[b_][1] - dv) % 1440)
            # 고창 ― 인천공항 시외 편: TAGO 에 고창 발만 있어 정읍·김제 칸이 비는 것을 나무위키 시각(정읍 +40, 김제 +80)으로
            if '고창' in c and c['고창'][0] == 'd' and c.get('_sub') and any(s_.startswith('인천공항') for s_ in c) and '정읍' not in c and '김제' not in c and '정읍' in X_['stops']:
                c['정읍'] = ('d', (c['고창'][1] + 40) % 1440); c['김제'] = ('d', (c['고창'][1] + 80) % 1440)
# 인천공항 버스: 공항을 위에 두어(공항 발이 하행) 차례를 맞추고, 1터미널 줄은 늘 둔다.
# TAGO 시외는 2터미널과 끝 정류장 사이만 판다 → 1터미널은 그 표의 고속 편(또는 시각표)과 같은 간격으로 (공항 발은 모르면 +25분: 김해 고속・나무위키 시각표 모두 +25),
# 그 밖의 사이 정류장은 모름(빈칸, 「통과」 아님)
T1_, T2_ = '인천공항T1', '인천공항T2'
for i_, (T_, U_) in enumerate(both):
    if not any(s_.startswith('인천공항') for s_ in T_['stops']): continue
    if U_ and not T_['stops'][0].startswith('인천공항'):
        T_, U_ = dict(U_, stops=list(reversed(T_['stops'])), title=None), dict(T_, title=None)
    if T1_ not in T_['stops'] and T2_ in T_['stops']:
        k_ = T_['stops'].index(T2_); T_['stops'].insert(k_ + 1 if k_ == 0 else k_, T1_)
    both[i_] = (T_, U_)
    for X_, st_ in ((T_, T_['stops']), (U_, list(reversed(T_['stops'])))):
        if not X_: continue
        for out_ in (True, False):                    # 공항 발 / 공항 행
            kd_ = 'd' if out_ else 'a'
            offs_ = collections.Counter(((c[T1_][1] - c[T2_][1]) if out_ else (c[T2_][1] - c[T1_][1])) % 1440 for c in X_['cols'] if T1_ in c and T2_ in c and c[T2_][0] == kd_)
            o_ = offs_.most_common(1)[0][0] if offs_ else (25 if out_ else None)
            for c in X_['cols']:
                if T2_ not in c or c[T2_][0] != kd_: continue
                if T1_ not in c and o_ is not None:
                    c[T1_] = (kd_, (c[T2_][1] + (o_ if out_ else -o_)) % 1440)
                    if out_: X_['board'] = set(X_['board']) | {T1_}
                if c.get('_sub'):
                    on_ = [k for k, s_ in enumerate(st_) if s_ in c]
                    c['_unk'] = {s_ for k, s_ in enumerate(st_) if on_[0] < k < on_[-1] and s_ not in c} | ({T1_} if T1_ not in c else set())
def ends_of(T, U):
    """표의 하행 차례로: 차가 떠나는 곳(왼쪽)·끝나는 곳(오른쪽) — 중간에서 시발·종착하는 주요 정류장"""
    st = T['stops']; L_, R_ = set(), set()
    for X, rev in ((T, False), (U, True)):
        if not X: continue
        for c in X['cols']:
            idx = [s_ for s_ in st if s_ in c and s_ in st]
            if not idx: continue
            f_, l_ = idx[0], idx[-1]                       # 하행 차례로 처음·끝
            if rev: f_, l_ = l_, f_                         # 상행: 하행 차례의 끝에서 떠나 처음에서 끝난다 → 하행 뜻으로는 끝이 시발(오른쪽)
            (R_ if rev else L_).add(f_); (L_ if rev else R_).add(l_)
    mids = (L_ | R_) - {st[0], st[-1]}
    left = [st[0]] + [s_ for s_ in st[1:-1] if s_ in L_ and s_ not in R_]
    right = [s_ for s_ in st[1:-1] if s_ in R_] + [st[-1]]
    return mids, left, right
for T, U in both:
    if T.get('title') and T.get('branch') and not U and '인천공항' in T['title']: T['mids'] = ends_of(T, U)[0]; continue    # 공항 갈래 표는 이름 그대로
    mids, left, right = ends_of(T, U)
    T['mids'] = mids
    T['title'] = '%s ― %s' % ('・'.join(nm(x) for x in left), '・'.join(nm(x) for x in right))
    T['title_up'] = '%s ― %s' % ('・'.join(nm(x) for x in right[::-1]), '・'.join(nm(x) for x in left[::-1]))
# 이름이 같은 표(서울경부 ― 아산온양 둘: 천안운동장 길 · 아산탕정 길)는 저마다 가장 많은 차가 서는 제 정류장을 가운데에
_tg = collections.defaultdict(list)
for T, U in both: _tg[T.get('title')].append((T, U))
for tt_, ps_ in _tg.items():
    if not tt_ or len(ps_) < 2: continue
    for T, U in ps_:
        oth_ = set().union(*(set(T2['stops']) for T2, _ in ps_ if T2 is not T))
        uq_ = [s_ for s_ in T['stops'] if s_ not in oth_]
        if not uq_: continue
        cnt_ = lambda s_: sum(1 for X in (T, U) if X for c in X['cols'] if s_ in c)
        best_ = max(uq_, key=lambda s_: (cnt_(s_), T['stops'].index(s_)))
        a_, _, b_ = T['title'].partition(' ― ')
        T['title'] = '%s ― %s ― %s' % (a_, nm(best_), b_)
        if T.get('title_up'):
            a_, _, b_ = T['title_up'].partition(' ― ')
            T['title_up'] = '%s ― %s ― %s' % (a_, nm(best_), b_)
ncols = lambda p: len(p[0]['cols']) + (len(p[1]['cols']) if p[1] else 0)
both.sort(key=lambda p: (-(ncols(p) > W1), -apt(p[0]), p[0]['stops'][0], p[0]['stops'][-1]))
def foot(c):
    w = c['_w']
    gs = collections.Counter(x for x in w if x)
    g0 = gs.most_common(1)[0][0] if gs else '우'
    diff = [d for d in range(7) if w[d] and w[d] != g0]
    rem_ = ('%s%s' % (''.join(WD[d] for d in diff), GR.get(w[diff[0]], w[diff[0]]))) if diff else '_'
    if diff:                                              # 비고: 「금토일/□프」 (요일 줄바꿈 등급 네모, 심야는 검은 네모)
        g1 = w[diff[0]]
        rem_ = '%s/%s{%s}' % (''.join(WD[d] for d in diff), 'BS' if g1.startswith('심') else 'S', {'심': '우', '심프': '프', '심일': '일'}.get(g1, g1))
    if c.get('_sub'): rem_ = '†' if rem_ == '_' else '†/' + rem_          # 시외버스로 파는 편
    if c.get('_note'): rem_ = c['_note']                                  # 등급마다 들르는 곳 (alt-routes.json)
    return g0, wdl([d for d in range(7) if w[d]]), rem_
BR = {}
ALT = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'alt-stops.json')))
_NVF = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'not-via.json')
NV_ = json.load(open(_NVF)) if os.path.exists(_NVF) else []
def cells_of(c, st, up=False):
    """up: 상하 병기의 상행(아래에서 위로 읽는다) — 통과 ↿, 하행·보통 표는 ⇂(v). 지나지 않는 곳도 통과(レ)로, 갈래가 갈린 표(지선)의 다른 갈래만 ║"""
    idx = [k for k, s_ in enumerate(st) if s_ in c]
    def other(s_): return s_ in BR and '_br' in c and BR[s_] != c['_br']        # 다른 갈래의 정류장
    def alt(s_): return any(s_ in g and any(o in c for g2 in A_ if g2 is not g for o in g2) for A_ in ALT for g in A_)   # 다른 길로 가는 차(alt-stops.json)
    def cell(k, s_):
        if s_ in c: return hm(c[s_][1])
        if s_ in c.get('_unk', ()): return 'c'                         # 시각 모름 (인천공항 발 시외의 사이 정류장)
        mid = idx[0] < k < idx[-1]
        if not mid: return 'x'
        if other(s_): return 'i'                                      # 다른 갈래(지선): ║
        if any(s_ == nv_['stop'] and nv_['from_side'] in c and nv_['to'] in c and c[nv_['from_side']][0] == 'd' for nv_ in NV_): return 'x'    # 그 방향은 거치지 않는 곳 (not-via.json): ‥
        if c.get('_sub'): return 'c'                                  # 시외는 TAGO 가 끝과 끝만 팔아 사이 정류장은 모름 (통과 아님): 빈칸
        return '↿' if up else 'v'                                     # 통과·지나지 않음: レ
    return [cell(k, s_) for k, s_ in enumerate(st)]
def line(c, st, up=False):
    g0, dl_, rem_ = foot(c)
    KB = {'우': '우', '일': '일', '프': '프', '심': '우', '심프': '프', '심일': '일'}          # 목록처럼 한 글자 등급
    kind = '"◆"' if g0 == '◆' else '%s{%s}' % ('BS' if g0.startswith('심') else 'S', KB.get(g0, g0))   # 차마다 돌아가는 등급 ◆, 심야는 검은 네모 (목록과 같이)
    return '%s : %s : %s %s' % (kind, ' '.join(cells_of(c, st, up)), dl_, rem_)
ORD = ['첫째', '둘째', '셋째', '넷째', '다섯째', '여섯째', '일곱째', '여덟째', '아홉째', '열째', '열한째', '열두째']
def cut(xs, k):
    sz = [len(xs) // k + (1 if i < len(xs) % k else 0) for i in range(k)]
    out_, a_ = [], 0
    for z in sz: out_.append(xs[a_:a_ + z]); a_ += z
    return out_
CAPF = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bus-caps.json')       # ttbook 이 잰 표마다 한 쪽 폭에 드는 편 수 (busCaps)
CAPS = json.load(open(CAPF)) if os.path.exists(CAPF) else {}
import re as _re
nset = lambda tt: frozenset(x.strip() for x in _re.split('[―・]', tt.split('|')[0]))          # 이름의 정류장들 (차례·방향 무관)
def capS(*tts):
    for tt in tts:
        if tt in CAPS: return CAPS[tt]
        for k_, v in CAPS.items():
            if nset(k_) == nset(tt): return v
    return W1
def capB(tt, tu):
    if tt + '|both' in CAPS: return CAPS[tt + '|both']
    return capS(tt, tu)                                  # 잰 값으로는 상하 병기도 한 방향 표와 폭이 같다
def greedy(xs, k):
    """앞 띠부터 꽉 채워 (뒤 띠가 짧게) — 잘린 데서 「차가 더 없나」 싶지 않게"""
    return [xs[i:i + k] for i in range(0, len(xs), k)]
emit = []
TTL = {}                                                # 표 → 이름 (목록의 참조 줄)
for T, U in both:
    # 한 쪽 폭에 드는 상하 병기는 한 표로. 넘으면 보통 시각표로 하행(서울에서 나가는 쪽) 띠들, 이어서 상행 띠들 (같은 이름의 표 여럿을 위아래로)
    st = T['stops']
    tT = T.get('title') or '%s ― %s' % (nm(st[0]), nm(st[-1]))
    n = len(T['cols']) + (len(U['cols']) if U else 0)
    tU = T.get('title_up') or '%s ― %s' % (nm(st[-1]), nm(st[0]))
    if U and n <= capB(tT, tU):
        emit.append((T, U, tT, '', T['cols'], U['cols'])); TTL[id(T)] = TTL[id(U)] = tT; continue
    for X_, tt in ((T, tT),) + (((dict(U, stops=list(reversed(st)), mids=T.get('mids', set())), tU),) if U else ()):
        TTL[id(X_ if X_ is T else U)] = tt
        m = len(X_['cols']); k = capS(tt, tT)
        if m <= k: emit.append((X_, None, tt, '', X_['cols'], [])); continue
        for i, cs in enumerate(greedy(X_['cols'], k)): emit.append((X_, None, tt, '（%s）' % ORD[i], cs, []))
out_apt = ["{{시각표테마}}", "'''인천공항 버스''' 노선표. 국토교통부 TAGO 고속・시외버스정보(2026년 10월 17∼30일) 기준.", '', '== 인천공항버스 ==']
out_reg = out
for T, U, ttl, part, cols_, ucols in emit:
    out = out_apt if apt(T) else out_reg               # 인천공항 버스는 따로 (pages/인천공항버스.txt)
    st = T['stops']
    BR.clear(); BR.update(T.get('branch', {}))
    out += ['=== %s%s ===' % (ttl, part), '{{#invoke:Timetable|main|data=', 'title "%s%s"' % (ttl, part), 'headl "b%s"' % ttl]
    out += (['cols ad st ad', 'both 1'] if U else ['cols st ad', 'rcols st']) + ['',
            '[rows]', 'kind 등급 style=va=b r=等級', '', '[footer]', 'days 운행일 r=運行日 style=va=t', 'rem 비고 r=備考 style=va=t', '', '[stations]']
    pv, pu = None, None
    for i, s_ in enumerate(st):
        ad = '發' if s_ in T['board'] else '着'
        if pv and not any(s_ in c for c in T['cols']): ad = pv                 # 이 방향으로는 서지 않는 정류장: 앞 줄을 따라 〃
        mk = '*' if i in (0, len(st) - 1) or s_ in T.get('mids', ()) else ''     # 처음·끝, 중간에서 시발·종착하는 주요 정류장 (조준선)
        rl = ''
        bg_ = lambda x: (T.get('brline') or BR).get(x, -1)                   # 선 긋는 덩이 (갈리는 정류장은 줄기에 붙는 갈래 쪽)
        if BR and i > 0 and bg_(s_) != bg_(st[i - 1]): rl = ' style=bt=1'      # 갈래가 바뀌는 곳(갈래 구간 위아래)에 선
        if U:
            au = '發' if s_ in U['board'] else '着'
            if pu and not any(s_ in c for c in U['cols']): au = pu
            out.append('%s %s%s %s%s' % (ad if ad != pv else '〃', mk, nm(s_), au if au != pu else '〃', rl))
            pu = au
        else:
            out.append('%s%s %s%s' % (mk, nm(s_), ad if ad != pv else '〃', rl))
        pv = ad
    out += ['', '[trains]'] + [line(c, st) for c in cols_]
    if U:
        rs = list(reversed(st))                        # 상행은 아래(출발)에서 위로 읽는 차례로
        out += ['', '[trains up]'] + [line(c, rs, True) for c in ucols]
    out += ['', '[notes]', '}}', '']
tables = [T for p in both for T in p if T]
title_of = dict(TTL)                                    # 한 표 상하 병기면 상행도 하행 표 이름으로, 따로 실으면 제 이름으로
for k_, M_ in title_merge.items(): title_of[k_] = title_of[id(M_)]
out = out_reg
open(sys.argv[2], 'w').write('\n'.join(out))
open(re.sub(r'(\.txt)?$', '-apt.txt', sys.argv[2], count=1), 'w').write('\n'.join(out_apt))
# 일부 편만 들르는 정류장 (사람이 확인한 것, partial-stops.json: [A, B, D] = A 발 D 행의 몇 편이 B 에도 선다): 목록의 A→D 에 ◇ 표지와 안내 줄.
# B 의 편 가운데 노선표에 실린 다른 노선의 차는 빼고 맞춘다
pmark, pfold = {}, {}                                    # pfold: B 쪽 덩이의 편이 모두 ◇ 편이면 참조 줄로 (가장 긴 구간에 싣는다)
def intab(X, Y):
    """노선표에 실린 X 발(Y 에 서는) 시각 — 그 시각의 모든 요일이 표의 칸으로 덮일 때만 (원주문막 1245 처럼 월∼목은 기업도시 차, 금∼일은 원주 차인 것은 빼지 않는다)"""
    cov = collections.defaultdict(set)
    for T in tables:
        for c in T['cols']:
            if X in c and Y in c and c[X][0] == 'd': cov[c[X][1]] |= {d_ for d_ in range(7) if c['_w'][d_]}
    return {t for t, ds in cov.items() if (X, Y) not in P or t not in P[(X, Y)]['t'] or {d_ for d_ in range(7) if P[(X, Y)]['t'][t][d_]} <= ds}
for A, B_, D in PART:
    if (A, D) in P and (B_, D) in P:                     # 오는 길: A 발 + δ 에 B 발
        ta, tb = P[(A, D)]['t'], set(P[(B_, D)]['t']) - intab(B_, D)
        d = max(range(1, 121), key=lambda d: sum(1 for t in ta if (t + d) % 1440 in tb))
        pmark[(A, D)] = ({t for t in ta if (t + d) % 1440 in tb}, '◇ 승차 %s +%s' % (nm(B_), hmd(d)))
        pfold[(B_, D)] = ('seeFrom', A, {(t + d) % 1440 for t in pmark[(A, D)][0]})
    if (D, A) in P and (D, B_) in P:                     # 가는 길: D 발이 같은 시각이면 B 에 먼저 선다
        ta, tb = P[(D, A)]['t'], set(P[(D, B_)]['t']) - intab(D, B_)
        d = P[(D, A)]['dur'] - P[(D, B_)]['dur']
        pmark[(D, A)] = ({t for t in ta if t in tb}, '◇ 경유 %s %s' % (nm(B_), hmd(P[(D, B_)]['dur'])))
        pfold[(D, B_)] = ('see', A, pmark[(D, A)][0])
own = {p for T in tables for p in T['pairs'] if not apt(T) or any(s_.startswith('인천공항') for s_ in p)}      # 인천공항 버스 표의 공항 밖 구간(김해 → 인천)은 목록에도
_cov = {(A, c[A][1], D) for T in tables for c in T['cols'] for A in c if not A.startswith('_') and c[A][0] == 'd' for D in c if not D.startswith('_') and D != A}
_bo = {tuple(k.split('|')): v for k, v in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'board-offsets.json'))).items()}
_altS = [set(R_['seq']) for R_ in (json.load(open(ALTF)) if os.path.exists(ALTF) else [])]
LOST = sorted((A, hm(t), D) for A, D in own if not any({A, D} <= q_ for q_ in _altS) for t in P[(A, D)]['t'] if (A, t, D) not in _cov and not any(B == A and (A, (t + v) % 1440, D) in _cov for (_, B), v in _bo.items()))
if LOST: print('표가 가진 구간인데 표에 없는 편', len(LOST), LOST[:12], file=sys.stderr)
for O in b['origins']: O['dests'] = [X for X in O['dests'] if (O['from'], X['to']) not in own]
b['origins'] = [O for O in b['origins'] if O['dests']]
# 표가 갖지 않은 구간(SKIPOWN: 사람이 확인한 노선 표에 그 밖의 시외를 싣지 않은 것): 목록 덩이에서 표에 실린 편은 빼고 「이 밖에 노선표」
SKIPREF = []
for O in b['origins']:
    for X in O['dests']:
        k = (O['from'], X['to'])
        if k not in SKIPOWN or 'times' not in X: continue
        it_ = intab(*k)
        if not it_: continue
        tts_ = {next((title_of.get(id(T)) for T in tables if any(k[0] in c and k[1] in c and c[k[0]] == ('d', t_) for c in T['cols'])), None) for t_ in it_}
        X['times'] = [t for t in X['times'] if m_(t[0]) not in it_]
        SKIPREF += [[k[0], k[1], tt, X['dur'], X.get('fare')] for tt in tts_ if tt]
for O in b['origins']: O['dests'] = [X for X in O['dests'] if 'times' not in X or X['times']]
b['origins'] = [O for O in b['origins'] if O['dests']]
# 목록에도 TAGO 에 없는 끝 정류장 (extra-stops.json 의 lists: 그 출발지·행선지와 오가는 것만): after 행을 본떠 stop 행(착 +min), after 발을 본떠 stop 발(발 −min)
for E_ in EXTRA:
    if not E_.get('lists'): continue
    af_, sp_, mn_ = E_['after'], E_['stop'], E_['min']
    for O in b['origins']:
        X = next((X for X in O['dests'] if X['to'] == af_ and 'times' in X), None) if O['from'] in E_['lists'] else None
        if X and not any(Y['to'] == sp_ for Y in O['dests']):
            fr_ = P[(sp_, O['from'])]['fare'] if (sp_, O['from']) in P else None          # 요금은 반대 방향(TAGO 에 있으면)과 같게
            O['dests'].append({'to': sp_, 'dur': X['dur'] + mn_, 'fare': fr_, 'times': [[t[0], hm(m_(t[1]) + mn_)] + t[2:] for t in X['times']]} | ({'gnote': X['gnote']} if X.get('gnote') else {}))
    OA_ = next((O for O in b['origins'] if O['from'] == af_), None)
    if OA_:
        new_ = [{'to': X['to'], 'dur': X['dur'] + mn_, 'fare': None, 'times': [[hm(m_(t[0]) - mn_)] + t[1:] for t in X['times']]} | ({'gnote': X['gnote']} if X.get('gnote') else {})
                for X in OA_['dests'] if X['to'] in E_['lists'] and 'times' in X]
        OS_ = next((O for O in b['origins'] if O['from'] == sp_), None)
        if OS_: OS_['dests'] += [X for X in new_ if not any(Y['to'] == X['to'] for Y in OS_['dests'])]
        elif new_: b['origins'].append({'from': sp_, 'dests': new_})
for O in b['origins']:
    for X in O['dests']:
        k = (O['from'], X['to'])
        if k in pmark:
            ts, note = pmark[k]
            X['vnote'] = note
            for t in X['times']:
                if m_(t[0]) in ts: t.append('◇')
def tab_of(X_, Y_, t_):                                 # 그 편(X_ 발 t_, Y_ 에 섬)이 실린 노선표 이름
    for T in tables:
        if any(X_ in c and Y_ in c and c[X_] == ('d', t_) for c in T['cols']): return title_of.get(id(T))
for O in b['origins']:
    for X in O['dests']:
        k = (O['from'], X['to'])
        if k in pfold and 'times' in X:
            ts0 = {m_(t[0]) for t in X['times']}
            tt_ = {t_: tab_of(k[0], k[1], t_) for t_ in ts0 - pfold[k][2]}     # ◇ 편이 아닌 것은 노선표(갈래 노선 따위)에 실렸으면 그리로
            if all(tt_.values()) and len(set(tt_.values())) <= 1:
                kind, A_, _ = pfold[k]; du_, fa_ = X['dur'], X.get('fare'); to_ = X['to']
                X.clear(); X.update({'to': to_, kind: A_ if kind == 'seeFrom' else A_, 'dur': du_, 'fare': fa_})
                if tt_: X['alsoTable'] = next(iter(tt_.values()))              # 참조 줄 둘: 「→ 원주 행」「→ 노선표」
# 같은 차 (사람이 확인, same-bus.json): drop [B, D] = B 에 내리는 차는 다 D 까지 간다 → D 덩이에 「경유 B」, B 자리에는 참조 줄.
# board [A, B] = B 에서 타는 차는 다 A 에서 온다 (TAGO 는 B 에도 A 의 발차 시각을 붙인다) → A 덩이에 「승차 B」, B 발 목록에는 참조 줄
SAME = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'same-bus.json')))
BOFF = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'board-offsets.json')))     # TAGO 가 첫 터미널 시각을 그대로 붙인 타는 곳: 몇 분 뒤인지 (반대 방향 소요 차로 안 것)
ts_ = lambda X: {t[0] for t in X.get('times', [])}
for B_, D, *only in SAME['drop']:                      # 셋째 칸이 있으면 그 출발지들에만
    for O in b['origins']:
        if only and O['from'] not in only[0]: continue
        d = {X['to']: X for X in O['dests']}
        if B_ in d and D in d and 'times' in d[B_] and 'times' in d[D]:
            kb_ = {t[0] for t in d[B_]['times'] if '시' not in t[3:]}      # 같은 차라고 확인한 것은 고속 편: B 에서 끝나는 시외(진주 → 서대구 합천 경유)는 B 에 남긴다
            if not (kb_ and kb_ <= ts_(d[D])): continue
            XB = d[B_]; d[D].setdefault('via', []).append([B_, XB['dur'], XB.get('fare')])
            rest_ = [t for t in XB['times'] if t[0] not in ts_(d[D]) or '시' in t[3:]]
            if rest_:
                n_ = len(XB['times']) - len(rest_); XB['_v2'] = {D: [t[0] for t in XB['times'] if t not in rest_]}; XB['times'] = rest_; XB['vnote2'] = '이 밖에 %s 행 %d편도 섬' % (nm(D), n_)
                XB['dur'] = sorted((m_(t[1]) - m_(t[0])) % 1440 for t in rest_)[len(rest_) // 2]      # 남은 편(시외)의 소요・요금으로
                mf_ = [M_['fare'] for M_ in json.load(open(os.path.join(HERE2_, 'manual-trips.json'))) if M_['from'] == O['from'] and M_['to'] == B_ and M_.get('fare')]
                if mf_: XB['fare'] = [min(f_[0] for f_ in mf_), max(f_[1] for f_ in mf_)]
            else: XB.clear(); XB.update({'to': B_, 'see': D})
for A, B_, *only in SAME['board']:                      # 셋째 칸이 있으면 그 행선지들에만
    oa = next((O for O in b['origins'] if O['from'] == A), None); ob = next((O for O in b['origins'] if O['from'] == B_), None)
    if not oa or not ob: continue
    da = {X['to']: X for X in oa['dests']}
    for X in ob['dests']:
        Y = da.get(X['to'])
        if only and X['to'] not in only[0]: continue
        if not (Y and 'times' in X and 'times' in Y): continue
        tA, tB = {m_(t) for t in ts_(Y)}, {m_(t) for t in ts_(X)}
        d = next((d for d in range(0, 61) if {(t - d) % 1440 for t in tB} <= tA), None)     # B 발 = A 발 + δ (TAGO 가 같은 시각을 붙이면 δ=0)
        if d is not None:
            if not d: d = BOFF.get('%s|%s' % (A, B_), 0)       # TAGO 가 같은 시각을 붙인 곳: 아는 분수(반대 방향 소요 차)로
            Y.setdefault('board', []).append(B_ + (' +%s' % hmd(d) if d else ''))      # 「승차 호남제일 +10분」: 이 덩이의 발 시각 + δ 에 B 발
            to_ = X['to']; X.clear(); X.update({'to': to_, 'seeFrom': A})
# 겹치는 행선지 묶음: 차마다 가장 먼 행선지 덩이에 싣고, 그 앞에 서는 곳은 「경유」(모든 편) 또는 ◇(몇 편만, 하나까지).
# 앞 행선지 덩이에는 남은 편과 「이 밖에 … 행 n편도 섬」, 남은 편이 없으면 참조 줄
import chains
def merge_drop(d, xs):
    """d: 행선지 → 덩이, xs: 가까운 것부터. 되면 True"""
    blocks = {x: (frozenset(t[0] for t in d[x]['times']), d[x]['dur']) for x in xs}
    far = {}                                              # 발차 → 가장 먼 행선지
    for x in xs:
        for t in blocks[x][0]: far[t] = x
    plan = {}
    for j, x in enumerate(xs):
        mine = sorted(t for t in blocks[x][0] if far[t] == x)
        vias, part = [], []
        for y in xs[:j]:
            k = sum(1 for t in mine if t in blocks[y][0])
            if k == len(mine) and mine: vias.append(y)
            elif k: part.append(y)
        same_ = lambda: len(part) == 1 and d[x].get('vnote', '').startswith('◇ 승차 %s' % nm(part[0])) and \
            {t[0] for t in d[x]['times'] if '◇' in t[3:]} == {t for t in mine if t in blocks[part[0]][0]}      # 같은 ◇ 편이 그 정류장에서 타기도(오는 길 승차를 먼저 합친 것)
        sec_ = False                                      # 둘째 묶음 △: 이미 「◇ 경유 진주혁신」인 덩이에 「△ 경유 진주개양」 (두 묶음까지)
        if len({frozenset(t for t in mine if t in blocks[y][0]) for y in part}) > 1: return False   # ◇ 는 한 묶음(같은 편들)까지
        if part and 'vnote' in d[x] and not same_():
            if len(part) == 1 and d[x]['vnote'].startswith('◇ 경유') and '\n' not in d[x]['vnote'] and nm(part[0]) not in d[x]['vnote']: sec_ = True
            else: return False
        plan[x] = (mine, vias, part, sec_)
    for x in xs:
        mine, vias, part, sec_ = plan[x]
        X = d[x]
        if not mine:                                      # 남은 편이 없으면 참조 줄: 편이 여러 덩이로 갔으면 가장 가까운 덩이로 (그 덩이의 「이 밖에」 줄이 나머지를 알린다)
            tgt = min({far[t] for t in blocks[x][0]}, key=xs.index)
            du_, fa_ = X['dur'], X.get('fare'); X.clear(); X.update({'to': x, 'see': tgt, 'dur': du_, 'fare': fa_}); continue
        X['times'] = [t for t in X['times'] if t[0] in set(mine)]
        if vias:
            vv = {v[0]: v for v in X.get('via', [])}
            for y in vias: vv.setdefault(y, [y, blocks[y][1], d[y].get('fare')])
            X['via'] = sorted(vv.values(), key=lambda v: (xs.index(v[0]) if v[0] in xs else -1, v[1]))      # 차례대로
        if part and sec_:
            y = part[0]
            for t in X['times']:
                if t[0] in blocks[y][0] and '△' not in t[3:]: t.append('△')
            X['vnote'] += '\n△ 경유 %s %s' % (nm(y), hmd(blocks[y][1])); X['_mk2'] = ('d', y, 0)
        elif part:
            y = part[0]
            bv_ = X.get('vnote', '')
            for t in X['times']:
                if t[0] in blocks[y][0] and '◇' not in t[3:]: t.append('◇')
            X['_part'] = [[z, blocks[z][1], d[z].get('fare')] for z in part]; X['_mk1'] = ('d', y, 0)
            X['vnote'] = '◇ 경유 ' + '・'.join('%s %s' % (nm(z), hmd(blocks[z][1])) for z in part)
            if bv_.startswith('◇ 승차 %s' % nm(y)): X['vnote'] += '・승차' + bv_[len('◇ 승차 %s' % nm(y)):]      # 「◇ 경유 황간 30분・승차 +30분」
        also = collections.Counter(far[t] for t in blocks[x][0] if far[t] != x)
        if also: X['_v2'] = {z: sorted(t for t in blocks[x][0] if far[t] == z) for z in also}
        if also: X['vnote2'] = '이 밖에 ' + ', '.join('%s 행 %d편' % (nm(z), n) for z, n in sorted(also.items(), key=lambda kv: blocks[kv[0]][1])) + '도 섬'
    return True
def merge_board(D, os_, strict=False):
    """D 로 가는 덩이들, os_: 먼저 타는 곳부터. 뒤 출발지 B 마다 앞 출발지 A 의 편이 B 에서도 타면(B 발 = A 발 + δ):
    A 의 편이 모두 그러면 A 덩이에 「승차 B +δ」, 몇 편만이면 그 편에 ◇ 와 「◇ 승차 B +δ」.
    B 덩이에서는 그 편을 빼고 「이 밖에 A 발 n편도 탐」(남은 편이 없으면 참조 줄)"""
    blk = {o: next((X for X in OR[o]['dests'] if X['to'] == D and 'times' in X), None) for o in os_ if o in OR}
    n = 0
    for i, o in enumerate(os_):
        X = blk.get(o)
        if not X or 'times' not in X: continue
        best = None
        for A in os_[:i]:
            Y = blk.get(A)
            if not Y or 'times' not in Y: continue
            tA = [m_(t[0]) for t in Y['times']]; tB = {m_(t[0]) for t in X['times']}
            # 그 차가 B 에 닿기 전에 B 에서 떠날 수는 없다: A 발 같은 시각의 A→B 편(같은 차가 B 에 내려 준다)이 있으면 그 착 −10분 뒤에만
            arrB = {t: (t + P[(A, o)]['dur']) for t in tA if (A, o) in P and t in P[(A, o)]['t']}
            dd = Y['dur'] - X['dur']
            for e in range(0, 421):
                far_ = abs(e - dd) > max(15, 0.2 * abs(dd))
                if far_ and (strict or e > 180): continue
                k = sum(1 for t in tA if (t + e) % 1440 in tB and (t not in arrB or t + e >= arrB[t] - 10))
                if far_ and (k < len(tA) or k < 2): continue    # 사람이 준 노선: TAGO 소요(노선마다 하나라 같게 적히기도)와 달라도 편이 모두 같은 δ 로 맞으면 (청양 → 정산 +20분)
                key_ = (k == len(tA), k, -abs(e - dd))
                if k and (best is None or key_ > best[0]): best = (key_, k, e, A, tA)
        if not best: continue
        _, k, e, A, tA = best; Y = blk[A]
        arrB = {t: (t + P[(A, o)]['dur']) for t in tA if (A, o) in P and t in P[(A, o)]['t']}
        if strict and k < min(len(tA), len(X['times'])): continue      # 사람이 보지 않은 묶음: 한쪽 편이 모두 맞을 때만
        if k < len(tA) and k < 3 and len(X['times']) > 5: continue      # 몇 편만(◇), 그것도 한두 편이 촘촘한 B 발과 맞으면 우연 (주문진 1405 → 강릉 1440 고속)
        got = {(t + e) % 1440 for t in tA if (t + e) % 1440 in {m_(t[0]) for t in X['times']} and (t not in arrB or t + e >= arrB[t] - 10)}
        if not e: e_ = BOFF.get('%s|%s' % (A, o), 0)
        else: e_ = e
        es = ('+' + hmd(e_)) if e_ else ''
        if k == len(tA): Y.setdefault('board', []).append(o + (' ' + es if es else ''))
        elif 'vnote' not in Y:
            for t in Y['times']:
                if (m_(t[0]) + e) % 1440 in got: t.append('◇')
            Y['vnote'] = '◇ 승차 %s%s' % (nm(o), ' ' + es if es else ''); Y['_mk1'] = ('b', o, e)
        elif ' %s ' % nm(o) in Y['vnote'] + ' ' and {m_(t[0]) for t in Y['times'] if '◇' in t[3:]} == {t for t in tA if (t + e) % 1440 in got}:
            Y['vnote'] += '・승차 %s' % es if es else '・승차'      # 같은 ◇ 편이 그 정류장에 내리고 타기도: 「◇ 경유 황간 30분・승차 +30분」
        elif Y['vnote'].startswith('◇ 승차') and '\n' not in Y['vnote'] and ' %s ' % nm(o) not in Y['vnote'] + ' ':      # 둘째 묶음 △ (진주 발: ◇ 승차 진주혁신, △ 승차 진주개양)
            for t in Y['times']:
                if (m_(t[0]) + e) % 1440 in got: t.append('△')
            Y['vnote'] += '\n△ 승차 %s%s' % (nm(o), ' ' + es if es else ''); Y['_mk2'] = ('b', o, e)
        else: continue
        rest_ = [t for t in X['times'] if m_(t[0]) not in got]
        if rest_: X['times'] = rest_; X['vnote3'] = '이 밖에 %s 발 %d편도 탐' % (nm(A), len(got)); X['_v3'] = [A, [((t + e) % 1440, t) for t in tA if (t + e) % 1440 in got]]
        else: du_, fa_ = X['dur'], X.get('fare'); X.clear(); X.update({'to': D, 'seeFrom': A, 'dur': du_, 'fare': fa_})
        n += 1
    return n
OR = {O['from']: O for O in b['origins']}
def extra_between():                                     # 시각 모르는 경유지(extra-stops.json 의 between)를 경유·승차 줄에 이름만
    for E_ in EXTRA:
        bts_ = E_.get('between') or []
        for bt_ in (bts_ if isinstance(bts_, list) else [bts_]):
            for O in b['origins']:
                for X in O['dests']:
                    if O['from'] in E_.get('lists', []) and O['from'] == bt_.get('with', O['from']) and X['to'] == E_['stop'] and 'via' in X:
                        k_ = next((i for i, v in enumerate(X['via']) if v[0] == bt_['after']), None)
                        if k_ is not None: X['via'][k_ + 1:k_ + 1] = [[n_, None, None] for n_ in bt_['names']]
                    if O['from'] == E_['stop'] and X['to'] in E_.get('lists', []) and X['to'] == bt_.get('with', X['to']) and 'board' in X:
                        k_ = next((i for i, v in enumerate(X['board']) if v.split(' ')[0] == bt_['after']), None)
                        if k_ is None: k_ = len(X['board'])          # after 가 ◇ 승차(몇 편만)로 빠졌으면 끝에
                        X['board'][k_:k_] = bt_['names'][::-1]
# 사람이 확인한 노선(list-chains.json, 정류장 차례): 목록에서 가장 긴 구간으로 (두 방향)
LCH = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'list-chains.json')))
nl = 0
LCH1 = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'list-chains-oneway.json'))) if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'list-chains-oneway.json')) else []
for seq0 in LCH + LCH1:
    for seq in ((seq0,) if seq0 in LCH1 else (seq0, seq0[::-1])):      # 한 방향만(list-chains-oneway.json): 오는 길은 TAGO 에 타는 곳이 없어 시각으로 이을 수 없는 것
        rev_ = seq is not seq0
        if rev_:                                         # 오는 길은 승차를 먼저: 당진 → 기지시(+25분) → 서울호남 이 「당진→기지시」 동네 편 한둘과 우연히 맞아 ◇ 경유가 되지 않게
            for k, D in enumerate(seq): nl += merge_board(D, seq[:k])
        for i, o in enumerate(seq):
            if o not in OR: continue
            d = {X['to']: X for X in OR[o]['dests'] if 'times' in X}
            xs = [x for x in seq[i + 1:] if x in d]
            if len(xs) >= 2 and merge_drop(d, xs): nl += 1
        if not rev_:
            for k, D in enumerate(seq): nl += merge_board(D, seq[:k])
for O in b['origins']:                                  # ◇ 경유가 남은 편 모두에 붙었으면(다른 묶음이 편을 가져간 뒤) 「경유」로
    for X in O['dests']:
        if X.get('_part') and all('◇' in t for t in X['times']):
            for t in X['times']: t.remove('◇')
            vv = {v[0]: v for v in X.get('via', [])}
            for v in X.pop('_part'): vv.setdefault(v[0], v)
            X['via'] = sorted(vv.values(), key=lambda v: v[1]); X.pop('vnote', None)
# 모든 편이 B 에서 타는데(「승차 강릉 +30분」) 몇 편만 B 에 내린다(◇ 경유 강릉 23분, TAGO 동네 시외 요금으로만 팔린 편): 모든 편이 B 에 서니 「경유 B」 로
for O in b['origins']:
    for X in O['dests']:
        pt_ = X.get('_part') or []
        bd_ = {s_.split(' ')[0]: s_ for s_ in X.get('board', [])}
        if 'times' in X and len(pt_) == 1 and pt_[0][0] in bd_ and '\n' not in X.get('vnote', ''):
            for t in X['times']:
                if '◇' in t: t.remove('◇')
            mo_ = re.match(r'\S+ \+(?:(\d+)시간)? ?(?:(\d+)분)?', bd_[pt_[0][0]])
            dv_ = (int(mo_.group(1) or 0) * 60 + int(mo_.group(2) or 0)) if mo_ else 0
            X['via'] = X.get('via', []) + [[pt_[0][0], dv_ or pt_[0][1], pt_[0][2]]]; X.pop('_part'); X.pop('vnote', None)      # 내리는 때도 타는 때로 (시각표)
# ◇・△ 가 다 붙은 편: 같은 시각이라도 날마다 한 곳만 들른다 (진주개양 또는 진주혁신, 요일에 따라) → 요일로 두 줄로 나눈다
for O in b['origins']:
    for X in O['dests']:
        mk1_, mk2_ = X.pop('_mk1', None), X.pop('_mk2', None)
        if not (mk1_ and mk2_ and 'times' in X): continue
        def days_(mk, t0):
            k_, s_, e_ = mk
            p_ = (O['from'], s_) if k_ == 'd' else (s_, X['to'])
            w_ = P.get(p_, {}).get('t', {}).get((t0 + e_) % 1440) if p_ in P else None
            return {d_: w_[d_] for d_ in range(7) if w_ and w_[d_]}
        out_ = []
        for t in X['times']:
            if not ('◇' in t[3:] and '△' in t[3:]): out_.append(t); continue
            t0 = m_(t[0]); D1, D2 = days_(mk1_, t0), days_(mk2_, t0)
            S2 = {d_ for d_ in D2 if d_ not in D1 or (D2[d_] == t[2][d_] != D1[d_])}      # 두 곳 다 그날 있다고 하면 등급이 맞는 쪽 (1830 월: 개양 프, 혁신 우, 진주 우)
            w2 = [g_ if d_ in S2 else 0 for d_, g_ in enumerate(t[2])]
            w1 = [0 if d_ in S2 else g_ for d_, g_ in enumerate(t[2])]
            fl_ = [f_ for f_ in t[3:] if f_ not in '◇△']
            if any(w1): out_.append(t[:2] + [w1] + fl_ + ['◇'])
            if any(w2): out_.append(t[:2] + [w2] + fl_ + ['△'])
        X['times'] = out_
print('list chains merged', nl, file=sys.stderr)
# 사람이 확인하지 않은 묶음(chains.py): 같은 차로 볼 만하고(sure) 차례가 시각으로(또는 stop-order.json 으로) 정해지는 것만
AUTO, REVIEW = [], []
for O in b['origins']:
    d = {X['to']: X for X in O['dests'] if 'times' in X and 'via' not in X and 'vnote' not in X}
    blocks = {x: (frozenset(t[0] for t in X['times']), X['dur']) for x, X in d.items()}
    for r, ms in chains.trees(blocks):
        xs = sorted(ms + [r], key=lambda x: blocks[x][1])
        if not chains.sure(blocks, xs) and not (chains.ordered(blocks, xs) and min(len(blocks[x][0]) for x in xs) >= 2): continue   # 편이 둘 넘고 소요로 차례가 정해지면 사람이 볼 것으로 싣는다
        sq_ = next((q for q in SEQ if O['from'] in q and all(x in q for x in xs)), None)     # 사람이 확인한 차례(stop-order.json)가 있으면 그대로
        if sq_:
            i0_ = sq_.index(O['from'])
            xs = sorted(xs, key=lambda x: abs(sq_.index(x) - i0_))
        elif not chains.ordered(blocks, xs): REVIEW.append((O['from'], xs)); continue
        if merge_drop(d, xs): AUTO.append((O['from'], xs))
        else: REVIEW.append((O['from'], xs))
NB_ = sum(merge_board(o, xs[::-1], strict=True) for o, xs in AUTO)      # 반대 방향(오는 길)도: 먼 데서 타는 차가 가까운 데서도 타면 「승차」
print('auto chains up', NB_, file=sys.stderr)
extra_between()
# 시각표로 아는 승차(known-boarding.json): TAGO 에 타는 곳이 없는 편 — 그 편에 ◇ 와 「◇ 승차 신철원 +20분・포천 +1시간」
KB_ = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'known-boarding.json')
for K_ in (json.load(open(KB_)) if os.path.exists(KB_) else []):
    for O in b['origins']:
        if O['from'] != K_['from']: continue
        for X in O['dests']:
            if X['to'] != K_['to'] or 'times' not in X: continue
            hit_ = [t for t in X['times'] if t[0] in K_['times'] and (not K_.get('sub') or '시' in t[3:])]      # sub: 시외 편만 (같은 시각 고속 편은 빼고)
            if len(hit_) == len(X['times']): X.setdefault('board', []).extend(K_['board'])
            elif hit_:
                for t in hit_: t.append('◇')
                X['vnote'] = '◇ 승차 ' + '・'.join(K_['board'])
            for bs_ in K_['board']:                     # 그 타는 곳 발 목록에 따로 있는 같은 차(TAGO 합천 → 서대구)는 접는다
                mo_ = re.match(r'(\S+) \+(?:(\d+)시간)? ?(?:(\d+)분)?', bs_)
                if not mo_: continue
                dv_ = int(mo_.group(2) or 0) * 60 + int(mo_.group(3) or 0)
                OB_ = next((O2 for O2 in b['origins'] if O2['from'] == mo_.group(1)), None)
                XB_ = next((X2 for X2 in (OB_['dests'] if OB_ else []) if X2['to'] == K_['to'] and 'times' in X2), None)
                if not XB_: continue
                tt_ = {(m_(t[0]) + dv_) % 1440 for t in hit_}
                rest_ = [t for t in XB_['times'] if m_(t[0]) not in tt_]
                if len(rest_) == len(XB_['times']): continue
                if rest_: XB_['vnote3'] = '이 밖에 %s 발 %d편도 탐' % (nm(K_['from']), len(XB_['times']) - len(rest_)); XB_['times'] = rest_; XB_['_v3'] = [K_['from'], [((m_(t[0]) + dv_) % 1440, m_(t[0])) for t in hit_]]
                else: du_, fa_ = XB_['dur'], XB_.get('fare'); XB_.clear(); XB_.update({'to': K_['to'], 'seeFrom': K_['from'], 'dur': du_, 'fare': fa_})
print('auto chains', len(AUTO), 'review', len(REVIEW), file=sys.stderr)
b['autoChains'] = [[o] + xs for o, xs in AUTO]
b['reviewChains'] = [[o] + xs for o, xs in REVIEW]
b['routeOwned'] = sorted('%s→%s' % p for p in own)
b['names'] = SHORT
b['tableRefs'] = sorted([A, D, title_of[id(T)], P[(A, D)]['dur'], P[(A, D)]['fare']] for T in tables for A, D in T['pairs'])   # 목록에서 노선표로 보내는 줄
b['tableRefs'] += sorted(map(list, {tuple(x[:3]) + (x[3], tuple(x[4]) if x[4] else None) for x in SKIPREF}))
b['tableRefs'] += sorted([A, D, title_of[i_], du_, None] for A, D, i_, du_ in set(EXREF) if i_ in title_of)                  # TAGO 에 없는 끝 정류장 (요금 모름)
APT_T = {title_of[id(T)] for T in tables if apt(T) and id(T) in title_of}          # 인천공항 버스는 따로 떼어: 목록에서 그 표로 보내지 않고, 공항 오가는 덩이도 싣지 않는다
b['tableRefs'] = [r_ for r_ in b['tableRefs'] if r_[2] not in APT_T and not r_[0].startswith('인천공항') and not r_[1].startswith('인천공항')]
_apl = sum(len(X.get('times', [])) for O in b['origins'] for X in O['dests'] if O['from'].startswith('인천공항') or X['to'].startswith('인천공항'))
if _apl: print('인천공항 버스인데 표에 없어 목록에서도 빠진 편', _apl, file=sys.stderr)
for O in b['origins']: O['dests'] = [X for X in O['dests'] if not (O['from'].startswith('인천공항') or X['to'].startswith('인천공항') or str(X.get('see', '')).startswith('인천공항'))]
b['origins'] = [O for O in b['origins'] if O['dests']]
# ── 이어진 노선을 목록에서 이어서 보이기 ──
# 1) 「이 밖에 D 행 n편도 섬」: 그 편들(더 먼 D 까지 가는 차)을 이 덩이에도 싣고 그 줄에 「→D 착」 (D 덩이에도 그대로)
# 2) 「이 밖에 A 발 n편도 탐」: 앞 출발지 A 에서 오는 차를 이 덩이에 싣고 그 줄에 「A 발 시각」
# 3) 시각을 아는 사이 정류장(경유 착・승차 발, ◇・△ 편만 서는 곳): 덩이에 칸(둘까지)을 두고 그 편의 시각을 적는다 — ◇・△ 표지와 안내 줄 대신
_hm4 = lambda x: hm(x % 1440)
_OD = {(O['from'], X['to']): X for O in b['origins'] for X in O['dests']}
def _dur_of(s):
    mo = re.search(r'(?:(\d+)시간)?\s*(?:(\d+)분)?\s*$', s.strip())
    return (int(mo.group(1) or 0) * 60 + int(mo.group(2) or 0)) if mo and (mo.group(1) or mo.group(2)) else None
for O in b['origins']:
    for X in O['dests']:
        if not X.get('times'): continue
        X['lab'] = [''] * len(X['times'])
for O in b['origins']:
    for X in O['dests']:
        if not X.get('times'): continue
        add_ = []
        for D_, ts0 in (X.pop('_v2', None) or {}).items():
            YD = _OD.get((O['from'], D_))
            if not YD or not YD.get('times'): continue
            for t in YD['times']:
                if t[0] in ts0:
                    add_.append(([t[0], _hm4(m_(t[0]) + X['dur']), t[2]] + [f_ for f_ in t[3:] if f_ not in ('◇', '△')], '→%s %s' % (nm(D_), t[1])))
            X.pop('vnote2', None)
        v3_ = X.pop('_v3', None)
        if v3_:
            A_, prs_ = v3_; YA = _OD.get((A_, X['to']))
            if YA and YA.get('times'):
                for tb_, ta_ in prs_:
                    cs_ = [t for t in YA['times'] if m_(t[0]) == ta_]
                    cs_ = [t for t in cs_ if '◇' in t[3:] or '△' in t[3:]] or cs_      # 같은 시각의 다른 차(고속 1640・시외 1640)는 그 승차 표지가 붙은 것 하나만
                    for t in cs_[:1]:
                        add_.append(([_hm4(tb_), t[1], t[2]] + [f_ for f_ in t[3:] if f_ not in ('◇', '△')], '%s %s발' % (nm(A_), t[0])))
                X.pop('vnote3', None)
        if add_:
            rows_ = list(zip(X['times'], X['lab'])) + add_
            rows_.sort(key=lambda p: m_(p[0][0]))
            X['times'] = [p[0] for p in rows_]; X['lab'] = [p[1] for p in rows_]
for O in b['origins']:
    for X in O['dests']:
        if not X.get('times'): continue
        cand = []                                       # (이름, 종류 a/d, 분, 표지 또는 None=모든 편)
        txt_v, txt_b = [], []
        tv_ = [v for v in X.get('via', []) if v[1] is not None and v[1] != X['dur']]
        offs_ = collections.Counter(v[1] for v in tv_)
        for v in X.get('via', []):
            if v in tv_ and offs_[v[1]] == 1: cand.append((v[0], 'a', v[1], None))
            else: txt_v.append(v)
        for s_ in X.get('board', []):
            nm_, _, rs_ = s_.partition(' ')
            dv_ = _dur_of(rs_) if rs_.startswith('+') else None
            if dv_: cand.append((nm_, 'd', dv_, None))
            else: txt_b.append(s_)
        keep_lines, colmk = [], set()
        for ln in X.get('vnote', '').split('\n') if X.get('vnote') else []:
            mk, body = ln[0], ln[2:]
            got_, ok_, kind_, last_ = [], mk in '◇△', None, None
            for sg in body.split('・'):
                sg = sg.strip()
                if sg.startswith('경유 '): kind_ = 'a'; sg = sg[3:]
                elif sg.startswith('승차'): kind_ = 'd'; sg = sg[2:].strip()
                if kind_ is None: ok_ = False; break
                if kind_ == 'a':
                    nm_, _, rs_ = sg.partition(' '); dv_ = _dur_of(rs_)
                else:
                    if sg.startswith('+'): nm_, dv_ = last_, _dur_of(sg[1:])
                    else: nm_, _, rs_ = sg.partition(' '); dv_ = _dur_of(rs_[1:]) if rs_.startswith('+') else None
                if not nm_ or dv_ is None: ok_ = False; break
                got_.append((nm_, kind_, dv_, mk)); last_ = nm_
            if ok_ and got_: cand += got_; colmk.add(mk)
            else: keep_lines.append(ln)
        # 이름이 같으면 한 칸 (내리고 타는 곳: 타는 시각)
        cols_ = []
        for nm_, k_, dv_, mk in cand:
            c_ = next((c for c in cols_ if c[0] == nm_ and (c[3] == mk or c[3] is None or mk is None)), None)
            if c_:
                if c_[1] != k_: c_[1] = 'ad'
                c_[2] = dv_ if k_ == 'd' else c_[2]
                if mk is None: c_[3] = None
            else: cols_.append([nm_, k_, dv_, mk])
        if not cols_: continue
        if len(cols_) > 2:                               # 칸이 셋 넘으면(서울호남 → 보성 옥과・송광사・벌교) 안내 줄 그대로
            continue
        cols_.sort(key=lambda c: c[2])
        X['mid'] = [[c[0], c[1]] for c in cols_]
        X['mt'] = [[(_hm4(m_(t[0]) + c[2]) if (c[3] is None or c[3] in t[3:]) else '') for c in cols_] for t in X['times']]
        for t in X['times']:
            for mk in colmk:
                while mk in t: t.remove(mk)
        cn_ = {c[0] for c in cols_ if c[3] is None}
        X['via'] = [v for v in txt_v]
        if not X['via']: X.pop('via')
        X['board'] = txt_b
        if not X['board']: X.pop('board')
        if keep_lines: X['vnote'] = '\n'.join(keep_lines)
        else: X.pop('vnote', None); X.pop('_part', None)
for O in b['origins']:
    for X in O['dests']:
        if 'lab' in X and not any(X['lab']): X.pop('lab')
for M_ in json.load(open(os.path.join(HERE2_, 'manual-trips.json'))):     # 시각 모르는 경유지(시각표에 이름만): 「경유 꽃동산・장수」
    for O in b['origins']:
        for X in O['dests']:
            if not (O['from'] == M_['from'] and X['to'] == M_['to'] and 'times' in X): continue
            if M_.get('via_names'):
                vv_ = {v[0] for v in X.get('via', [])}
                X['via'] = X.get('via', []) + [[n_, None, None] for n_ in M_['via_names'] if n_ not in vv_]
            if M_.get('note') and M_['note'] not in X.get('vnote', ''):      # 시각표로 아는 몇 편만 서는 곳: 「◇ 경주 경유」
                X['vnote'] = (X['vnote'] + '\n' if X.get('vnote') else '') + M_['note']
            if M_.get('labels'):                         # 더 가는 편: 「→유성복합」
                lb_ = X.get('lab') or [''] * len(X['times'])
                for k_, t in enumerate(X['times']):
                    if t[0] in M_['labels'] and '시' in t[3:]: lb_[k_] = M_['labels'][t[0]]
                X['lab'] = lb_
for O in b['origins']:
    for X in O['dests']: X.pop('_mk1', None); X.pop('_mk2', None)
json.dump(b, open(sys.argv[3], 'w'), ensure_ascii=False, indent=0)
# 사람이 확인할 목록 (마크다운)
rep = ['# 고속버스 노선표: 확인할 것', '', '정류장 차례·경유 여부는 TAGO 구간별 시각을 맞물려 짐작한 것. 아래는 근거가 약하거나 따로 확인되지 않은 것.', '']
rep += ['## 1. 반대 방향·구간 소요로 확인되지 않은 연결 (시각만 맞물림)', '']
inT = lambda *ns: any(all(n_ in T['stops'] for n_ in ns) for T in tables)      # 실은 표에 든 것만
rep += ['- ' + x for k, x in sorted(set(unconf)) if inT(*k)]
rep += ['', '## 2. 맞물린 횟수가 적은 연결 (3번 이하)', '']
rep += ['- %s → %s (%d분 뒤) … %s 행, %d번' % (A, B, d, D, n) for D, A, B, d, n, pv in sorted(LB) if n <= 3 and inT(A, B, D)]
rep += ['- %s 발 %s 행이 %s 에 들름, %d번' % (A, D2, D1, n) for A, D1, D2, n, pv in sorted(LD) if n <= 3 and inT(A, D1, D2)]
rep += ['', '## 3. 정류장 차례가 방향마다 어긋나는 표 (TAGO 소요가 뒤바뀐 듯)', '']
for T in tables:
    st = T['stops']
    rv = [U for U in tables if set(U['stops']) == set(st) and U is not T]
    if rv and list(reversed(rv[0]['stops'])) != st and st < rv[0]['stops']:
        rep.append('- %s / 반대: %s' % (' → '.join(st), ' → '.join(rv[0]['stops'])))

open(sys.argv[4], 'w').write('\n'.join(rep) + '\n')
open(sys.argv[4] + '.log', 'w').write('\n'.join(sus) + '\n')
print('links board', len(LB), 'drop', len(LD), 'trips', len(trips), 'tables', len(tables), 'pairs owned', len(own),
      'cols', sum(len(T['cols']) for T in tables), 'suspects', len(sus), file=sys.stderr)
if len(sys.argv) > 5:
    for x in LB:
        if x[1] in sys.argv[5].split(',') or x[2] in sys.argv[5].split(','): print('LB', x, P[(x[1], x[0])]['dur'], P[(x[2], x[0])]['dur'], len(P[(x[1], x[0])]['t']), file=sys.stderr)
    for x in LD:
        if x[0] in sys.argv[5].split(','): print('LD', x, file=sys.stderr)
