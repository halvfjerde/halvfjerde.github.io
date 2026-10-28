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
# 사람이 확인한 같은 차(force-links.json: 정류장 차례): 맞물린 편이 하나뿐이어도 잇는다 (시각이 맞는 δ 로)
FORCE = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'force-links.json')))
have = {(D, A, B) for D, A, B, *_ in LB}
haved = {(A, D1, D2) for A, D1, D2, *_ in LD}
for seq in FORCE:
    for i, A in enumerate(seq):
        for B in seq[i + 1:]:
            for D in seq[seq.index(B) + 1:]:                 # 타는 곳: A 다음 B, 둘 다 D 로
                if (A, D) in P and (B, D) in P and (D, A, B) not in have:
                    ta, tb = P[(A, D)]['t'], P[(B, D)]['t']
                    cnt = {d: sum(1 for t in ta if (t + d) % 1440 in tb) for d in range(0, 181)}
                    d = max(cnt, key=lambda d: cnt[d])
                    if cnt[d] >= 1: LB.append((D, A, B, d, cnt[d], 0.0)); have.add((D, A, B))
            for D2 in seq[i + 1:]:                           # 내리는 곳: A 에서 B(먼저) 거쳐 D2
                if D2 != B and seq.index(D2) > seq.index(B) and (A, B) in P and (A, D2) in P and (A, B, D2) not in haved:
                    n = len(set(P[(A, B)]['t']) & set(P[(A, D2)]['t']))
                    if n >= 1: LD.append((A, B, D2, n, 0.0)); haved.add((A, B, D2))

# 마디 (A, t, D) 를 단서로 잇는다
par = {}
def f(x):
    par.setdefault(x, x)
    while par[x] != x: par[x] = par[par[x]]; x = par[x]
    return x
def u(x, y): par[f(x)] = f(y)
for D, A, B, d, n, pv in LB:
    tb = P[(B, D)]['t']
    for t in P[(A, D)]['t']:
        if (t + d) % 1440 in tb: u((A, t, D), (B, (t + d) % 1440, D))
for A, D1, D2, n, pv in LD:
    t2 = P[(A, D2)]['t']
    for t in P[(A, D1)]['t']:
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
for i, tr in enumerate(trips):
    L = last(tr)
    for A in tr['board']:
        k = (L, A)
        if k in seen: tp[g(i)] = g(seen[k])
        else: seen[k] = i
groups = collections.defaultdict(list)
for i in range(len(trips)): groups[g(i)].append(trips[i])

tables, owned = [], set()
for grp in groups.values():
    L = last(grp[0])
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
    bset = {A for tr in grp for A in tr['board']}
    dset = {D for tr in grp for D in tr['drop']} - bset
    pairs = {(A, D) for tr in grp for A, t, D in tr['nodes']}
    pairs = {p for p in pairs if p not in owned}
    owned |= pairs
    cols = []
    for tr in grp:
        cols.append({s: ('d', tr['board'][s]) if s in tr['board'] else ('a', tr['drop'][s]) for s in stops if s in tr['board'] or s in tr['drop']} | {'_w': tr['w'], '_sub': tr['sub']})
    used = {(A, t, D) for tr in grp for A, t, D in tr['nodes']}
    for A, D in sorted(pairs):                         # 그 구간의 다른 차(정류장을 거치지 않는 차)도 이 표에
        for t, w in P[(A, D)]['t'].items():
            x = (A, t, D)
            if x in used or (x in par and len(comp.get(f(x), [])) > 1): continue      # 다른 표의 차
            cols.append({A: ('d', t), D: ('a', (t + P[(A, D)]['dur']) % 1440), '_w': w, '_sub': x in SUBN})
    def key(c):
        for k_, s in enumerate(stops):
            if s in c: return (c[s][1] - 0) % 1440 + (0 if c[s][1] >= 240 else 1440), k_
    cols.sort(key=key)
    tables.append({'stops': stops, 'board': bset, 'cols': cols, 'pairs': pairs, 'last': L})

GR = {'우': '우등', '일': '일반', '프': '프리', '심': '심우', '심프': '심프', '심일': '심일'}
def wdl(ws):
    ws = sorted(ws)
    if len(ws) == 7: return '_'
    if ws == [0, 1, 2, 3, 4]: return '월∼금'
    if len(ws) >= 3 and ws == list(range(ws[0], ws[-1] + 1)): return WD[ws[0]] + '∼' + WD[ws[-1]]
    return ''.join(WD[w] for w in ws)
