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
# 노선 띠에 적을 역(하행 차례. 상행은 뒤집는다). 없으면 자동
HEADS = {
    ('ktx', '경부선'): '서울 대전 동대구 부산', ('gen', '경부선'): '서울 대전 동대구 부산',
    ('ktx', '호남선'): '용산 익산 광주송정 목포', ('gen', '호남선'): '용산 서대전 익산 광주송정 목포',
    ('ktx', '전라선'): '용산 익산 전주 순천 여수엑스포', ('gen', '전라선'): '용산 서대전 익산 전주 순천 여수엑스포',
    ('ktx', '경전선'): '서울 동대구 마산 진주', ('gen', '경전선'): '부전 삼랑진 마산 진주 순천 광주송정',
    ('ktx', '동해선(서울~포항)'): '서울 대전 동대구 포항', ('ktx', '동해선(부전-강릉)'): '부전 포항 삼척 강릉',
    ('gen', '동해선'): '부전 태화강 포항 삼척 동해 강릉',
    ('ktx', '강릉선'): '서울 청량리 평창 강릉 동해',
    ('ktx', '중앙선'): '청량리 원주 안동 경주 부전', ('gen', '중앙선'): '청량리 원주 제천 영주 안동 부전',
    ('ktx', '중부내륙선'): '판교(경기) 충주 문경',
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

LINE_HANJA = {'경부선': '京釜線', '호남선': '湖南線', '전라선': '全羅線', '경전선': '慶全線', '동해선': '東海線',
              '강릉선': '江陵線', '중앙선': '中央線', '중부내륙선': '中部內陸線', '장항선': '長項線', '서해선': '西海線',
              '충북선': '忠北線', '경북선': '慶北線', '대구선': '大邱線', '영동선': '嶺東線', '태백선': '太白線',
              '목포보성선': '木浦寶城線', '교외선': '郊外線'}
# 종별 → 열차명 칸 (KTX 표에서 그냥 KTX는 비운다)
KIND = {'KTX': '', 'KTX-산천': '산천', 'KTX산천': '산천', 'KTX_산천': '산천', 'KTX-청룡': '청룡', 'KTX-이음': '이음',
        'ITX-새마을': '새마을', '새마을': '새마을호', 'ITX-마음': '마음', '무궁화': '무궁화', '누리로': '누리로'}
LBL = {  # 머리 이름 (한국어, 국한문)
    'fr': ('시발역', '始發驛'), 'no': ('열차번호', '列車番號'), 'kind': ('등급', '等級'), 'car': ('차종', '車種'),
    'to': ('종착역', '終着驛'), 'day': ('운행일', '運行日'),
}
def lbl(k): return LBL[k][1 if MIX else 0]

def clean_name(s): return re.sub(r'\((출발|도착)\)$', '', s)

def hm(t):
    t %= 1440
    return f'{t // 60}{t % 60:02d}'

def esc_txt(s):
    """칸 내용 안에서 꾸미기 표기로 읽히지 않게"""
    return s.replace('.', '..')

def vert(s):
    return f'r{esc_txt(s)}.' if s else '_'

BLACK = {'새마을', '마음', '새마을호'}      # ITX·새마을급은 검은 네모, 무궁화급·KTX 차종은 흰 네모
def badge(k):
    if not k: return '_'
    return f'BS{{k{k}.}}' if k in BLACK else f'S{{{k}}}'

def q(s):
    """공백·따옴표가 든 값은 "…"로"""
    if s == '' : return '_'
    if re.search(r'[\s"]', s): return '"' + s.replace('"', '""') + '"'
    return s


class Table:
    def __init__(self, t, hanja):
        self.cat, self.line, self.dir = t['cat'], t['line'], t['dir']
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
                if isinstance(x, str): times[i] = 'I' if a < i < b else None
            # 자정을 넘으면 1440을 더해 단조롭게
            prev, add = None, 0
            for i in idx:
                if prev is not None and times[i] + add < prev - 120: add += 1440
                times[i] += add; prev = times[i]
            trains.append(dict(tr, times=times))
        # 아무 열차도 서지 않는 역은 뺀다
        keep = [i for i in range(len(st)) if any(isinstance(tr['times'][i], int) for tr in trains)]
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
        hs = HEADS.get((self.cat, self.line))
        if hs:
            hs = hs.split()
            if self.dir == 'up': hs = hs[::-1]
            names = [self.st[i] for i in band]
            band_names = [s for s in hs if s in self.st]
        else: band_names = [self.st[i] for i in band]
        dirmark = 'k하행.' if self.dir == 'down' else 'n상행.'
        name = ('KTX ' if ktx else '') + (self.line_disp)
        span = (f'{band_names[0]} > {band_names[-1]}' if band_names[0] != band_names[-1] else ' > '.join(band_names)) if not sub else ' > '.join(sub.split(' ─ ')[::-1] if self.dir == 'up' else sub.split(' ─ '))
        L = []
        L.append(f'title "{dirmark} {name} u({span})."')
        hd = ' ― '.join(band_names)
        L.append(f'head "b{hd}."')
        L.append('headheight 34')
        if ktx: L.append(f'headstyle "fc={KTX_COLOR}"')
        L.append('cols st ad')
        L.append('rcols st')
        if MIX: L.append('rlabel 驛名')
        L.append('')
        # 머리 행
        L.append('[rows]')
        self.o0, self.d0 = self.st[o0], self.st[d0]
        odd = [tr for tr in self.trains if self.ends_of(tr) != (self.o0, self.d0)]
        has_fr = has_to = bool(odd)
        if has_fr: L.append(f'fr   {lbl("fr")}')
        L.append(f'no   {lbl("no")} fmt=N{{*}}')
        L.append(f'kind {lbl("car" if ktx else "kind")} style=va=t')
        L.append('')
        L.append('[footer]')
        if has_to: L.append(f'to   {lbl("to")}')
        has_day = any(tr['note'] for tr in self.trains)
        if has_day: L.append(f'day  {lbl("day")} style=va=t')
        L.append('')
        thru = collections.Counter()
        for tr in self.trains:
            idx = [i for i, x in enumerate(tr['times']) if isinstance(x, int)]
            for i in idx[1:-1]: thru[i] += 1
        self.split = {i for i in major if 0 < i < n - 1 and ends[i] >= max(2, 0.05 * N) and thru[i] >= 1}
        L.append('[stations]')
        rules = set()
        for alt in BRANCH.get((self.cat, self.line), []):
            for grp in alt:
                ix = [self.st.index(s) for s in grp if s in self.st]
                if ix: rules |= {min(ix), max(ix) + 1}
        rules -= {0, n}
        for i, s in enumerate(self.st):
            if i in rules: L.append('---')
            ad = '発' if i == 0 else '着' if i == n - 1 else '着発' if i in self.split else '〃'
            mk = '**' if i in self.split else '*' if i in major else ''
            nm = mk + s
            hj = self.hanja.get(s, '')
            r = f' r={q(mk + hj)}' if hj else ''
            L.append(f'{q(nm)} {ad}{r}')
        L.append('')
        L.append('[trains]')
        for tr in self.trains:
            hdr = []
            if has_fr:
                o, d = self.ends_of(tr)
                hdr.append(q(esc_txt(o)) if (o, d) != (self.o0, self.d0) else '_')
            hdr.append(tr['no'])
            k = KIND.get(tr['type'], tr['type'])
            hdr.append(q(badge(k)))
            cells = self.cells(tr)
            ft = []
            if has_to:
                o, d = self.ends_of(tr)
                ft.append(q(esc_txt(d)) if (o, d) != (self.o0, self.d0) else '_')
            if has_day: ft.append(q(vert(tr['note'])) if tr['note'] else '_')
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
            names = [('새마을', 'ITX-새마을'), ('마음', 'ITX-마음')]
            parts = [f'「{k}」은 `{full}`' for k, full in names if k in kinds]
            if parts: notes.append('등급 ' + ', '.join(parts))
        if has_day: notes.append('운행일 무표시는 매일 운행')
        if self.split: notes.append('着発을 나눈 역의 도착 시각은 그 역에서 끝나는 열차만 표시')
        L += notes
        return '\n'.join(L)

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
        """역마다 한 토큰. 달리지 않는 칸은 ‥, 着発 역은 '착,발'"""
        T = tr['times']
        idx = [i for i, x in enumerate(T) if isinstance(x, int)]
        a, b = idx[0], idx[-1]
        ends_here = True   # 표 밖으로 이어 가는 열차도 이 표에서는 끝 표시 (종착역 행에 실제 종착역)
        out, bar = [], False
        for i, x in enumerate(T):
            sp = i in self.split
            if i < a or (i > b and not (i == b + 1 and ends_here and not bar)):
                out.append('x')
            elif i > b:                                   # 종착 다음 칸: 끝 표시
                out.append('-,x' if sp else '-')
            elif isinstance(x, int):
                t = hm(x)
                if not sp: out.append(t)
                elif i == a and i == b: out.append(t)
                elif i == a: out.append(f'x,{t}')         # 여기서 떠남
                elif i == b:                              # 여기서 끝남(끝 표시는 발 줄에)
                    out.append(f'{t},-' if ends_here else f'{t},x'); bar = True
                else: out.append(f'_,{t}')                # 지나가며 섬: 도착 시각은 자료에 없음
            else:
                out.append({'v': 'v', 'x': 'x', 'I': 'i'}[x])
        res = []
        for c in out:
            if res and res[-1][0] == c and c in ('v', 'x', 'i'): res[-1][1] += 1
            else: res.append([c, 1])
        return [c if k == 1 else f'{c}*{k}' for c, k in res]


def main():
    data = json.load(open(sys.argv[1]))
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
        for cat, sheet, sub in parts:
            head = ('KTX' if cat == 'ktx' else '일반열차') + (f" ({sub.replace(' ─ ', '–')})" if sub else '')
            P.append(f'== {head} ==')
            for d in ('down', 'up'):
                t = tabs.get((cat, sheet, d))
                if not t: continue
                T = Table(t, data['hanja'])
                T.line_disp = line
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


if __name__ == '__main__':
    main()
