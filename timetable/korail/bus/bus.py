#!/usr/bin/env python3
"""TAGO 고속버스정보로 노선별 시각표(모듈:Timetable, 상하병기) 원문을 만든다.
python3 bus.py 날짜(YYYYMMDD) 출발터미널ID… > 고속버스.txt
열쇠는 /root/.config/tago.key (저장소에 넣지 않는다). 받은 것은 ~/.cache/tago-bus 에 둔다
· 한 노선 = 출발 터미널 O 에서 종점 X 까지. 같은 시각에 O 를 떠나 X 보다 먼저 닿는 곳(S)은 그 버스의 정차지
· 정차지 판정: S 의 발차가 모두 X 의 발차에 들고 소요가 X 보다 짧을 때, X 는 그런 것 가운데 소요 차가 가장 작은 곳.
  S→X 버스가 따로 있으면 O→S + S→X ≈ O→X 일 때만 (아니면 우연히 같은 시각에 떠나는 다른 노선)
· 상행: X→O 와 S→O 를 받아 O 에 닿는 시각이 같은 것을 한 버스로"""
import json, sys, os, time, urllib.request, urllib.parse, collections, concurrent.futures as cf
KEY = open('/root/.config/tago.key').read().strip()
BASE = 'https://apis.data.go.kr/1613000/ExpBusInfo/'
CACHE = os.path.expanduser('~/.cache/tago-bus'); os.makedirs(CACHE, exist_ok=True)

def api(op, **kw):
    kw.update(serviceKey=KEY, _type='json', numOfRows=kw.get('numOfRows', 1000), pageNo=1)
    ck = os.path.join(CACHE, op + '-' + '-'.join('%s=%s' % (k, v) for k, v in sorted(kw.items()) if k not in ('serviceKey', '_type', 'pageNo')))
    if os.path.exists(ck): return json.load(open(ck))
    u = BASE + op + '?' + urllib.parse.urlencode(kw)
    for t in range(4):
        try:
            j = json.loads(urllib.request.urlopen(u, timeout=40).read().decode())
            if 'response' in j:
                json.dump(j, open(ck, 'w'), ensure_ascii=False); return j
        except Exception: pass
        time.sleep(1 + t)
    return {}

def items(j):
    b = j.get('response', {}).get('body', {}); it = b.get('items') or {}
    it = it.get('item', []) if isinstance(it, dict) else []
    return it if isinstance(it, list) else [it]

def mins(x): s = str(x); return int(s[8:10]) * 60 + int(s[10:12])
def trips(dep, arr, day):
    """dep→arr 의 버스 {출발 분: (도착 분, 등급, 요금)}"""
    out = {}
    for r in items(api('GetStrtpntAlocFndExpbusInfo', depTerminalId=dep, arrTerminalId=arr, depPlandTime=day)):
        out[mins(r['depPlandTime'])] = (mins(r['arrPlandTime']), r.get('gradeNm', ''), r.get('charge'))
    return out
dur = lambda t, a: (a - t) % 1440

GRADE = {'우등': '우등', '프리미엄': '프리', '일반': '일반', '심야우등': '심우', '심야프리미엄': '심프', '심야일반': '심일', '심야고속': '심고'}
def hm(m): return '%d%02d' % (m // 60 % 24, m % 60)

def routes(O, fwd, day, nm):
    """fwd: {도착지: {출발 분: (도착 분, 등급, 요금)}} → [(종점 X, [정차지 S…])]"""
    D = {x: v for x, v in fwd.items() if v}
    avgd = {x: sum(dur(t, a) for t, (a, _, _) in v.items()) / len(v) for x, v in D.items()}
    parent = {}
    for s, vs in D.items():
        cands = [x for x, vx in D.items() if x != s and set(vs) <= set(vx) and all(dur(t, vs[t][0]) < dur(t, vx[t][0]) for t in vs)]
        cands.sort(key=lambda x: avgd[x] - avgd[s])
        for x in cands[:3]:
            sx = trips(s, x, day)
            if sx:      # S→X 버스가 따로 있다: 소요가 맞아야 같은 노선
                d_sx = sum(dur(t, a) for t, (a, _, _) in sx.items()) / len(sx)
                if abs(avgd[s] + d_sx - avgd[x]) > 25: continue
            elif avgd[x] - avgd[s] > 60: continue
            parent[s] = x; break
    def root(x):
        seen = set()
        while x in parent and x not in seen: seen.add(x); x = parent[x]
        return x
    out = collections.defaultdict(list)
    for s in parent: out[root(s)].append(s)
    return [(x, sorted(out.get(x, []), key=lambda s: avgd[s])) for x in sorted([x for x in D if x not in parent], key=lambda x: avgd[x])], D

def table(O, X, stops, D, day, nm):
    sts = [O] + stops + [X]
    down = sorted(D[X])
    cols_d = []
    for t in down:
        g = D[X][t][1]
        cells = [hm(t)] + [hm(D[s][t][0]) if t in D.get(s, {}) else 'v' for s in stops] + [hm(D[X][t][0])]
        cols_d.append((g, cells))
    # 상행: X→O 와 S→O, O 에 닿는 시각으로 한 버스
    up_x = trips(X, O, day)
    up_s = {s: trips(s, O, day) for s in stops}
    by_arr = {}
    for t, (a, g, _) in up_x.items(): by_arr[a] = (t, g)
    cols_u = []
    for a in sorted(by_arr, key=lambda a: by_arr[a][0]):
        t, g = by_arr[a]
        st_t = {}
        for s in stops:
            hit = [ts for ts, (aa, _, _) in up_s[s].items() if aa == a]
            st_t[s] = hit[0] if hit else None
        cells = [hm(t)] + [hm(st_t[s]) if st_t[s] is not None else 'v' for s in reversed(stops)] + [hm(a)]
        cols_u.append((g, cells))
    L = ['title "%s ― %s"' % (nm[O], nm[X]), 'headl "b%s ― %s"' % (nm[O], nm[X]), 'cols ad st ad', 'both 1', '',
         '[rows]', 'kind 등급 style=va=b r=等級', '', '[stations]']
    for i, s in enumerate(sts):
        ad = '發' if i == 0 else '着'
        L.append('%s %s%s %s' % (ad, '**' if i in (0, len(sts) - 1) else '', nm[s], ad))
    L += ['', '[trains]'] + ['S{%s} : %s' % (GRADE.get(g, g[:2]), ' '.join(c)) for g, c in cols_d]
    L += ['', '[trains up]'] + ['S{%s} : %s' % (GRADE.get(g, g[:2]), ' '.join(c)) for g, c in cols_u]
    return '\n'.join(L), len(cols_d), len(cols_u)

if __name__ == '__main__':
    day = sys.argv[1]
    nm = {}
    for t in items(api('GetExpBusTrminlList')): nm[t['terminalId']] = t['terminalNm']
    P = ["{{시각표테마}}", "'''고속버스''' 시각표. 국토교통부 TAGO 고속버스정보(%s) 기준." % day, '']
    for O in sys.argv[2:]:
        fwd = {x: trips(O, x, day) for x in nm if x != O}
        rs, D = routes(O, fwd, day, nm)
        for X, stops in rs:
            txt, nd, nu = table(O, X, stops, D, day, nm)
            print('%s→%s %d/%d %s' % (nm[O], nm[X], nd, nu, ','.join(nm[s] for s in stops)), file=sys.stderr)
            P += ['== %s ― %s ==' % (nm[O], nm[X]), '{{#invoke:Timetable|main|data=', txt, '}}', '']
    print('\n'.join(P))
