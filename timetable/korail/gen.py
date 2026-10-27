"""data.json(parse.py) → 위키 시각표 원문(모듈:Timetable) — JTB 꼴로 다시 짠다.

python3 gen.py data.json out/            노선마다 out/<노선>.wiki 와 out/book.json
옵션  --mix   표 머리 이름을 국한문혼용으로(列車番號 등). 기본은 한국어, 오른쪽 역명은 언제나 한자.
"""
import json, sys, os, re, statistics, collections, math

EDITION = '2026년 11월호'
PREFIX = f'연습장:시각표 {EDITION}'
MIX = '--mix' in sys.argv
KTX_COLOR = '#1d3f8a'          # KTX 표의 노선 띠·제목 표지 색

# 책에 싣는 노선 순서와, 각 노선에 들어갈 표(엑셀 시트 이름)
BOOK = [
    ('경부선',     [('ktx', '경부선', None), ('gen', '경부선', None)]),
    ('호남선',     [('ktx', '호남선', None), ('gen', '호남선', None)]),
    ('전라선',     [('ktx', '전라선', None), ('gen', '전라선', None)]),
    ('경전선',     [('ktx', '경전선', None), ('gen', '경전선', None)]),
    ('동해선',     [('ktx', '동해선(서울~포항)', '서울 ─ 포항'), ('ktx', '동해선(부전-강릉)', '부전 ─ 강릉'), ('gen', '동해선', None)]),
    ('강릉선',     [('ktx', '강릉선', None)]),
    ('중앙선',     [('ktx', '중앙선', None), ('gen', '중앙선', None)]),
    ('중부내륙선', [('ktx', '중부내륙선', None)]),
    ('장항선',     [('gen', '장항선', None)]),
    ('서해선',     [('gen', '서해선', None)]),
    ('충북선',     [('gen', '충북선', None)]),
    ('경북선',     [('gen', '경북선', None)]),
    ('대구선',     [('gen', '대구선', None)]),
    ('영동선',     [('gen', '영동선', None)]),
    ('태백선',     [('gen', '태백선', None)]),
    ('목포보성선', [('gen', '목포보성선', None)]),
    ('교외선',     [('gen', '교외선', None)]),
]
# 서는 열차가 없어도 남길 역 (하행·상행의 역을 맞춰 나란히 놓을 때 행이 어긋나지 않게. 모든 열차 통과로)
KEEP_STATIONS = {('gen', '목포보성선'): {'조성'}}
# 수서를 드나드는 열차(옛 SRT)를 따로 표로 내는 KTX 노선 (그 열차가 3분의 1 남짓 되는 곳)
SPLIT_SUSEO = {('ktx', '경부선'), ('ktx', '호남선')}
# 노선 띠에 적을 역(하행 차례. 상행은 뒤집는다). 없으면 자동
HEADS = {
    ('ktx', '경부선', '수서'): '수서 대전 동대구 부산', ('ktx', '호남선', '수서'): '수서 익산 광주송정 목포',
    ('ktx', '경부선'): '서울 대전 동대구 부산', ('gen', '경부선'): '서울 대전 동대구 부산',
    ('ktx', '호남선'): '용산 익산 광주송정 목포', ('gen', '호남선'): '용산 서대전 익산 광주송정 목포',
    ('ktx', '전라선'): '용산 익산 전주 순천 여수엑스포', ('gen', '전라선'): '용산 서대전 익산 전주 순천 여수엑스포',
    ('ktx', '경전선'): '서울 동대구 마산 진주', ('gen', '경전선'): '부전 삼랑진 마산 진주 순천 광주송정',
    ('ktx', '동해선(서울~포항)'): '서울 대전 동대구 포항', ('ktx', '동해선(부전-강릉)'): '부전 포항 삼척 강릉',
    ('gen', '동해선'): '부전 태화강 포항 삼척 동해 강릉',
    ('ktx', '강릉선'): '서울 청량리 평창 강릉 동해',
    ('ktx', '중앙선'): '청량리 원주 안동 경주 부전', ('gen', '중앙선'): '청량리 원주 제천 영주 안동 부전',
    ('ktx', '중부내륙선'): '판교 충주 문경',
    ('gen', '장항선'): '용산 천안 홍성 대천 익산', ('gen', '서해선'): '홍성 천안 서화성 홍성',
    ('gen', '충북선'): '대전 조치원 충주 제천 영주', ('gen', '경북선'): '김천 상주 점촌 영주',
    ('gen', '대구선'): '동대구 영천 경주 포항', ('gen', '영동선'): '강릉 동해 철암 영주',
    ('gen', '태백선'): '제천 영월 태백 동해', ('gen', '목포보성선'): '순천 벌교 전남장흥 목포',
    ('gen', '교외선'): '대곡 의정부',
}

