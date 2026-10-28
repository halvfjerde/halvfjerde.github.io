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
    w = P[(first, next(D for A, t, D in nodes if A == first))]['t'][board[first]]
    trips.append({'board': board, 'drop': {D: a for D, (a, _) in drop.items()}, 'w': w, 'nodes': nodes})

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
    bset = {A for tr in grp for A in tr['board']}
    dset = {D for tr in grp for D in tr['drop']} - bset
    pairs = {(A, D) for tr in grp for A, t, D in tr['nodes']}
    pairs = {p for p in pairs if p not in owned}
    owned |= pairs
    cols = []
    for tr in grp:
        cols.append({s: ('d', tr['board'][s]) if s in tr['board'] else ('a', tr['drop'][s]) for s in stops if s in tr['board'] or s in tr['drop']} | {'_w': tr['w']})
    used = {(A, t, D) for tr in grp for A, t, D in tr['nodes']}
    for A, D in sorted(pairs):                         # 그 구간의 다른 차(정류장을 거치지 않는 차)도 이 표에
        for t, w in P[(A, D)]['t'].items():
            x = (A, t, D)
            if x in used or (x in par and len(comp.get(f(x), [])) > 1): continue      # 다른 표의 차
            cols.append({A: ('d', t), D: ('a', (t + P[(A, D)]['dur']) % 1440), '_w': w})
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
print('candidates', len(cand), 'picked', len(pick), 'cols', tot, file=sys.stderr)
tables = pick
out = ["{{시각표테마}}", "'''고속버스''' 노선표. 국토교통부 TAGO 고속버스정보(2026년 10월 24∼30일) 기준.", '', '== 고속버스 ==']
tables.sort(key=lambda T: (T['stops'][0], T['stops'][-1]))
for T in tables:
    st = T['stops']
    def foot(c):
        w = c['_w']
        gs = collections.Counter(x for x in w if x)
        g0 = gs.most_common(1)[0][0] if gs else '우'
        diff = [d for d in range(7) if w[d] and w[d] != g0]
        rem_ = ('%s%s' % (''.join(WD[d] for d in diff), GR.get(w[diff[0]], w[diff[0]]))) if diff else '_'
        return g0, wdl([d for d in range(7) if w[d]]), rem_
    fs_ = [foot(c) for c in T['cols']]
    hasd = hasr = True                                   # 표마다 줄 짜임이 같아야 나란히 놓을 때 어긋나지 않는다
    out += ['=== %s ― %s ===' % (st[0], st[-1]), '{{#invoke:Timetable|main|data=',
            'title "%s ― %s"' % (st[0], st[-1]), 'headl "b%s ― %s"' % (st[0], st[-1]), 'cols st ad', 'rcols st', '',
            '[rows]', 'kind 등급 style=va=b r=等級', '']
    if hasd or hasr:
        out += ['[footer]'] + (['days 운행일 r=運行日 style=va=t'] if hasd else []) + (['rem 비고 r=備考 style=va=t'] if hasr else []) + ['']
    out += ['[stations]']
    prev = None
    for i, s in enumerate(st):
        ad = '發' if s in T['board'] else '着'
        out.append('%s%s %s' % ('**' if i in (0, len(st) - 1) else '', s, ad if ad != prev else '〃'))
        prev = ad
    out += ['', '[trains]']
    for c, (g0, dl_, rem_) in zip(T['cols'], fs_):
        idx = [k for k, s in enumerate(st) if s in c]
        cells = []
        for k, s in enumerate(st):
            if s in c: cells.append(hm(c[s][1]))
            elif idx[0] < k < idx[-1]: cells.append('v')
            else: cells.append('x')
        ft = ([dl_] if hasd else []) + ([rem_] if hasr else [])
        out.append('S{%s} : %s' % (GR.get(g0, g0), ' '.join(cells)) + (' : ' + ' '.join(ft) if ft else ''))
    out += ['', '[notes]', '}}', '']
open(sys.argv[2], 'w').write('\n'.join(out))
own = {p for T in tables for p in T['pairs']}
for O in b['origins']: O['dests'] = [X for X in O['dests'] if (O['from'], X['to']) not in own]
b['origins'] = [O for O in b['origins'] if O['dests']]
b['routeOwned'] = sorted('%s→%s' % p for p in own)
b['tableRefs'] = sorted([A, D, '%s ― %s' % (T['stops'][0], T['stops'][-1])] for T in tables for A, D in T['pairs'])   # 목록에서 노선표로 보내는 줄
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
