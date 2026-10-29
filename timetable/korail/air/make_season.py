#!/usr/bin/env python3
"""공항공사 국내선 스케줄(SCHEDULE_DOM_*.xlsx) → 한 철(동계·하계)의 정기편 다이아 air.json
운항일은 철 전체를 두고 적는다: 요일마다 다니는 주(週)가 같은 요일끼리 묶어 「화・목・토・일, 월・수・금 12월 11일까지・12월 21일∼1월 15일」.
요금은 TAGO 한 달치(있으면)에서. FROM=20261101 python3 make_season.py kac/ [flights-YYYYMM.json(TAGO)] > air.json"""
import sys, os, glob, calendar, json, datetime, collections, re, openpyxl
D = datetime.date
EN = {'GIMPO': '김포', 'GIMHAE': '김해', 'JEJU': '제주', 'CHEONGJU': '청주', 'DAEGU': '대구', 'YANGYANG': '양양', 'GWANGJU': '광주',
      'ULSAN': '울산', 'YEOSU': '여수', 'POHANG GYEONGJU': '포항', 'SACHEON': '사천', 'GUNSAN': '군산', 'WONJU': '원주', 'INCHEON': '인천', 'MUAN': '무안'}
WD = '월화수목금토일'
recs = set()
for f in sorted(glob.glob(sys.argv[1] + '/*SCHEDULE_DOM_*.xlsx')):
    for r in list(openpyxl.load_workbook(f, read_only=True).worksheets[0].iter_rows(values_only=True))[2:]:
        if not r or not r[2]: continue
        kind, al, no, ap, sec, dt, at = r[:7]
        if kind == '出発': dep, arr = ap, sec
        elif kind == '到着' and ap == 'INCHEON': dep, arr = ap, sec          # 인천발은 도착 행에서 (도착 행의 「공항」 칸은 떠난 공항)
        else: continue
        a_, b_ = re.findall(r'(\d{4})\.(\d{2})\.(\d{2})', r[14])
        recs.add((EN[dep], EN[arr], no, dt.replace(':', ''), at.replace(':', ''), tuple(x == 'Y' for x in r[7:14]), D(*map(int, a_)), D(*map(int, b_))))
S0 = min(r[6] for r in recs); S1 = max(r[7] for r in recs)                  # 철: 가장 이른 시작 ∼ 가장 늦은 끝
if os.environ.get('FROM'): S0 = max(S0, D(*map(int, re.findall(r'(\d{4})(\d\d)(\d\d)', os.environ['FROM'])[0])))   # 책이 나가는 달 첫날부터 (지난 날은 버린다)
season = [S0 + datetime.timedelta(n) for n in range((S1 - S0).days + 1)]
fl = collections.defaultdict(lambda: collections.defaultdict(set))          # (발,착) → (편,발,착) → 날짜들
for dep, arr, no, t, a, fg, d0, d1 in recs:
    for d in season:
        if d0 <= d <= d1 and fg[d.weekday()]: fl[(dep, arr)][(no, t, a)].add(d)
# 공항공사 스케줄에 없는 편 (TAGO 한 달치에만: 인천 연결편·임시편). 그 달 끝 주에도 뜨면 그 요일로 철 끝까지 이어 뜬다고 본다.
# 김포↔인천의 편명 끝 A·P (특별·전세 편)는 싣지 않는다
if os.environ.get('EXTRA'):
    ex = json.load(open(os.environ['EXTRA']))
    by = collections.defaultdict(set)
    for f in ex['flights']:
        if {f['dep'], f['arr']} == {'김포', '인천'} and f['no'][-1] in 'AP': continue
        by[(f['dep'], f['arr'], f['no'], f['t'], f['a'])].add(D(int(f['day'][:4]), int(f['day'][4:6]), int(f['day'][6:])))
    for (dep, arr, no, t, a), ds in by.items():
        last = max(ds); mend = D(last.year, last.month, calendar.monthrange(last.year, last.month)[1])
        ws = {d.weekday() for d in ds}
        if (mend - last).days <= 1 and (last - min(ds)).days >= 6:      # 달 끝까지 한 주 넘게 뜬 편만 이어 뜬다고 본다
            ds = ds | {d for d in season if d > mend and d.weekday() in ws}
        fl[(dep, arr)][(no, t, a)] |= {d for d in ds if S0 <= d <= S1}