# 노선표에 실을 것만 고른다: 타는 곳이 둘 이상이고 그 시각이 실제로 다른(δ>0) 노선 — 목록으로는 보여 줄 수 없는 것.
# 정류장이 많은 차례로, 표 칸(차 수)의 합이 CAP 안에서 (두 쪽 안팎)
CAP = int(os.environ.get('CAP', '40'))           # 한 쪽에 드는 만큼 (조판해 보고 정함)
def real_board(T):
    return sum(1 for s_ in T['board'] if any(c.get(s_, ('', 0))[0] == 'd' for c in T['cols'])) >= 2 and \
        any(len({c[s_][1] for s_ in T['board'] if s_ in c and c[s_][0] == 'd'}) >= 2 for c in T['cols'])
cand = sorted([T for T in tables if real_board(T)], key=lambda T: (-len(T['stops']), len(T['cols'])))
pick, tot = [], 0
for T in cand:
    if len(T['cols']) <= int(os.environ.get('MAXC', '16')) and tot + len(T['cols']) <= CAP: pick.append(T); tot += len(T['cols'])
# 주요·긴 노선: 정류장이 넷 넘는 표를 차 수가 많은 차례로 CAP2 안에서 (한 쪽 폭에 안 들면 접어 아래로)
CAP2 = int(os.environ.get('CAP2', '80'))
tot2 = 0
W1 = int(os.environ.get('W1', '20'))                # 한 쪽 폭에 드는 편 수 (어림)
fits = lambda n: n <= W1 or n % W1 == 0 or n % W1 >= W1 // 2      # 접었을 때 끝 띠가 너무 짧지 않게
for T in sorted([T for T in tables if T not in pick and len(T['stops']) >= 4 and fits(len(T['cols']))],
                key=lambda T: (-len(T['cols']) * len(T['stops']))):       # 주요(차가 많고) 긴(정류장이 많은) 노선부터
    if tot2 + len(T['cols']) <= CAP2: pick.append(T); tot2 += len(T['cols'])
for T in tables:                                        # 사람이 확인한 노선(force-links)은 늘 싣는다
    if T not in pick and any(sum(1 for s_ in T['stops'] if s_ in seq) >= 3 for seq in FORCE): pick.append(T)
print('candidates', len(cand), 'picked', len(pick), 'cols', tot, '+', tot2, file=sys.stderr)
# 편도 8편 이하: 반대 방향 표(정류장이 같은 것)와 상하 병기 한 표로 (고르지 않았어도 반대 방향은 곁들인다)
ALL = tables
both = []
used_ = set()
for T in pick:
    if id(T) in used_: continue
    U = next((U for U in ALL if U is not T and set(U['stops']) == set(T['stops']) and id(U) not in used_), None)
    if U and len(T['cols']) <= 8 and len(U['cols']) <= 8:
        both.append((T, U)); used_ |= {id(T), id(U)}
    else:
        both.append((T, None)); used_.add(id(T))
