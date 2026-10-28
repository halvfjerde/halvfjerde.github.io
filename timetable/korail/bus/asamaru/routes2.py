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
import json, sys, os, collections, math

b = json.load(open(sys.argv[1]))
m_ = lambda s: int(s[:-2]) * 60 + int(s[-2:])
hm = lambda x: '%d%02d' % (x // 60 % 24, x % 60)
hmd = lambda m: ('%d시간' % (m // 60) if m >= 60 else '') + (' ' if m >= 60 and m % 60 else '') + ('%d분' % (m % 60) if m % 60 or m < 60 else '')
WD = '월화수목금토일'
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
                    cnt = {d: sum(1 for t in ta if (t + d) % 1440 in tb and (t not in arr_ or arr_[t] - 10 <= t + d <= arr_[t] + 30)) for d in range(0, 421)}   # 닿고 30분 넘게 서 있지도 않는다
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
            if (A, B) in P and t in P[(A, B)]['t'] and not (P[(A, B)]['dur'] - 10 <= d <= P[(A, B)]['dur'] + 30): continue      # B 에 닿기 전(또는 한참 뒤) B 발: 다른 차
            x_, y_ = (A, t, D), (B, (t + d) % 1440, D)
            if (D, A, B) not in FLB and (x_ in FN or y_ in FN): continue
            u(x_, y_)
for A, D1, D2, n, pv in LD:
    t2 = P[(A, D2)]['t']
    for t in P[(A, D1)]['t']:
        if (A, D1, D2) not in FLD and ((A, t, D1) in FN or (A, t, D2) in FN): continue
        if t in t2: u((A, t, D1), (A, t, D2))
comp = collections.defaultdict(list)
for x in list(par): comp[f(x)].append(x)
trips = []
for nodes in comp.values():
    if len(nodes) < 2: continue
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
        k = (L, A, fk is not None)                      # 사람이 확인한 노선의 차는 그 밖의 차와 (끝·타는 곳이 같아도) 섞지 않는다
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
    dense = {p for p in pairs if len(P[p]['t']) > 3 * nn[p] + 5}      # 이 노선의 차는 몇 편뿐인 촘촘한 구간(광주→목포 따위): 표가 갖지 않고 목록에 둔다
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
    if U is None and apt(T) and len(T['cols']) <= 8 and T['stops'][-1].startswith('인천공항'):
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
pool = [p for p in both if not p[0].get('branch')]
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
BOFF_ = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'board-offsets.json')))
for T_, U_ in both:                                    # 노선표: TAGO 가 같은 시각을 붙인 타는 곳은 아는 분수만큼 뒤로
    for X_ in (T_, U_):
        if not X_: continue
        for c in X_['cols']:
            for k_, dv in BOFF_.items():
                a_, b_ = k_.split('|')
                if a_ in c and b_ in c and c[a_][0] == 'd' and c[b_][0] == 'd' and c[a_][1] == c[b_][1]:
                    c[b_] = ('d', (c[b_][1] + dv) % 1440)
            # 고창 ― 인천공항 시외 편: TAGO 에 고창 발만 있어 정읍·김제 칸이 비는 것을 나무위키 시각(정읍 +40, 김제 +80)으로
            if '고창' in c and c['고창'][0] == 'd' and c.get('_sub') and any(s_.startswith('인천공항') for s_ in c) and '정읍' not in c and '김제' not in c and '정읍' in X_['stops']:
                c['정읍'] = ('d', (c['고창'][1] + 40) % 1440); c['김제'] = ('d', (c['고창'][1] + 80) % 1440)
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
def cells_of(c, st, up=False):
    """up: 상하 병기의 상행(아래에서 위로 읽는다) — 통과 ↿, 하행·보통 표는 ⇂(v). 지나지 않는 곳도 통과(レ)로, 갈래가 갈린 표(지선)의 다른 갈래만 ║"""
    idx = [k for k, s_ in enumerate(st) if s_ in c]
    def other(s_): return s_ in BR and '_br' in c and BR[s_] != c['_br']        # 다른 갈래의 정류장
    def alt(s_): return any(s_ in g and any(o in c for g2 in A_ if g2 is not g for o in g2) for A_ in ALT for g in A_)   # 다른 길로 가는 차(alt-stops.json)
    def cell(k, s_):
        if s_ in c: return hm(c[s_][1])
        mid = idx[0] < k < idx[-1]
        if not mid: return 'x'
        if other(s_): return 'i'                                      # 다른 갈래(지선): ║
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
for T, U, ttl, part, cols_, ucols in emit:
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
open(sys.argv[2], 'w').write('\n'.join(out))
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
own = {p for T in tables for p in T['pairs']}
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
        if B_ in d and D in d and 'times' in d[B_] and 'times' in d[D] and ts_(d[B_]) <= ts_(d[D]):
            XB = d[B_]; d[D].setdefault('via', []).append([B_, XB['dur'], XB.get('fare')])
            XB.clear(); XB.update({'to': B_, 'see': D})
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
        if len({frozenset(t for t in mine if t in blocks[y][0]) for y in part}) > 1 or (part and 'vnote' in d[x]): return False   # ◇ 는 한 묶음(같은 편들)까지
        plan[x] = (mine, vias, part)
    for x in xs:
        mine, vias, part = plan[x]
        X = d[x]
        if not mine:                                      # 남은 편이 없으면 참조 줄: 편이 여러 덩이로 갔으면 가장 가까운 덩이로 (그 덩이의 「이 밖에」 줄이 나머지를 알린다)
            tgt = min({far[t] for t in blocks[x][0]}, key=xs.index)
            du_, fa_ = X['dur'], X.get('fare'); X.clear(); X.update({'to': x, 'see': tgt, 'dur': du_, 'fare': fa_}); continue
        X['times'] = [t for t in X['times'] if t[0] in set(mine)]
        if vias:
            vv = {v[0]: v for v in X.get('via', [])}
            for y in vias: vv.setdefault(y, [y, blocks[y][1], d[y].get('fare')])
            X['via'] = sorted(vv.values(), key=lambda v: (xs.index(v[0]) if v[0] in xs else -1, v[1]))      # 차례대로
        if part:
            y = part[0]
            for t in X['times']:
                if t[0] in blocks[y][0]: t.append('◇')
            X['_part'] = [[z, blocks[z][1], d[z].get('fare')] for z in part]
            X['vnote'] = '◇ 경유 ' + '・'.join('%s %s' % (nm(z), hmd(blocks[z][1])) for z in part)
        also = collections.Counter(far[t] for t in blocks[x][0] if far[t] != x)
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
        got = {(t + e) % 1440 for t in tA if (t + e) % 1440 in {m_(t[0]) for t in X['times']} and (t not in arrB or t + e >= arrB[t] - 10)}
        if not e: e_ = BOFF.get('%s|%s' % (A, o), 0)
        else: e_ = e
        es = ('+' + hmd(e_)) if e_ else ''
        if k == len(tA): Y.setdefault('board', []).append(o + (' ' + es if es else ''))
        elif 'vnote' not in Y:
            for t in Y['times']:
                if (m_(t[0]) + e) % 1440 in got: t.append('◇')
            Y['vnote'] = '◇ 승차 %s%s' % (nm(o), ' ' + es if es else '')
        elif ' %s ' % nm(o) in Y['vnote'] + ' ' and {m_(t[0]) for t in Y['times'] if '◇' in t[3:]} == {t for t in tA if (t + e) % 1440 in got}:
            Y['vnote'] += '・승차 %s' % es if es else '・승차'      # 같은 ◇ 편이 그 정류장에 내리고 타기도: 「◇ 경유 황간 30분・승차 +30분」
        else: continue
        rest_ = [t for t in X['times'] if m_(t[0]) not in got]
        if rest_: X['times'] = rest_; X['vnote3'] = '이 밖에 %s 발 %d편도 탐' % (nm(A), len(got))
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
        for i, o in enumerate(seq):
            if o not in OR: continue
            d = {X['to']: X for X in OR[o]['dests'] if 'times' in X}
            xs = [x for x in seq[i + 1:] if x in d]
            if len(xs) >= 2 and merge_drop(d, xs): nl += 1
        for k, D in enumerate(seq): nl += merge_board(D, seq[:k])