# 갈래(서로 다른 길로 가는 구간). 묶음마다 [기본 갈래, 다른 갈래, …]. 빈 기본 갈래는 막다른 지선
HS_SPLIT = [['광명'], ['영등포', '수원'], ['수서', '동탄', '평택지제']]
BRANCH = {
    ('ktx', '경부선'): [HS_SPLIT, [['경주', '울산'], ['경산', '밀양', '물금', '구포']]],
    ('ktx', '경전선'): [HS_SPLIT],
    ('ktx', '동해선(서울~포항)'): [HS_SPLIT],
    ('ktx', '호남선'): [HS_SPLIT, [['공주'], ['서대전', '계룡', '논산']]],
    ('ktx', '전라선'): [HS_SPLIT, [['공주'], ['서대전', '계룡', '논산']]],
    ('ktx', '강릉선'): [[['강릉'], ['정동진', '묵호', '동해']]],
    ('gen', '경전선'): [[['부전', '사상', '구포', '화명', '물금', '원동', '삼랑진'], ['동대구', '경산', '남성현', '청도', '상동', '밀양']]],
    ('gen', '중앙선'): [[[], ['하양', '동대구']]],
    ('gen', '호남선'): [[[], ['극락강', '광주']]],
    ('gen', '충북선'): [[[], ['대전']]],
}

# 착발을 나누지 않는 역: 연결선으로 애매하게 붙는 역
NOSPLIT_ALL = {'행신'}
SPLIT_ALL = {'수서'}         # 서는 열차가 있으면 늘 착발을 나눈다
# KTX 에서 착발을 나누는 역
#  1) 여러 계통이 지나도 모든 열차가 서는 역 (열차 20편 이상인 표에서, 지나는 열차가 모두 서는 역) — 자동
#  2) 그 밖에 주요역이라 보는 역 (손으로)
KTX_MAJOR = {'수서', '오송', '익산', '광주송정', '순천', '울산', '포항', '마산', '안동', '강릉', '청량리'}

LINE_HANJA = {'경부선': '京釜線', '호남선': '湖南線', '전라선': '全羅線', '경전선': '慶全線', '동해선': '東海線',
              '강릉선': '江陵線', '중앙선': '中央線', '중부내륙선': '中部內陸線', '장항선': '長項線', '서해선': '西海線',
              '충북선': '忠北線', '경북선': '慶北線', '대구선': '大邱線', '영동선': '嶺東線', '태백선': '太白線',
              '목포보성선': '木浦寶城線', '교외선': '郊外線'}
# 종별 → 열차명 칸 (KTX 표에서 그냥 KTX는 비운다)
KIND = {'KTX': '', 'KTX-산천': '산천', 'KTX산천': '산천', 'KTX_산천': '산천', 'KTX-청룡': '청룡', 'KTX-이음': '이음',
        'ITX-새마을': '새마을', '새마을': '새마을', 'ITX-마음': '마음', '무궁화': '무궁화', '누리로': '누리로'}
LBL = {  # 머리 이름 (한국어, 국한문)
    'fr': ('시발역', '始發驛'), 'no': ('열차번호', '列車番號'), 'kind': ('등급', '等級'), 'car': ('차종', '車種'),
    'to': ('종착역', '終着驛'), 'day': ('비고', '備考'),   # 운행일 등. 인쇄에서는 쪽의 남는 자리를 이 행이 받는다
    'days': ('운행일주의', '運行日注意'),                         # 기호(◆◇)로 적는 운행일: 한 줄. 그 밑에 빈 비고 행
}
def lbl(k): return LBL[k][1 if MIX else 0]

# 역 이름 고침 (위키에서 고친 것): 원본 이름 → 표에 쓸 이름. 한자도 함께
RENAME = {'판교(경기)': '판교', '진부(오대산)': '진부'}
RENAME_HANJA = {'진부': '珍富', '여수엑스포': '麗水엑스포', '민둥산': '민둥山'}   # 반만 한자인 이름은 한자 부분만
def clean_name(s):
    s = re.sub(r'\((출발|도착)\)$', '', s)
    return RENAME.get(s, s)

def hm(t):
    t %= 1440
    return f'{t // 60}{t % 60:02d}'

def esc_txt(s):
    """칸 내용 안에서 꾸미기 표기로 읽히지 않게"""
    return s.replace('.', '..')

def vert(s):
    return f'r{esc_txt(s)}.' if s else '_'

WEEK = '월화수목금토일'
def day_range(s):
    """이어지는 요일 셋 이상은 범위로: 금토일 → 금∼일, 월화수목금 → 월∼금 (주를 넘어가도: 금토일월 → 금∼월)"""
    if s.endswith(' 경유'): return s[:-3] + '/경유'        # 「중앙선/경유」 두 줄 세로쓰기
    if any(ch not in WEEK for ch in s): return s
    if len(s) >= 3:
        k = WEEK.index(s[0])
        if all(WEEK[(k + i) % 7] == ch for i, ch in enumerate(s)): s = f'{s[0]}∼{s[-1]}'
    return s + '/운행'                                     # 요일 | 운행 두 줄