mon0 = S0 - datetime.timedelta(S0.weekday())
wk = lambda d: (d - mon0).days // 7
def wdl(ws):
    ws = sorted(ws)
    if ws == [0, 1, 2, 3, 4]: return '월∼금'
    if len(ws) >= 4 and len(ws) < 7:                     # 넉 날 넘게 이어진 요일은 「금∼월」처럼 (주를 넘어 이어져도). 사흘은 「화・수・목」 (사용자)
        for s0 in ws:
            if sorted((s0 + k) % 7 for k in range(len(ws))) == ws: return WD[s0] + '∼' + WD[(s0 + len(ws) - 1) % 7]
    return '・'.join(WD[w] for w in ws)
def md(d, prev=None): return ('%d일' % d.day) if prev and prev.month == d.month else '%d월 %d일' % (d.month, d.day)
def label_wk(days):
    """철 전체에 대한 운항일. 매일이면 비운다"""
    days = set(days)
    if not days: return ''
    occ = {w: frozenset(wk(d) for d in days if d.weekday() == w) for w in range(7)}
    allw = {w: frozenset(wk(d) for d in season if d.weekday() == w) for w in range(7)}
    grp = collections.OrderedDict()                      # 다니는 주가 같은 요일끼리 (주 번호로 맞춘다: 철의 첫 주·끝 주의 반쪽은 「다 다님」으로 친다)
    for w in range(7):
        if not occ[w]: continue
        key = 'ALL' if occ[w] == allw[w] else occ[w]
        grp.setdefault(key, []).append(w)
    parts = []
    for key, ws in sorted(grp.items(), key=lambda kv: (kv[0] != 'ALL', -len(kv[1]))):
        wl = '' if len(ws) == 7 else wdl(ws)
        if key == 'ALL': parts.append(wl); continue
        ds = sorted(d for d in days if d.weekday() in ws)
        sq = sorted(d for d in season if d.weekday() in ws)
        runs, cur = [], None
        for d in sq:                                     # 그 요일들의 날을 차례로: 다니는 날이 끊기지 않는 동안이 한 동안
            if d in days:
                if cur: cur[1] = d
                else: cur = [d, d]
            elif cur: runs.append(cur); cur = None
        if cur: runs.append(cur)
        txt = []
        for a, b in runs:
            if a == b: txt.append(md(a))
            elif a == sq[0]: txt.append(md(b) + '까지')
            elif b == sq[-1]: txt.append(md(a) + '부터')
            else: txt.append(md(a) + '∼' + md(b, a))
        parts.append((wl + ' ' if wl else '') + '・'.join(txt))
    return ', '.join(parts)
def label_skip(days, noW=False):
    """요일 W(그 요일 날의 절반 넘게 다님) 위에: 앞뒤를 자른 동안과 「…제외」 동안, W 밖 요일에 더 다니는 날"""
    days = set(days)
    lo0, hi0 = min(days), max(days)
    W = {w for w in range(7) if 2 * sum(1 for d in days if d.weekday() == w) > sum(1 for d in season if d.weekday() == w and lo0 <= d <= hi0)}
    if all(d in days for d in season if lo0 <= d <= hi0): W = set(range(7))       # 동안 안에서 날마다
    if not W: return None
    B = [d for d in season if d.weekday() in W]
    on = [d for d in B if d in days]
    if not on: return None
    lo, hi = on[0], on[-1]
    gaps, cur = [], None                                 # lo∼hi 안에서 W 날인데 안 다니는 동안 (사이에 다니는 W 날이 없으면 한 동안)
    for d in B:
        if d < lo or d > hi: continue
        if d not in days:
            if cur: cur[1] = d
            else: cur = [d, d]
        elif cur: gaps.append(cur); cur = None
    out = '' if (len(W) == 7 or noW) else wdl(W)
    per = ''
    if lo == hi: per = md(lo)
    elif lo != B[0] and hi != B[-1]: per = md(lo) + '∼' + md(hi, lo)
    elif lo != B[0]: per = md(lo) + '부터'
    elif hi != B[-1]: per = md(hi) + '까지'
    out = (out + ' ' + per).strip()
    if gaps:
        g = '・'.join(md(a) if a == b else md(a) + '∼' + md(b, a) for a, b in gaps)
        out = (out + ', ' if out else ('' if noW else '매일, ')) + '%s 제외' % g
    extra = days - set(B)
    if extra:
        e = label_wk(extra)
        out = (out + ', ' if out else ('' if noW else '매일, ')) + e
    return (W, out) if noW else out