SHORT = {'센트럴시티(서울)': '서울호남', '광주(유·스퀘어)': '광주', '대전청사(샘머리)': '대전청사', '세종터미널(연구)': '세종터미널', '청주(센트럴)': '청주',
         '동천(호남)': '동천', '임자(진리)': '임자', '가톨릭관동대강릉': '가톨릭관동대', '아산탕정사무소': '아산탕정', '천안종합운동장': '천안운동장',
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
both.sort(key=lambda p: (-(len(p[0]['cols']) > W1), -apt(p[0]), p[0]['stops'][0], p[0]['stops'][-1]))
def foot(c):
    w = c['_w']
    gs = collections.Counter(x for x in w if x)
    g0 = gs.most_common(1)[0][0] if gs else '우'
    diff = [d for d in range(7) if w[d] and w[d] != g0]
    rem_ = ('%s%s' % (''.join(WD[d] for d in diff), GR.get(w[diff[0]], w[diff[0]]))) if diff else '_'
    if c.get('_sub'): rem_ = '†' if rem_ == '_' else '†' + rem_          # 시외버스로 파는 편
    return g0, wdl([d for d in range(7) if w[d]]), rem_
BR = {}
def cells_of(c, st):
    idx = [k for k, s_ in enumerate(st) if s_ in c]
    def other(s_): return s_ in BR and '_br' in c and BR[s_] != c['_br']        # 다른 갈래의 정류장
    return [hm(c[s_][1]) if s_ in c else ('i' if other(s_) and idx[0] < k < idx[-1] else 'x' if other(s_) else ('v' if idx[0] < k < idx[-1] else 'x')) for k, s_ in enumerate(st)]
def line(c, st):
    g0, dl_, rem_ = foot(c)
    kind = '"◆"' if g0 == '◆' else 'S{%s}' % GR.get(g0, g0)          # 차마다 돌아가는 등급
    return '%s : %s : %s %s' % (kind, ' '.join(cells_of(c, st)), dl_, rem_)
ORD = ['첫째', '둘째', '셋째', '넷째', '다섯째', '여섯째']
emit = []
for T, U in both:                                       # 한 쪽 폭을 넘는 표는 같은 이름의 표 여럿으로 나눠 위아래로 (펼침면으로 넘기지 않게)
    n = len(T['cols'])
    if U or n <= W1: emit.append((T, U, '', T['cols'])); continue
    k = -(-n // W1); sz = [n // k + (1 if i < n % k else 0) for i in range(k)]
    a_ = 0
    for i, z in enumerate(sz): emit.append((T, None, '（%s）' % ORD[i], T['cols'][a_:a_ + z])); a_ += z
for T, U, part, cols_ in emit:
    st = T['stops']
    BR.clear(); BR.update(T.get('branch', {}))
    ttl = T.get('title') or '%s ― %s' % (nm(st[0]), nm(st[-1]))
    out += ['=== %s%s ===' % (ttl, part), '{{#invoke:Timetable|main|data=', 'title "%s%s"' % (ttl, part), 'headl "b%s"' % ttl]
    out += (['cols ad st ad', 'both 1'] if U else ['cols st ad', 'rcols st']) + ['',
            '[rows]', 'kind 등급 style=va=b r=等級', '', '[footer]', 'days 운행일 r=運行日 style=va=t', 'rem 비고 r=備考 style=va=t', '', '[stations]']
    pv, pu = None, None
    for i, s_ in enumerate(st):
        ad = '發' if s_ in T['board'] else '着'
        mk = '*' if i in (0, len(st) - 1) else ''
        if U:
            au = '發' if s_ in U['board'] else '着'
            out.append('%s %s%s %s' % (ad if ad != pv else '〃', mk, nm(s_), au if au != pu else '〃'))
            pu = au
        else:
            out.append('%s%s %s' % (mk, nm(s_), ad if ad != pv else '〃'))
        pv = ad
    out += ['', '[trains]'] + [line(c, st) for c in cols_]
    if U:
        rs = list(reversed(st))                        # 상행은 아래(출발)에서 위로 읽는 차례로
        out += ['', '[trains up]'] + [line(c, rs) for c in U['cols']]
    out += ['', '[notes]', '}}', '']
tables = [T for p in both for T in p if T]
title_of = {id(X_): T.get('title') or '%s ― %s' % (nm(T['stops'][0]), nm(T['stops'][-1])) for T, U in both for X_ in (T, U) if X_}      # 상하 병기면 상행도 하행 표 이름으로
for k_, M_ in title_merge.items(): title_of[k_] = title_of[id(M_)]
open(sys.argv[2], 'w').write('\n'.join(out))
# 일부 편만 들르는 정류장 (사람이 확인한 것, partial-stops.json: [A, B, D] = A 발 D 행의 몇 편이 B 에도 선다): 목록의 A→D 에 ◇ 표지와 안내 줄
PART = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'partial-stops.json')))
pmark = {}
for A, B_, D in PART:
    if (A, D) in P and (B_, D) in P:                     # 오는 길: A 발 + δ 에 B 발
        ta, tb = P[(A, D)]['t'], P[(B_, D)]['t']
        d = max(range(1, 121), key=lambda d: sum(1 for t in ta if (t + d) % 1440 in tb))
        pmark[(A, D)] = ({t for t in ta if (t + d) % 1440 in tb}, '◇ %s 경유 (%s 발 %d분 뒤)' % (nm(B_), nm(A), d))
    if (D, A) in P and (D, B_) in P:                     # 가는 길: D 발이 같은 시각이면 B 에 먼저 선다
        ta, tb = P[(D, A)]['t'], P[(D, B_)]['t']
        d = P[(D, A)]['dur'] - P[(D, B_)]['dur']
        pmark[(D, A)] = ({t for t in ta if t in tb}, '◇ %s 경유 (%s 착 %d분 전)' % (nm(B_), nm(A), d))
own = {p for T in tables for p in T['pairs']}
for O in b['origins']: O['dests'] = [X for X in O['dests'] if (O['from'], X['to']) not in own]
b['origins'] = [O for O in b['origins'] if O['dests']]
for O in b['origins']:
    for X in O['dests']:
        k = (O['from'], X['to'])
        if k in pmark:
            ts, note = pmark[k]
            X['vnote'] = note
            for t in X['times']:
                if m_(t[0]) in ts: t.append('◇')
b['routeOwned'] = sorted('%s→%s' % p for p in own)
b['names'] = SHORT
b['tableRefs'] = sorted([A, D, title_of[id(T)], P[(A, D)]['dur'], P[(A, D)]['fare']] for T in tables for A, D in T['pairs'])   # 목록에서 노선표로 보내는 줄
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