# 따로 조사한 도착 시각 {(열차번호, 역): 분}. arrivals.json 이 있으면 읽는다
ARR = {}
NEED = set()   # 도착 시각을 더 조사해야 하는 (열차번호, 시발역, 역)
if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'arrivals.json')):
    ARR = {tuple(k.split('@')): v for k, v in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'arrivals.json'))).items()}

def grade(t): return 'KTX' if t.startswith('KTX') else t
DWELL = {}   # (등급, 역) → 가장 흔한 정차 시간(분). main 에서 ARR 로 채운다

BLACK = {'ITX-새마을', 'ITX-마음'}      # ITX는 검은 네모, 새마을호·무궁화·누리로·KTX 차종은 흰 네모
def badge(k, typ=''):
    if not k: return '_'
    return f'BS{{k{k}.}}' if typ in BLACK else f'S{{{k}}}'

def q(s):
    """공백·따옴표가 든 값은 "…"로"""
    if s == '' : return '_'
    if re.search(r'[\s"]', s): return '"' + s.replace('"', '""') + '"'
    return s


class Table:
    def __init__(self, t, hanja):
        self.cat, self.line, self.dir = t['cat'], t['line'], t['dir']
        self.variant = t.get('variant')
        st = [clean_name(s) for s in t['stations']]
        self.hanja = hanja
        trains = []
        for tr in t['trains']:
            times = list(tr['times'])
            idx = [i for i, x in enumerate(times) if isinstance(x, int)]
            if not idx: continue
            a, b = idx[0], idx[-1]
            # 글자 칸(… 경유): 앞뒤 끝이면 지우고, 사이에 끼면 다른 선 경유(║)
            for i, x in enumerate(times):
                if isinstance(x, str):
                    if i < a: tr['via_in'], tr['via_in_at'] = x, i     # 표 밖 다른 선에서 들어옴 (…선 경유). 그 줄이 갈림역
                    if i > b and 'via_out' not in tr: tr['via_out'], tr['via_out_at'] = x, i   # 표 밖 다른 선으로 나감
                    times[i] = 'I' if a < i < b else None
            # 자정을 넘으면 1440을 더해 단조롭게
            prev, add = None, 0
            for i in idx:
                if prev is not None and times[i] + add < prev - 120: add += 1440
                times[i] += add; prev = times[i]
            trains.append(dict(tr, times=times))
        # 아무 열차도 서지 않는 역은 뺀다
        kept = KEEP_STATIONS.get((self.cat, self.line), set())
        keep = [i for i in range(len(st)) if st[i] in kept or any(isinstance(tr['times'][i], int) for tr in trains)]
        self.st = [st[i] for i in keep]
        for tr in trains: tr['times'] = [tr['times'][i] for i in keep]
        self.trains = trains
        self.infer()
        self.sort()

    # ── 통과(⇂)와 비경유(‥) 가리기 ──
    def infer(self):
        n = len(self.st)
        E = collections.Counter()
        for tr in self.trains:
            idx = [i for i, x in enumerate(tr['times']) if isinstance(x, int)]
            for u, v in zip(idx, idx[1:]):
                if not any(tr['times'][k] == 'I' for k in range(u + 1, v)): E[(u, v)] += 1
        out = collections.defaultdict(list)
        for (u, v), c in E.items(): out[u].append((v, c))

        # 더 잘게 나눌 수 있는 간선(사이에 서는 역이 있는 구간)은 빼고, 이웃한 역 사이의 간선만 남긴다
        elem = collections.defaultdict(list)
        for (u, v), c in E.items():
            if not any(E.get((u, w)) and E.get((w, v)) for w in range(u + 1, v)): elem[u].append((v, c))

        def best_path(a, b):
            """a→b 사이 이웃 간선으로 이은 길 가운데 가장 붐비는(병목이 큰) 길. 없으면 None"""
            best = {a: (math.inf, 0, None)}
            for u in range(a, b):
                if u not in best: continue
                bn, ln, _ = best[u]
                for v, c in elem[u]:
                    if v > b: continue
                    cand = (min(bn, c), ln + 1, u)
                    if v not in best or cand[:2] > best[v][:2]: best[v] = cand
            if b not in best: return None
            path, x = set(), b
            while x is not None: path.add(x); x = best[x][2]
            return path

        # 두 역에 함께 서는 열차가 있는가 (같은 길 위에 있다는 표지)
        stopsets = [frozenset(i for i, x in enumerate(tr['times']) if isinstance(x, int)) for tr in self.trains]
        co = [[False] * n for _ in range(n)]
        for S in stopsets:
            for i in S:
                for j in S: co[i][j] = True
        # 갈래: BRANCH 의 갈래 묶음마다, 이 열차가 서는 갈래만 지나고(⇂) 나머지 갈래는 지나지 않는다(‥).
        # 어느 갈래에도 서지 않으면 첫 갈래(빈 갈래면 모두 ‥: 막다른 지선)
        alts = [[[self.st.index(s) for s in grp if s in self.st] for grp in alt] for alt in BRANCH.get((self.cat, self.line), [])]
        for tr, S in zip(self.trains, stopsets):
            T = tr['times']
            off = set()
            for alt in alts:
                used = [k for k, grp in enumerate(alt) if any(i in S for i in grp)] or [0]
                for k, grp in enumerate(alt):
                    if k not in used: off |= set(grp)
            idx = sorted(S)
            for u, v in zip(idx, idx[1:]):
                if v == u + 1 or any(T[k] == 'I' for k in range(u + 1, v)):
                    for k in range(u + 1, v):
                        if T[k] is None: T[k] = 'I'
                    continue
                for k in range(u + 1, v): T[k] = 'I' if k in off else 'v'   # 다른 갈래를 달리는 동안은 ║

    # ── 기준 시각으로 줄 세우기 ──
    def sort(self):
        n = len(self.st)
        off = [None] * n
        off[0] = 0
        for s in range(1, n):
            ds = []
            for tr in self.trains:
                T = tr['times']
                if not isinstance(T[s], int): continue
                p = next((k for k in range(s - 1, -1, -1) if isinstance(T[k], int) and off[k] is not None), None)
                if p is not None: ds.append(T[s] - T[p] + off[p])
            off[s] = statistics.median(ds) if ds else None
        for tr in self.trains:
            T = tr['times']
            r = [T[k] - off[k] for k in range(n) if isinstance(T[k], int) and off[k] is not None]
            tr['ref'] = statistics.median(r) if r else 9999
        self.trains.sort(key=lambda tr: (tr['ref'], tr['no']))

    # ── 원문 쓰기 ──
    def stops(self, i): return sum(isinstance(tr['times'][i], int) for tr in self.trains)

    def wiki(self, sub=None):
        n, ktx = len(self.st), self.cat == 'ktx'
        N = len(self.trains)
        first, last = self.st[0], self.st[-1]
        ends = collections.Counter()
        for tr in self.trains:
            idx = [i for i, x in enumerate(tr['times']) if isinstance(x, int)]
            ends[idx[0]] += 1; ends[idx[-1]] += 1
        busy = [i for i in range(n) if self.stops(i) >= 0.75 * N]
        if len(busy) > 0.4 * n: busy = []
        major = [i for i in range(n) if i in busy or ends[i] >= max(3, 0.15 * N)]
        major = sorted(set(major) | {0, n - 1})
        # 대표 시발·종착: 가장 많은 열차가 떠나고 닿는 역
        o_c = collections.Counter(); d_c = collections.Counter()
        for tr in self.trains:
            idx = [i for i, x in enumerate(tr['times']) if isinstance(x, int)]
            o_c[idx[0]] += 1; d_c[idx[-1]] += 1
        o0, d0 = o_c.most_common(1)[0][0], d_c.most_common(1)[0][0]
        mid = [i for i in range(o0 + 1, d0) if self.stops(i) >= 0.6 * N]
        if len(mid) > 3: mid = [mid[round(k * (len(mid) - 1) / 2)] for k in (0, 1, 2)]
        # 노선 띠: 주요 역을 많아야 다섯
        band = list(dict.fromkeys([o0] + mid + [d0]))
        hs = HEADS.get((self.cat, self.line, self.variant)) or HEADS.get((self.cat, self.line))
        if hs:
            hs = hs.split()
            if self.dir == 'up': hs = hs[::-1]
            names = [self.st[i] for i in band]
            band_names = [s for s in hs if s in self.st]
        else: band_names = [self.st[i] for i in band]
        dirmark = 'k하행.' if self.dir == 'down' else 'n상행.'
        vlab = (' 수서발' if self.dir == 'down' else ' 수서행') if self.variant == '수서' else ''
        name = ('KTX ' if ktx else '') + (self.line_disp) + vlab
        span = (f'{band_names[0]} > {band_names[-1]}' if band_names[0] != band_names[-1] else ' > '.join(band_names)) if not sub else ' > '.join(sub.split(' ─ ')[::-1] if self.dir == 'up' else sub.split(' ─ '))
        L = []
        L.append(f'title "{dirmark} {name} u({span})."')
        hd = ' ― '.join(band_names)
        # 노선 띠: 왼쪽에 방향·노선(인쇄에서 표마다 무엇인지), 가운데에 주요 역
        dirw = '하행' if self.dir == 'down' else '상행'
        # 방향은 노선 이름 뒤에 명조로
        L.append(f'headl "b' + ('`KTX` ' if ktx else '') + f'{self.line_disp}{vlab}. 〔{dirw}〕"')
        L.append(f'head "（{hd}）"')          # 구간: 명조로 괄호에
        L.append('headheight 48')
        if ktx: L.append(f'headstyle "fc={KTX_COLOR}"')
        L.append('cols st ad')
        L.append('rcols st')
        if MIX: L.append('rlabel 驛名')
        L.append('')
        # 머리 행
        L.append('[rows]')
        self.o0, self.d0 = self.st[o0], self.st[d0]
        has_fr = has_to = True
        # 등급(KTX는 차종) 표지 바로 밑에 열차번호, 두 행은 이름 칸을 합쳐 사이 선 없이. 그 밑에 시발역
        L.append(f'kind {lbl("no")} style=va=b r={LBL["no"][1]}')
        L.append(f'no   ^ fmt=N{{*}} style=va=t')
        if has_fr: L.append(f'fr   {lbl("fr")} r={LBL["fr"][1]}')
        L.append('')
        L.append('[footer]')
        if has_to: L.append(f'to   {lbl("to")} r={LBL["to"][1]}')
        has_day = any(tr['note'] for tr in self.trains)
        days = {tr['note'] for tr in self.trains if tr['note']}
        self.daysym = {'월화수목금': '◆', '토일': '◇'} if days and days <= {'월화수목금', '토일'} else None
        # 모든 표의 끝은 비고 행 (인쇄에서 쪽의 남는 자리를 받는다). 기호로 적는 운행일은 그 위에 한 줄로
        self.rem_empty = not has_day or bool(self.daysym)
        if has_day and self.daysym: L.append(f'days {lbl("days")} r={LBL["days"][1]}')
        elif has_day: L.append(f'day  {lbl("day")} r={LBL["day"][1]} style=va=t')
        if self.rem_empty: L.append(f'rem  {lbl("day")} r={LBL["day"][1]} style=va=t')
        L.append('')
        thru = collections.Counter()
        for tr in self.trains:
            idx = [i for i, x in enumerate(tr['times']) if isinstance(x, int)]
            for i in idx[1:-1]: thru[i] += 1
        # 중간에서 떠나거나 끝나는 열차가 하나라도 있고 지나가며 서는 열차도 있는 역은 모두 착발을 나눈다
        self.split = {i for i in range(1, n - 1) if ends[i] >= 1 and thru[i] >= 1}
        # 표의 첫 역·끝 역: 그 역에서 떠나거나 닿는 열차가 여럿이면 나눈다
        first_n = sum(1 for tr in self.trains if next(i for i, x in enumerate(tr['times']) if isinstance(x, int)) == 0)
        last_n = sum(1 for tr in self.trains if max(i for i, x in enumerate(tr['times']) if isinstance(x, int)) == n - 1)
        if first_n >= max(2, 0.1 * N): self.split.add(0)
        if last_n >= max(2, 0.1 * N): self.split.add(n - 1)
        # 연결선으로 붙는 역(중앙선·강릉선 KTX의 서울 등): 그 역에서 떠난 열차가 바로 다음에 서는 역(닿는 열차는 바로 앞 역)이
        # 착발을 나눈 역이면, 붙는 역은 한 줄로 둔다. 연결선 끝 역이 나뉘지 않았으면(부전·광주송정 등) 그대로 나눈다
        def junction(c):
            nxt = collections.Counter()
            for tr in self.trains:
                idx = [i for i, x in enumerate(tr['times']) if isinstance(x, int)]
                if idx[0] == c and len(idx) > 1: nxt[idx[1]] += 1
                if idx[-1] == c and len(idx) > 1: nxt[idx[-2]] += 1
            return nxt.most_common(1)[0][0] if nxt else None
        self.junc = set()        # 연결선으로 붙는 종착역: 착발은 나누지 않지만 주요역(*)으로
        for c in sorted(self.split, key=lambda i: min(i, n - 1 - i)):
            j = junction(c)
            if j is not None and j in self.split and j != c: self.split.discard(c); self.junc.add(self.st[c])
        if ktx:
            for i, s in enumerate(self.st):
                trav = sum(1 for tr in self.trains if isinstance(tr['times'][i], int) or tr['times'][i] == 'v')
                stop = self.stops(i)
                if N >= 20 and trav and stop == trav and stop >= 0.3 * N:      # 지나는 열차가 모두 서는 역만 (직관적 주요역 KTX_MAJOR 은 인쇄 쪽수 때문에 한 줄로)
                    self.split.add(i)
        self.split -= {i for i, s in enumerate(self.st) if s in NOSPLIT_ALL}
        self.split |= {i for i, s in enumerate(self.st) if s in SPLIT_ALL and self.stops(i)}
        # 상행·하행이 같은 주요역·착발역을 쓰도록 main 에서 두 방향을 모아 정한 값(shared)으로 덮어쓴다
        self.cand = {self.st[i]: (self.stops(i) + ends[i]) / N for i in major}
        self.split_names = {self.st[i] for i in self.split}
        sh = getattr(self, 'shared', None)
        if sh:
            self.split = {i for i, s in enumerate(self.st) if s in sh['split']}
            major = sorted({i for i, s in enumerate(self.st) if s in sh['major']} | self.split)
        L.append('[stations]')
        rules = set()
        for alt in BRANCH.get((self.cat, self.line), []):
            for grp in alt:
                ix = [self.st.index(s) for s in grp if s in self.st]
                if ix: rules |= {min(ix), max(ix) + 1}
        rules -= {0, n}
        for i, s in enumerate(self.st):
            if i in rules: L.append('---')
            ad = '着発' if i in self.split else '発' if i == 0 else '着' if i == n - 1 else '〃'
            mk = '**' if i in self.split else '*' if (i in major or s in self.junc) else ''
            nm = mk + s
            hj = RENAME_HANJA.get(s) or self.hanja.get(s) or self.hanja.get(next((k for k, v in RENAME.items() if v == s), ''), '')
            r = f' r={q(mk + hj)}' if hj else ''
            L.append(f'{q(nm)} {ad}{r}')
        L.append('')
        L.append('[trains]')
        for tr in self.trains:
            k = KIND.get(tr['type'], tr['type'])
            hdr = [q(badge(k, tr['type'])), tr['no']]
            if has_fr:
                o, d = self.ends_of(tr)
                hdr.append(q(f'{esc_txt(o)}/{hm(self.end_times(tr)[0])}'))
            cells = self.cells(tr)
            ft = []
            if has_to:
                o, d = self.ends_of(tr)
                ft.append(q(f'{esc_txt(d)}/{hm(self.end_times(tr)[1])}'))
            if has_day:
                nt = tr['note']
                ft.append('_' if not nt else self.daysym[nt] if self.daysym else q(vert(day_range(nt))))
            if self.rem_empty: ft.append('_')
            line = ' '.join(hdr) + ' : ' + ' '.join(cells)
            if ft: line += ' : ' + ' '.join(ft)
            L.append(line)
        L.append('')
        L.append('[notes]')
        notes = []
        kinds = [KIND.get(tr['type'], tr['type']) for tr in self.trains]
        if ktx:
            names = [('산천', 'KTX-산천'), ('청룡', 'KTX-청룡'), ('이음', 'KTX-이음')]
            parts = ['무표시는 KTX'] + [f'「{k}」은 `{full}`' for k, full in names if k in kinds]
            notes.append('차종 ' + ', '.join(parts))
        else:
            types = {tr['type'] for tr in self.trains}
            parts = []
            if 'ITX-새마을' in types: parts.append('BS{k새마을.}은 `ITX-새마을`')
            if '새마을' in types: parts.append('S{새마을}은 새마을호')
            if 'ITX-마음' in types: parts.append('BS{k마음.}은 `ITX-마음`')
            if parts: notes.append('등급 ' + ', '.join(parts))
        if has_day:   # 운행일 관련은 한 줄로
            dn = []
            if self.daysym:
                used = {tr['note'] for tr in self.trains}
                if '월화수목금' in used: dn.append('◆ 평일(월∼금) 운행')
                if '토일' in used: dn.append('◇ 토·일 운행')
            dn.append(('운행일주의' if self.daysym else '비고') + ' 무표시는 매일 운행')
            notes.append(', '.join(dn))
        if any(c.startswith('_,') for tr in self.trains for c in self.cells(tr)):
            notes.append('着発 역의 빈 도착 시각은 자료 없음')
        L += notes
        return '\n'.join(L)

    def daysym_pre(self):
        days = {tr['note'] for tr in self.trains if tr['note']}
        return bool(days) and days <= {'월화수목금', '토일'}

    def end_times(self, tr):
        """시발역 출발·종착역 도착 시각 (표 밖이어도). 자료에 없으면 표 안의 첫·끝 정차 시각"""
        idx = [i for i, x in enumerate(tr['times']) if isinstance(x, int)]
        f, t = tr.get('fromT'), tr.get('toT')
        return (f if isinstance(f, int) else tr['times'][idx[0]], t if isinstance(t, int) else tr['times'][idx[-1]])

    def ends_of(self, tr):
        """실제 시발·종착역 (표 밖이어도). 자료에 없으면 표 안의 첫·끝 정차역"""
        idx = [i for i, x in enumerate(tr['times']) if isinstance(x, int)]
        return (clean_name(tr.get('from') or '') or self.st[idx[0]], clean_name(tr.get('to') or '') or self.st[idx[-1]])

    def origin_out(self, tr):
        """표 밖에서 오는 열차의 시발역 (없으면 '')"""
        f = clean_name(tr.get('from') or '')
        if not f: return ''
        idx = [i for i, x in enumerate(tr['times']) if isinstance(x, int)]
        return '' if self.st[idx[0]] == f else f

    def dest_out(self, tr):
        t = clean_name(tr.get('to') or '')
        if not t: return ''
        idx = [i for i, x in enumerate(tr['times']) if isinstance(x, int)]
        return '' if self.st[idx[-1]] == t else t

    def cells(self, tr):
        """역마다 한 토큰. 달리지 않는 칸은 ‥, 着発 역은 '착,발'.
        표 밖 다른 선으로 나가거나 들어오는 열차는 남는 칸을 합쳐 세로 주석(어느 선 경유, 어디 몇 시 착·발)을 단다"""
        T = tr['times']
        n = len(T)
        idx = [i for i, x in enumerate(T) if isinstance(x, int)]
        a, b = idx[0], idx[-1]
        o, d = self.ends_of(tr)
        phys = lambda k: 2 if k in self.split else 1
        out, bar = [], False
        # 아래쪽: 표 밖으로 나가는 열차의 주석
        tail = None
        tail_at = tr.get('via_out_at', b + 1)          # 갈림역 줄부터 주석 자리. 그 앞 역들은 지나감
        head_at = tr.get('via_in_at', a - 1)
        def note_slots(k0, k1, via, va):
            """역 k0..k1 의 칸(착발역은 두 칸)을 모아 가운데에 (…선 경유) 세로 한 줄, 나머지는 ‥ → {역: 토큰}"""
            slots = [(k, p) for k in range(k0, k1 + 1) for p in range(phys(k))]
            if len(slots) < 2: return None
            text = via.replace(' ', '')
            text = text.replace('경유', ' 경유')
            need = -(-(len(text) + 2) * 10 // 12)          # 글자(괄호 포함) 1em, 행 1.2em
            if need > len(slots): need = 0                   # 자리가 모자라면 주석 없이 ║ 만 (행이 굵어지지 않게)
            s0 = (len(slots) - need) // 2
            parts = collections.defaultdict(list)
            for j, (k, p) in enumerate(slots):
                if need and j == s0: parts[k].append(q(f'^{need} va={va}; VP{{{esc_txt(text)}}}'))
                elif need and s0 < j < s0 + need: parts[k].append('!')
                else: parts[k].append('i')                   # 다른 선을 달림
            return {k: ','.join(v) if len(v) > 1 and v != ['i', 'i'] else v[0] for k, v in parts.items()}
        tail = note_slots(tail_at, n - 1, tr['via_out'], 'm') if d != self.st[b] and tr.get('via_out') and tail_at < n else None
        head = note_slots(0, head_at, tr['via_in'], 'm') if o != self.st[a] and tr.get('via_in') and head_at >= 0 else None
        for i, x in enumerate(T):
            sp = i in self.split
            if head and i <= head_at:
                out.append(head[i])
            elif head and i < a:
                out.append('v')
            elif tail and i >= tail_at:
                out.append(tail[i])
            elif tail and i > b:
                out.append('v')
            elif i < a or i > b + 1 or (i == b + 1 and bar):
                out.append('x')
            elif i == b + 1:                              # 마지막 정차역 다음 칸: 끝 표시
                out.append('-,x' if sp else '-')
            elif isinstance(x, int):
                t = hm(x)
                if not sp: out.append(t); continue
                st = self.st[i]
                arr = ARR.get((tr['no'], st))             # 따로 조사한 도착 시각 (TAGO 열차정보, 시발 시각이 맞는 것만)
                if arr is None or not 0 <= (x - arr) % 1440 <= 15:
                    w = DWELL.get((grade(tr['type']), st))   # 없으면 같은 등급·같은 역의 정차 시간으로
                    arr = x - w if w is not None else None
                arr = hm(arr) if arr is not None else '_'
                if (i == a or x == self.end_times(tr)[0]) and o == st: arr = 'x'   # 여기서 떠나는 열차: 착은 ‥ (광주처럼 역 차례가 거꾸로인 지선도)
                if i == b and d == st:                    # 여기서 끝나는 열차: 착에 시각, 발에 끝 표시
                    out.append(f'{t},-'); bar = True
                else:
                    if arr == '_': NEED.add((tr['no'], o, st, self.end_times(tr)[0]))
                    out.append(f'{arr},{t}')
            else:
                out.append({'v': 'v', 'x': 'x', 'I': 'i'}[x])
        res = []
        for c in out:
            if res and res[-1][0] == c and c in ('v', 'x', 'i', '!'): res[-1][1] += 1
            else: res.append([c, 1])
        return [c if k == 1 else f'{c}*{k}' for c, k in res]


def share(ts):
    """두 방향 표에서 주요역·착발역을 하나로: 착발역은 합집합, 주요역은 이웃한 두 역이 함께 굵지 않게 점수 높은 것부터"""
    order = next((t.st for t in ts if t.dir == 'down'), ts[0].st)
    pos = {s: k for k, s in enumerate(order)}
    score = collections.Counter()
    for t in ts:
        for s, v in t.cand.items(): score[s] += v
    split = set().union(*(t.split_names for t in ts))
    fixed = set(split)
    chosen = set(fixed)
    for s, v in score.most_common():
        if s in chosen or s not in pos: continue
        k = pos[s]
        if any(0 <= k + dk < len(order) and order[k + dk] in chosen for dk in (-1, 1)): continue
        chosen.add(s)
    return {'split': split, 'major': chosen}


def main():
    data = json.load(open(sys.argv[1]))
    c = collections.defaultdict(collections.Counter)
    for t in data['tables']:
        for tr in t['trains']:
            for s, x in zip(t['stations'], tr['times']):
                s = clean_name(s)
                if isinstance(x, int) and (tr['no'], s) in ARR and 0 <= (x - ARR[(tr['no'], s)]) % 1440 <= 15:
                    c[(grade(tr['type']), s)][(x - ARR[(tr['no'], s)]) % 1440] += 1
    DWELL.update({k: v.most_common(1)[0][0] for k, v in c.items()})
    outdir = sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    tabs = {(t['cat'], t['line'], t['dir']): t for t in data['tables']}
    book_items = []
    index = []
    for line, parts in BOOK:
        P = [f'{{{{시각표테마}}}}', f'{{{{상위문서|{PREFIX}}}}}',
             f"'''{line}'''({LINE_HANJA[line]}) 시각표. {EDITION}(가상), 코레일 2026년 10월 발표 자료 기준.", '']
        book_items.append({'type': 'divider', 'text': line, 'sub': '', 'inline': True})
        idx = 0
        title = f'{PREFIX}/{line}'
        expanded = []
        for cat, sheet, sub in parts:
            if (cat, sheet) in SPLIT_SUSEO:
                expanded += [(cat, sheet, sub, None), (cat, sheet, sub, '수서')]
            else: expanded.append((cat, sheet, sub, None))
        for cat, sheet, sub, variant in expanded:
            head = ('KTX' if cat == 'ktx' else '일반열차') + (f" ({sub.replace(' ─ ', '–')})" if sub else '') + (' (수서 발착)' if variant == '수서' else '')
            P.append(f'== {head} ==')
            pair = {}
            for d in ('down', 'up'):
                t = tabs.get((cat, sheet, d))
                if not t: continue
                if (cat, sheet) in SPLIT_SUSEO:
                    k = next(i for i, x in enumerate(t['stations']) if clean_name(x) == '수서')
                    t = dict(t, variant=variant, trains=[tr for tr in t['trains'] if isinstance(tr['times'][k], int) == (variant == '수서')])
                T = Table(t, data['hanja']); T.line_disp = line
                T.wiki(sub); pair[d] = T
            shared = share(list(pair.values()))
            for d in ('down', 'up'):
                if d not in pair: continue
                T = pair[d]; T.shared = shared
                P.append(f"=== {'하행' if d == 'down' else '상행'} ===")
                P.append('{{#invoke:Timetable|main|data=')
                P.append(T.wiki(sub))
                P.append('}}')
                P.append('')
                book_items.append({'type': 'table', 'title': title, 'idx': idx,
                                   'label': f"{line} {head} {'하행' if d == 'down' else '상행'}", 'fit': 'split', 'scale': 100})
                idx += 1
                print(f'{line:6} {head:16} {d:4} {len(T.st):3} st {len(T.trains):4} tr')
        open(os.path.join(outdir, f'{line}.wiki'), 'w').write('\n'.join(P) + '\n')
        index.append(line)
    # 목차 문서
    I = ['{{시각표테마}}', f'시각표 {EDITION}(가상). 코레일 2026년 10월 발표 자료(일반열차·고속열차) 기준, JTB 시각표 꼴로 재구성.', '',
         '* 시각은 분 단위(초 버림)', '* 오른쪽 역명은 한자', '', '== 노선 ==']
    I += [f'* [[{PREFIX}/{l}|{l}]]' for l in index]
    open(os.path.join(outdir, '_index.wiki'), 'w').write('\n'.join(I) + '\n')
    json.dump(book_items, open(os.path.join(outdir, 'items.json'), 'w'), ensure_ascii=False, indent=1)
    json.dump(sorted(NEED), open(os.path.join(outdir, 'need-arrivals.json'), 'w'), ensure_ascii=False)
    print(len(NEED), 'arrivals to look up,', len({(o, s) for _, o, s, _ in NEED}), 'station pairs')


if __name__ == '__main__':
    main()