def label(days):
    a = label_wk(days); b = label_skip(days)
    return a if b is None or len(a) <= len(b) else b
def short(nm): return nm
mm = lambda x: int(x[:2]) * 60 + int(x[2:])
hh_ = lambda x: str(int(x[:2])) + x[2:]
def rows_of(v):
    byno = collections.defaultdict(list)
    for (no, t, aa), ds in v.items(): byno[no].append((t, aa, ds))
    rows = []
    for no, vs in byno.items():
        vs.sort(key=lambda x: -len(x[2]))
        groups = []
        for t, aa, ds in vs:
            g = next((g for g in groups if abs(g[0] - mm(t)) <= 15), None)
            if g: g[1].append((t, aa, ds))
            else: groups.append((mm(t), [(t, aa, ds)]))
        for _, gs in groups:
            t, aa, ds = gs[0]
            alld = set().union(*(x[2] for x in gs))
            lab = label(alld)
            ws_ = label_skip(alld, True)                 # 요일 칸을 쓰는 목록: 요일(W)은 칸에, 주에는 날짜만
            if ws_ and lab == label_skip(alld): wm, labd = ''.join('1' if w in ws_[0] else '0' for w in range(7)), ws_[1]
            else: wm, labd = '0000000', lab                # 요일 위에 얹어 적기 어려운 편: 요일 칸은 비우고 주에 다

            for t2, a2, d2 in gs[1:]:
                same_dur = (mm(a2) - mm(t2)) % 1440 == (mm(aa) - mm(t)) % 1440
                vt = '(%s{%s}발%s)' % ((label(d2) + ' ') if label(d2) else '', hh_(t2), '' if same_dur else ' {%s}착' % hh_(a2))
                lab = (lab + ' ' if lab else '') + vt; labd = (labd + ' ' if labd else '') + vt
            rows.append((no, t, aa, lab.strip(), wm, labd.strip()))
    rows.sort(key=lambda r: (r[1], r[0]))
    return rows
fare = collections.defaultdict(list)
if len(sys.argv) > 2:
    t = json.load(open(sys.argv[2])); aps = t['airports']
    sh = lambda n: n.replace('국제공항', '').replace('공항', '').replace('포항경주', '포항')
    for f in t['flights']:
        if f.get('c'): fare[tuple(sorted((sh(aps[f['dep']]), sh(aps[f['arr']]))))].append(f['c'])
HUB = ['김포', '인천', '김해', '대구', '청주', '광주', '울산', '여수', '사천', '포항', '군산', '원주', '양양', '무안', '제주']
rank = lambda ap: HUB.index(ap) if ap in HUB else len(HUB) - 1
pairs = collections.Counter()
for (a, b), v in fl.items(): pairs[tuple(sorted((a, b)))] += sum(len(x) for x in v.values())
blocks = []
for n, ((a, b), _) in enumerate(pairs.most_common(), 1):
    first, second = (a, b) if rank(a) <= rank(b) else (b, a)
    fs_ = fare.get((a, b), [])
    blocks.append({'no': n, 'a': first, 'b': second, 'out': rows_of(fl.get((first, second), {})), 'in': rows_of(fl.get((second, first), {})),
                   'fare': [min(fs_), max(fs_)] if fs_ else None})
json.dump({'season': [S0.isoformat(), S1.isoformat()], 'pairs': blocks}, sys.stdout, ensure_ascii=False, indent=0)
print('season', S0, S1, 'pairs', len(blocks), 'rows', sum(len(b['out']) + len(b['in']) for b in blocks), file=sys.stderr)