for O in b['origins']:                                  # ◇ 경유가 남은 편 모두에 붙었으면(다른 묶음이 편을 가져간 뒤) 「경유」로
    for X in O['dests']:
        if X.get('_part') and all('◇' in t for t in X['times']):
            for t in X['times']: t.remove('◇')
            vv = {v[0]: v for v in X.get('via', [])}
            for v in X.pop('_part'): vv.setdefault(v[0], v)
            X['via'] = sorted(vv.values(), key=lambda v: v[1]); X.pop('vnote', None)
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
            hit_ = [t for t in X['times'] if t[0] in K_['times']]
            if len(hit_) == len(X['times']): X.setdefault('board', []).extend(K_['board'])
            elif hit_:
                for t in hit_: t.append('◇')
                X['vnote'] = '◇ 승차 ' + '・'.join(K_['board'])
print('auto chains', len(AUTO), 'review', len(REVIEW), file=sys.stderr)
b['autoChains'] = [[o] + xs for o, xs in AUTO]
b['reviewChains'] = [[o] + xs for o, xs in REVIEW]
b['routeOwned'] = sorted('%s→%s' % p for p in own)
b['names'] = SHORT
b['tableRefs'] = sorted([A, D, title_of[id(T)], P[(A, D)]['dur'], P[(A, D)]['fare']] for T in tables for A, D in T['pairs'])   # 목록에서 노선표로 보내는 줄
b['tableRefs'] += sorted(map(list, {tuple(x[:3]) + (x[3], tuple(x[4]) if x[4] else None) for x in SKIPREF}))
b['tableRefs'] += sorted([A, D, title_of[i_], du_, None] for A, D, i_, du_ in set(EXREF) if i_ in title_of)                  # TAGO 에 없는 끝 정류장 (요금 모름)
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
