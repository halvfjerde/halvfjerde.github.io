"""data.json(parse.py) → 위키 시각표 원문(모듈:Timetable) — JTB 꼴로 다시 짠다.

python3 gen.py data.json out/            노선마다 out/<노선>.wiki 와 out/book.json
옵션  --mix   표 머리 이름을 국한문혼용으로(列車番號 등). 기본은 한국어, 오른쪽 역명은 언제나 한자.
"""
import json, sys, os, re, statistics, collections, math

EDITION = '2026년 11월호'
PREFIX = f'연습장:시각표 {EDITION}'
MIX = '--mix' in sys.argv
KTX_COLOR = '#0a5fe0'          # KTX 표의 노선 띠·제목 표지 색

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
    ('영동선',     [('gen', '영동선', None)]),
    ('태백선',     [('gen', '태백선', None)]),
    ('목포보성선', [('gen', '목포보성선', None)]),
    ('교외선',     [('gen', '교외선', None)]),
]
# 관광열차 (tour.json, parse_tour.py): 따로 한 문서. 표마다 같은 길을 달리는 관광열차를
TOUR_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tour.json')
TOUR = json.load(open(TOUR_JSON)) if os.path.exists(TOUR_JSON) else None
if TOUR: BOOK.append(('관광열차', [('tour', t['line'], None) for t in TOUR['tables'] if t['dir'] == 'down']))
# 관광열차 표는 상하행을 한 표에 (가운데 역명, 왼쪽 하행·오른쪽 상행). 열차 옆 주석 열 (표 이름 → 세로 두 줄)
TOUR_COLNOTE = {}
TOUR_HEADR = {'정선아리랑': '토·일과 2, 7, 12, 17, 22, 27일 운행'}      # 표 머리띠 오른쪽에 적는 주      # 칸 문법 그대로 (세로 덩어리를 위에서 아래로)
# 노선마다 재래선(일반열차) 표를 먼저, KTX 는 그 뒤에
BOOK = [(line, sorted(parts, key=lambda p: 0 if p[0] == 'gen' else 1)) for line, parts in BOOK]
# 재래선과 같은 선로(정차역이 거의 같은)를 달리는 KTX 는 재래선 표에 합친다: 열차는 파란 글씨, 시각은 굵게
# 고속선에서 갈라지는 KTX(경전선·전라선·동해선 서울–포항)는 갈림역부터만 남기고 재래선 표에 (고속선 구간은 고속철도 표에)
MERGE_KTX = {('ktx', '동해선(부전-강릉)'): ('gen', '동해선'), ('ktx', '중앙선'): ('gen', '중앙선'),
             ('ktx', '경전선'): ('gen', '경전선'), ('ktx', '전라선'): ('gen', '전라선'), ('ktx', '동해선(서울~포항)'): ('gen', '동해선')}
MERGE_INTO = {}
for _k, _g in MERGE_KTX.items(): MERGE_INTO.setdefault(_g, []).append(_k)
VIA_HSR = {('ktx', '경전선'): '경부고속선', ('ktx', '전라선'): '호남고속선', ('ktx', '동해선(서울~포항)'): '경부고속선'}
KTX_STYLE = ['style=fc=' + KTX_COLOR, 'tstyle=fw=b']
SUSEO_COLOR = '#d1007a'         # 수서 발착 열차(옛 SRT)는 자주색

# 다른 재래선 표를 합친다 (대구선 → 동해선: 동대구–아화를 경주 앞(상행은 뒤)에 갈래로). 같은 번호 열차는 시각을 채우고,
# 경주에서 방향을 바꾸는 열차(동대구–부전)는 두 토막으로 (갈래 쪽 토막은 반대 방향 표에. 「…선 경유」로 잇는다)
MERGE_GEN = {('gen', '대구선'): ('gen', '동해선')}
LINE_DISP = {('gen', '동해선'): '동해선・대구선'}      # 합친 표의 노선 이름 (띠·제목·인쇄의 바깥 표지)
MERGE_GEN_INTO = {}
for _k, _g in MERGE_GEN.items(): MERGE_GEN_INTO.setdefault(_g, []).append(_k)

def merge_gen(h, g):
    hn = [clean_name(x) for x in h['stations']]
    gn = [clean_name(x) for x in g['stations']]
    extra = [x for x in gn if x not in hn]
    if extra:
        j0 = gn.index(extra[0])
        nxt = next((x for x in gn[j0:] if x in hn), None)
        prv = next((x for x in reversed(gn[:j0]) if x in hn), None)
        pos = hn.index(nxt) if nxt else hn.index(prv) + 1
        st = hn[:pos] + extra + hn[pos:]
    else: st = hn
    def remap(tr, names):
        p_ = {x: i for i, x in enumerate(names)}
        return dict(tr, times=[tr['times'][p_[x]] if x in p_ else None for x in st])
    trs = [remap(tr, hn) for tr in h['trains']]
    by = {tr['no']: tr for tr in trs}
    ex = {st.index(x) for x in extra}
    for tr in g['trains']:
        r = remap(tr, gn)
        if not any(isinstance(r['times'][i], int) for i in ex): continue      # 갈래에 서지 않는 열차는 이미 h 에
        if r['no'] in by:                                                     # 지나는 열차: 갈래 쪽 시각을 채우고 「대구선 경유」를 지운다
            hh = by[r['no']]
            hh['times'] = [x if isinstance(x, int) else r['times'][i] if i in ex and isinstance(r['times'][i], int) else None if isinstance(x, str) else x
                           for i, x in enumerate(hh['times'])]
            for k in ('from', 'to', 'fromT', 'toT'):
                if r.get(k) and not hh.get(k): hh[k] = r[k]
        else: trs.append(r)
    return dict(h, stations=st, trains=trs)

def combine_both(Td, Tu, sub, name):
    """하행 표·상행 표를 한 표로 (모듈의 both: 가운데 역명, 왼쪽 하행 위에서부터·오른쪽 상행 밑에서부터)"""
    a, b = Td.wiki(sub).split('\n'), Tu.wiki(sub).split('\n')
    assert Td.st == Tu.st[::-1], (Td.st, Tu.st)
    def sections(lines):
        out, cur = {'': []}, ''
        for l in lines:
            m = re.fullmatch(r'\[(\w+(?: \w+)?)\]', l.strip())
            if m: cur = m.group(1); out[cur] = []; continue
            out[cur].append(l)
        return out
    A, B = sections(a), sections(b)
    assert [l for l in A['footer'] if l.strip()] == [l for l in B['footer'] if l.strip()], (A['footer'], B['footer'])
    disp = name.replace('(', ' (')
    head = [f'title "{disp}"', f'headl "b{disp}"'] + ([f'headr "{TOUR_HEADR[name]}"'] if name in TOUR_HEADR else []) + ['cols ad st ad', 'both 1']
    head += [l for l in A[''] if l.strip() and not re.match(r'(title|headl|headr|head|headheight|cols|rcols)\b', l)]
    nh = len([l for l in A['rows'] if l.strip()])
    nf = len([l for l in A['footer'] if l.strip()])
    def notecol(T, text, up=False):
        # 상행 열은 모듈이 행을 뒤집어 놓으므로, 합친 칸(^n)은 상행 차례의 끝 칸에 (뒤집으면 맨 위)
        slots = [(k, p_) for k in range(len(T.st)) for p_ in range(2 if k in T.split else 1)]
        s0 = len(slots) - 1 if up else 0
        toks, j = [], 0
        for k in range(len(T.st)):
            ps = []
            for p_ in range(2 if k in T.split else 1):
                ps.append(q(f'^{len(slots)} va=m ' + text.split('; ', 1)[0] + '; ' + text.split('; ', 1)[1] if '; ' in text else f'^{len(slots)} va=m; {text}') if j == s0 else '!')
                j += 1
            toks.append(','.join(ps) if len(ps) > 1 else ps[0])
        return ' '.join(['_'] * nh) + ' : ' + ' '.join(compress(toks)) + ' : ' + ' '.join(['_'] * nf)
    trd = [l for l in A['trains'] if l.strip()]
    tru = [l for l in B['trains'] if l.strip()]
    cn = TOUR_COLNOTE.get(name)
    if cn:                  # 주석 열은 바깥쪽에: 하행은 열차 왼쪽, 상행은 오른쪽
        trd = [notecol(Td, cn)] + trd
        tru = tru + [notecol(Tu, cn, up=True)]
    notes = list(dict.fromkeys([l for l in A['notes'] + B['notes'] if l.strip()]))
    def stline(l):          # 역 줄: 「이름 착발 r=…」 → 「착발 이름 착발」 (cols ad st ad. 오른쪽 착발은 모듈이 상행으로 뒤집는다)
        tk = l.split()
        if not tk or tk[0] == '---': return l
        return f'{tk[1]} {tk[0]} {tk[1]}'
    L = head + ['', '[rows]'] + A['rows'] + ['[footer]'] + A['footer'] + ['[stations]'] + [stline(l) for l in A['stations']] \
        + ['[trains]'] + trd + ['', '[trains up]'] + tru + ['', '[notes]'] + notes
    return '\n'.join(L)

def merge_into(g, k, insert=True, via=None):
    """재래선 표 g 에 KTX 표 k 의 열차를 합친다. k 에만 있는 역은 k 의 차례대로 g 사이에 끼운다(insert).
    via: 표 밖(고속선)에서 들어오고 나가는 열차에 「…고속철도 경유」"""
    gn = [clean_name(x) for x in g['stations']]
    kn = [clean_name(x) for x in k['stations']]
    st = list(g['stations'])
    for j, x in enumerate(kn):
        if not insert or x in [clean_name(y) for y in st]: continue
        nxt = next((y for y in kn[j + 1:] if y in [clean_name(z) for z in st]), None)
        pos = [clean_name(z) for z in st].index(nxt) if nxt else len(st)
        st.insert(pos, k['stations'][j])
    sn = [clean_name(x) for x in st]
    def remap(tr, names, extra=None):
        tt = [None] * len(st)
        for j, x in enumerate(names):
            if x in sn: tt[sn.index(x)] = tr['times'][j]
        return dict(tr, times=tt, **(extra or {}))
    trs = [remap(tr, gn) for tr in g['trains']]
    skipped = list(g.get('skipped', []))
    for tr in k['trains']:
        r = remap(tr, kn, {'ktx': True, **real_ends_of(tr, k['stations'])})
        ix = [i for i, x in enumerate(r['times']) if isinstance(x, int)]
        if not ix: continue
        if via and len(ix) == 1:                          # 이 표에서는 한 역(포항 등)에만 서는 열차: 고속철도 표에만 (주에 적는다)
            if (sn[ix[0]], via) not in skipped: skipped.append((sn[ix[0]], via))
            continue
        if via:
            lab = f'{via}/경유'                                # 「경부고속선/경유」 두 줄 세로쓰기
            if r.get('cpl_at'): lab = f"{via}/{r['cpl_at']} {'분리' if k.get('dir') == 'down' else '연결'}"   # 병결: 「호남고속선/익산 분리」
            if clean_name(r['from']) != sn[ix[0]] and ix[0] >= 1: r['times'][ix[0] - 1] = lab
            if clean_name(r['to']) != sn[ix[-1]] and ix[-1] + 1 < len(sn): r['times'][ix[-1] + 1] = lab
        trs.append(r)
    return dict(g, stations=st, trains=trs, skipped=skipped)

# 서는 열차가 없어도 남길 역 (하행·상행의 역을 맞춰 나란히 놓을 때 행이 어긋나지 않게. 모든 열차 통과로)
KEEP_STATIONS = {('gen', '목포보성선'): {'조성'}}
# 수서를 드나드는 열차(옛 SRT)를 따로 표로 내는 KTX 노선 (그 열차가 3분의 1 남짓 되는 곳)
SPLIT_SUSEO = {('ktx', '경부선'), ('ktx', '호남선')}
# 순환 열차(시발역＝종착역: 홍성–천안–서화성–홍성 ITX-마음)는 따로 표로 (다른 표에서는 뺀다)
SPLIT_LOOP = {('gen', '서해선')}
LINE_STATIONS = {}      # (cat, 노선) → 역 이름들 (main 에서 채운다)
NOTE_COL_MAX = 21       # 주석 열을 더해도 이 열 수 안이면 주석 열, 넘치면 비고에
NOTES_TO_REM = {('gen', '대구선')}      # 칸이 빡빡한 표: 표 안의 경유 주도 모두 비고로
LOOP_NAME = {('gen', '서해선'): '평택선'}
def is_loop(tr): return bool(tr.get('from')) and clean_name(tr.get('from')) == clean_name(tr.get('to') or '')
# 노선 띠에 적을 역(하행 차례. 상행은 뒤집는다). 없으면 자동
HEADS = {
    ('gen', '서해선', None): '서화성 안중 홍성', ('gen', '서해선', '순환'): '홍성 천안 평택 홍성',
    ('ktx', '경부선', '수서'): '수서 대전 동대구 부산', ('ktx', '호남선', '수서'): '수서 익산 광주송정 목포',
    ('ktx', '경부선'): '서울 대전 동대구 부산', ('gen', '경부선'): '서울 대전 동대구 부산',
    ('ktx', '호남선'): '용산 익산 광주송정 목포', ('gen', '호남선'): '용산 서대전 익산 광주송정 목포',
    ('ktx', '전라선'): '용산 익산 전주 순천 여수엑스포', ('gen', '전라선'): '용산 서대전 익산 전주 순천 여수엑스포',
    ('ktx', '경전선'): '서울 동대구 마산 진주', ('gen', '경전선'): '부전 삼랑진 마산 진주 순천 광주송정',
    ('ktx', '동해선(서울~포항)'): '서울 대전 동대구 포항', ('ktx', '동해선(부전-강릉)'): '부전 포항 삼척 강릉',
    ('gen', '동해선'): '부전・동대구 경주 포항 삼척 동해 강릉',
    ('ktx', '강릉선'): '서울 청량리 평창 강릉 동해',
    ('ktx', '중앙선'): '청량리 원주 안동 경주 부전', ('gen', '중앙선'): '청량리 원주 제천 영주 안동 부전',
    ('ktx', '중부내륙선'): '판교 충주 문경',
    ('gen', '장항선'): '용산 천안 홍성 대천 익산', ('gen', '서해선'): '홍성 천안 서화성 홍성',
    ('gen', '충북선'): '대전 조치원 충주 제천 영주', ('gen', '경북선'): '김천 상주 점촌 영주',
    ('gen', '대구선'): '동대구 영천 경주 포항', ('gen', '영동선'): '강릉 동해 철암 영주',
    ('gen', '태백선'): '제천 영월 태백 동해', ('gen', '목포보성선'): '순천 벌교 전남장흥 목포',
    ('gen', '교외선'): '대곡 의정부',
    ('tour', '백두대간협곡・동해산타'): '영주 분천 철암 동해 강릉',
}

# 갈래(서로 다른 길로 가는 구간). 묶음마다 [기본 갈래, 다른 갈래, …]. 빈 기본 갈래는 막다른 지선
HS_SPLIT = [['광명'], ['영등포', '수원'], ['수서', '동탄', '평택지제']]
BRANCH = {
    ('ktx', '경부선'): [HS_SPLIT, [['경주', '울산'], ['경산', '밀양', '물금', '구포']], [[], ['포항']]],
    ('ktx', '경전선'): [HS_SPLIT],
    ('ktx', '동해선(서울~포항)'): [HS_SPLIT],
    ('ktx', '호남선'): [HS_SPLIT, [['공주'], ['서대전', '계룡', '논산']]],
    ('ktx', '전라선'): [HS_SPLIT, [['공주'], ['서대전', '계룡', '논산']]],
    ('ktx', '강릉선'): [[['강릉'], ['정동진', '묵호', '동해']]],
    ('gen', '경전선'): [[['부전', '사상', '구포', '화명', '물금', '원동', '삼랑진'], ['동대구', '경산', '남성현', '청도', '상동', '밀양']]],
    ('gen', '중앙선'): [[[], ['하양', '동대구']]],
    ('gen', '호남선'): [[[], ['극락강', '광주']]],
    ('gen', '충북선'): [[[], ['대전']]],
    ('gen', '동해선'): [[['부전', '센텀', '신해운대', '기장', '좌천', '월내', '남창', '덕하', '태화강', '효문', '호계', '북울산'], ['동대구', '하양', '영천', '아화']]],
}

# 끝에서 갈라지는 갈래 (수서 발착 표에 경전선·전라선 열차를 합친 것): 다른 갈래로 가는 열차에게 이 갈래는 ‥
DIVERGE = {
    ('ktx', '경부선'): [['물금', '구포', '부산'], ['진영', '창원중앙', '창원', '마산', '진주']],
    ('ktx', '호남선'): [['김제', '정읍', '장성', '광주송정', '나주', '목포'], ['전주', '남원', '곡성', '구례구', '순천', '여천', '여수엑스포']],
}
# 수서를 드나드는 열차를 다른 노선의 수서 발착 표에 합치는 KTX 노선 (그 노선의 표에는 서울 쪽 열차만)
SUSEO_TO = {('ktx', '경전선'): ('ktx', '경부선'), ('ktx', '전라선'): ('ktx', '호남선')}
MERGE_SUSEO = False          # 시험해 보았으나 합친 수서 표가 길어져 위아래로 들지 않아 쪽이 늘어난다 (아직 쓰지 않음)
if not MERGE_SUSEO: SUSEO_TO = {}
# 병결(분할·병합): 수서를 드나드는 손님 노선 열차는 주인 노선과 갈림역까지 함께 달린다.
# 주인 노선 수서 표에는 짝 열차 번호만(병결열차 행), 손님 노선에는 갈림역 ─ 끝의 작은 별표(수서 발착 병결)
COUPLE = {('ktx', '경부선'): ('ktx', '경전선', '동대구'), ('ktx', '호남선'): ('ktx', '전라선', '익산')}
COUPLE_GUEST = {(c, s): host for host, (c, s, _) in COUPLE.items()}
# 별표 대신 손님 노선 KTX 표 끝에 수서 열차를 직결 열차처럼 덧붙이는 노선 (수서·동탄·평택지제 행 없이, 굵은 세로줄 뒤에)
MERGE_GUEST = {('ktx', '경전선'), ('ktx', '전라선')}

def ro(no):
    """열차번호 뒤 조사 「으로/로」: 끝자리 읽기의 받침 (0·3·6 은 받침, 1·7·8 은 ㄹ 이라 「로」)"""
    return '으로' if no[-1] in '036' else '로'
GUEST_SUSEO = {}              # (cat, 손님 노선, 방향) → (별표, {손님 번호: [주인 번호]}). 주인 노선을 먼저 짤 때 채운다

def week_days(note):
    return set(note) if note and all(ch in WEEK for ch in note) else set(WEEK)

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
              '목포보성선': '木浦寶城線', '교외선': '郊外線', '관광열차': '觀光列車'}
# 종별 → 열차명 칸 (KTX 표에서 그냥 KTX는 비운다)
KIND = {'V-train': 'V', 'S-train': 'S', 'G-train': 'G', 'A-train': 'A', '동해산타열차': '산타', 'KTX': 'KTX', 'KTX-산천': '산천', 'KTX산천': '산천', 'KTX_산천': '산천', 'KTX-청룡': '청룡', 'KTX-이음': '이음',
        'ITX-새마을': '새마을', '새마을': '새마을', 'ITX-마음': '마음', '무궁화': '무궁화', '누리로': '누리로'}
LBL = {  # 머리 이름 (한국어, 국한문)
    'fr': ('시발역', '始發驛'), 'no': ('열차번호', '列車番號'), 'kind': ('등급', '等級'), 'car': ('차종', '車種'),
    'to': ('종착역', '終着驛'), 'day': ('비고', '備考'),   # 운행일 등. 인쇄에서는 쪽의 남는 자리를 이 행이 받는다
    'days': ('운행일', '運行日'),
    'cpl': ('병결열차', '倂結列車'),        # 갈림역에서 나뉘고 합치는 짝 열차의 번호                         # 기호(◆◇)로 적는 운행일: 한 줄. 그 밑에 빈 비고 행
}
def lbl(k): return LBL[k][1 if MIX else 0]

# 역 이름 고침 (위키에서 고친 것): 원본 이름 → 표에 쓸 이름. 한자도 함께
RENAME = {'판교(경기)': '판교', '진부(오대산)': '진부'}
RENAME_HANJA = {'진부': '珍富', '여수엑스포': '麗水엑스포', '민둥산': '민둥山', '나전': '羅田', '선평': '仙坪', '별어곡': '別於谷'}   # 반만 한자인 이름은 한자 부분만
def clean_name(s):
    s = re.sub(r'\((출발|도착)\)$', '', s)
    return RENAME.get(s, s)

def hm(t):
    t %= 1440
    return f'{t // 60}{t % 60:02d}'

def esc_txt(s):
    """칸 내용 안에서 꾸미기 표기로 읽히지 않게"""
    return s.replace('.', '..')

# 시발역·종착역 칸에 줄여 적는 역 이름 (한 칸에 다섯 자는 뭉개져 보기 싫다. 옛 여수역은 여수엑스포로 바뀌어 헷갈릴 것이 없다)
END_ABBR = {'여수엑스포': '여수'}

def vert(s):
    return f'r{esc_txt(s)}.' if s else '_'

WEEK = '월화수목금토일'
def day_range(s):
    """이어지는 요일 넷 이상은 범위로: 월화수목금 → 월∼금 (주를 넘어가도: 금토일월 → 금∼월). 셋은 금토일 그대로"""
    if s.endswith(' 경유'): return s[:-3] + '/경유'        # 「중앙선/경유」 두 줄 세로쓰기
    if any(ch not in WEEK for ch in s): return s
    if len(s) >= 3:
        k = WEEK.index(s[0])
        if all(WEEK[(k + i) % 7] == ch for i, ch in enumerate(s)): s = f'{s[0]}∼{s[-1]}' if len(s) >= 4 else s   # 셋은 금토일
        else: s = '・'.join(s)
    elif len(s) == 2: s = '・'.join(s)                     # 금・토 (일본식 가운뎃점. 「금토」는 한 낱말처럼 읽힌다)
    else: s += '요일'                                      # 월요일 (「월 운행」은 달로도 읽힌다)
    return s + '/운행'                                     # 요일 | 운행 두 줄

def day_short(s):
    """운행일 행: 요일 한 글자씩 붙여(금토·월수금·월), 이어지는 셋 이상만 범위(월∼목)"""
    if len(s) >= 4:                                       # 이어지는 넷 이상만 범위 (셋은 금토일처럼 늘어놓는다)
        k = WEEK.index(s[0])
        if all(WEEK[(k + i) % 7] == ch for i, ch in enumerate(s)): return f'{s[0]}∼{s[-1]}'
    return s

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
        self.merged = t.get('merged')       # 합친 노선 (경전선·전라선)
        self.skipped = t.get('skipped', [])  # 합치지 않은 KTX: 이 표에서 한 역에만 서는 것 [(역, 고속선)]
        self.loop_note = t.get('loop_note')  # 순환 열차를 뺀 표: 「홍성 순환 열차는 … 표에」
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
        for tr in trains:
            tr['times'] = [tr['times'][i] for i in keep]
            for key in ('via_in_at', 'via_out_at'):          # 뺀 역만큼 자리를 당긴다
                if key in tr: tr[key] = keep.index(tr[key]) if tr[key] in keep else sum(1 for i in keep if i < tr[key]) - 1
            if tr.get('pass_from') is not None:
                pf = st[tr['pass_from']]
                tr['pass_from'] = self.st.index(pf) if pf in self.st else None
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
            off, dead = set(), set()
            for alt in alts:
                used = [k for k, grp in enumerate(alt) if any(i in S for i in grp)] or [0]
                for k, grp in enumerate(alt):
                    if k not in used: off |= set(grp)
            for sp_, offs_ in SPUR_OFF.get((self.cat, self.line), {}).items():
                if sp_ in self.st and self.st.index(sp_) in S: off |= {self.st.index(x) for x in offs_ if x in self.st}
            for sp_ in DEAD_SPUR.get((self.cat, self.line), ()):     # 막다른 지선 역(포항)에 가지 않는 열차: ‥
                if sp_ in self.st and self.st.index(sp_) not in S: dead.add(self.st.index(sp_))
            idx = sorted(S)
            for u, v in zip(idx, idx[1:]):
                if v == u + 1 or any(T[k] == 'I' for k in range(u + 1, v)):
                    for k in range(u + 1, v):
                        if T[k] is None: T[k] = 'I'
                    continue
                for k in range(u + 1, v): T[k] = None if k in dead else 'I' if k in off else 'v'   # 다른 갈래를 달리는 동안은 ║
            # 끝에서 갈라지는 갈래: 열차가 서는 갈래가 아닌 쪽은 지나지 않는다 (‥)
            for alt in ([DIVERGE.get((self.cat, self.line), [])] if self.merged else []):
                gi = [[self.st.index(s) for s in grp if s in self.st] for grp in alt]
                used = [k for k, grp in enumerate(gi) if any(i in S for i in grp)]
                if not used: continue
                for k, grp in enumerate(gi):
                    if k in used: continue
                    for i in grp:
                        if T[i] in ('v', 'I'): T[i] = None

        # 덧붙인 수서 직결 열차: 표에 없는 수서 쪽에서 들어와 첫 정차역 앞(천안아산부터)은 지나감
        for tr in self.trains:
            p_ = tr.get('pass_from')
            if p_ is None: continue
            T = tr['times']
            idx = [i for i, x in enumerate(T) if isinstance(x, int)]
            rng = range(p_, idx[0]) if self.dir == 'down' else range(idx[-1] + 1, p_ + 1)
            for k in rng:
                if T[k] is None: T[k] = 'v'

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
        self.trains.sort(key=lambda tr: (tr.get('block', 0), tr['ref'], tr['no']))   # 덧붙인 덩어리(수서 직결)는 끝에

    # ── 원문 쓰기 ──
    def stops(self, i): return sum(isinstance(tr['times'][i], int) for tr in self.trains)

    def wiki(self, sub=None):
        n, ktx = len(self.st), self.cat == 'ktx'
        N = len(self.trains)
        first, last = self.st[0], self.st[-1]
        ends = collections.Counter()
        for tr in self.trains:
            idx = [i for i, x in enumerate(tr['times']) if isinstance(x, int)]
            if tr.get('pass_from') is not None:       # 수서 직결: 표 밖에서 들어오고 나가니 표 안의 첫·끝 역은 시발·종착이 아니다
                ends[idx[-1] if self.dir == 'down' else idx[0]] += 1; continue
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
            band_names = [s for s in hs if all(x in self.st for x in s.split('・'))]      # 「부전・동대구」: 갈래 끝 역을 나란히
        else: band_names = [self.st[i] for i in band]
        dirmark = 'k하행.' if self.dir == 'down' else 'n상행.'
        vlab = (' 수서발' if self.dir == 'down' else ' 수서행') if self.variant == '수서' else ''
        if self.merged: vlab = f'·{self.merged}' + vlab           # 경부선·경전선 수서발
        if self.variant == '순환': self.line_disp = LOOP_NAME.get((self.cat, self.line), self.line + ' 순환')
        cp = getattr(self, 'cpl', None)      # 병결: {열차번호: [짝 열차번호]}, 행 자리(head: 시발역 밑 / foot: 종착역 밑)
        hsr = HSR_NAME.get((self.cat, self.line))
        name = (hsr + vlab) if hsr else ('KTX ' if ktx else '') + (self.line_disp) + vlab
        span = (f'{band_names[0]} > {band_names[-1]}' if band_names[0] != band_names[-1] else ' > '.join(band_names)) if not sub else ' > '.join(sub.split(' ─ ')[::-1] if self.dir == 'up' else sub.split(' ─ '))
        L = []
        L.append(f'title "{dirmark} {name} u({span})."')
        hd = ' ― '.join(band_names)
        # 노선 띠: 왼쪽에 방향·노선(인쇄에서 표마다 무엇인지), 가운데에 주요 역
        dirw = '하행' if self.dir == 'down' else '상행'
        # 방향은 노선 이름 뒤에 명조로
        L.append(f'headl "b' + (f'{hsr}{vlab}' if hsr else ('`KTX` ' if ktx else '') + f'{self.line_disp}{vlab}') + f'. 〔{dirw}〕"')
        L.append(f'head "（{hd}）"')          # 구간: 명조로 괄호에
        L.append('headheight 48')
        if ktx: L.append(f'headstyle "fc={SUSEO_COLOR if self.variant == "수서" else KTX_COLOR}"')   # 수서 발착 표는 띠도 자주색
        L.append('cols st ad')
        L.append('rcols st')
        if MIX: L.append('rlabel 驛名')
        L.append('')
        # 머리 행
        L.append('[rows]')
        self.o0, self.d0 = self.st[o0], self.st[d0]
        has_fr = has_to = not getattr(self, 'both', False)      # 상하행을 한 표에: 시발·종착은 시각으로 (머리·발 행 없이)
        # 등급(KTX는 차종) 표지 바로 밑에 열차번호, 두 행은 이름 칸을 합쳐 사이 선 없이. 그 밑에 시발역
        L.append(f'kind {lbl("no")} style=va=b r={LBL["no"][1]}')
        L.append(f'no   ^ fmt=N{{*}} style=va=t')
        cpl_row = f'cpl  {lbl("cpl")} r={LBL["cpl"][1]}'
        if has_fr: L.append(f'fr   {lbl("fr")} r={LBL["fr"][1]}')
        if cp and cp['pos'] == 'head': L.append(cpl_row)
        L.append('')
        L.append('[footer]')
        if has_to: L.append(f'to   {lbl("to")} r={LBL["to"][1]}')
        if cp and cp['pos'] == 'foot': L.append(cpl_row)
        # 표의 첫 역에서 다른 선에서 들어온 열차: 그 열차(같은 선에서 잇달아 오는 열차들) 앞에 주석 열(꺾쇠 화살표 ↱ + 「…선에서」 세로).
        # 주석 열을 더하면 한 쪽에 넘칠 만큼 열차가 많은 표는 비고에 (↑…선 경유)
        fls = [self.from_line(tr) for tr in self.trains]
        runs = sum(1 for i, f in enumerate(fls) if f and (i == 0 or fls[i - 1] != f))
        self.notecol = bool(runs) and len(self.trains) + runs <= NOTE_COL_MAX
        # 표의 끝 역에서 다른 선으로 나가는 열차: 비고가 비어 있으면 비고에 「…선 경유」, 아니면 그 열차(잇달아 나가는 열차들) 뒤에 주석 열(「…선 경유」 세로 + ⬏)
        isday_ = lambda s: bool(s) and all(ch in WEEK for ch in s)
        tls = [self.to_line(tr) for tr in self.trains]
        busy = lambda tr, f: bool(self.cpl_note(tr) or self.rem_via(tr) or (f and not self.notecol) or (tr['note'] and not isday_(tr['note'])))
        # 비고에 「…선 경유」를 내려도 비고 행이 높아지지 않을 때만 (이미 그만큼 긴 세로 주가 있을 때). 아니면 주석 열
        def rem_len(tr, f):
            v = self.rem_via(tr) or (f'↑{f}/경유' if f and not self.notecol else None) or (day_range(tr['note']) if tr['note'] and not isday_(tr['note']) else None)
            return max((len(x) for x in v.split('/')), default=0) + (1 if v.startswith('↑') else 0) if v else 0
        room = max((rem_len(tr, f) for tr, f in zip(self.trains, fls)), default=0)
        self.tl_col = any(t_ and (busy(tr, f) or room < len(t_) + 1) for tr, f, t_ in zip(self.trains, fls, tls))
        cpn = any(self.cpl_note(tr) for tr in self.trains) or (any(fls) and not self.notecol) or any(self.rem_via(tr) for tr in self.trains) or (any(tls) and not self.tl_col)
        # 운행일은 제 행에 (기호 ◆◇ 또는 요일), 비고 행에는 병결·그 밖의 주. 모든 표의 끝은 비고 행 (인쇄에서 쪽의 남는 자리를 받는다)
        isday = lambda s: bool(s) and all(ch in WEEK for ch in s)
        days = {tr['note'] for tr in self.trains if isday(tr['note'])}
        self.has_days = bool(days)
        self.daysym = {'월화수목금': '◆', '토일': '◇'} if days and days <= {'월화수목금', '토일'} else None
        has_day = cpn or any(tr['note'] and not isday(tr['note']) for tr in self.trains)     # 비고에 적을 것
        self.rem_empty = not has_day
        if self.has_days: L.append(f'days {lbl("days")} r={LBL["days"][1]} style=va=t')
        if has_day: L.append(f'day  {lbl("day")} r={LBL["day"][1]} style=va=t')
        else: L.append(f'rem  {lbl("day")} r={LBL["day"][1]} style=va=t')
        self.rem_row = True
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
            nblk = sum(1 for tr in self.trains if tr.get('block'))      # 덧붙인 덩어리는 표의 크기로 치지 않는다
            for i, s in enumerate(self.st):
                trav = sum(1 for tr in self.trains if isinstance(tr['times'][i], int) or tr['times'][i] == 'v')
                stop = self.stops(i)
                if N - nblk >= 20 and trav and stop == trav and stop >= 0.3 * N:      # 지나는 열차가 모두 서는 역만 (직관적 주요역 KTX_MAJOR 은 인쇄 쪽수 때문에 한 줄로)
                    self.split.add(i)
        self.split -= {i for i, s in enumerate(self.st) if s in NOSPLIT_ALL}
        self.split |= {i for i, s in enumerate(self.st) if s in SPLIT_ALL and self.stops(i)}
        if self.cat == 'tour':           # 관광열차: 오래 머무는 역(분천·승부 등 5분 넘게)은 착발을 나눈다
            self.split |= {i for i, s in enumerate(self.st) for tr in self.trains
                           if isinstance(tr['times'][i], int) and (tr['no'], s) in ARR and (tr['times'][i] - ARR[(tr['no'], s)]) % 1440 >= 5}
        # 상행·하행이 같은 주요역·착발역을 쓰도록 main 에서 두 방향을 모아 정한 값(shared)으로 덮어쓴다
        self.cand = {self.st[i]: (self.stops(i) + ends[i]) / N for i in major}
        self.split -= {i for i in self.split if self.arr_unknown(i)}     # 도착 시각을 모르는 역(나주 등)은 착발을 합친다
        self.split_names = {self.st[i] for i in self.split}
        sh = getattr(self, 'shared', None)
        if sh:
            self.split = {i for i, s in enumerate(self.st) if s in sh['split']}
            self.split -= {i for i in self.split if self.arr_unknown(i)}
            major = sorted({i for i, s in enumerate(self.st) if s in sh['major']} | self.split)
        L.append('[stations]')
        rules = set()
        alts_r = list(BRANCH.get((self.cat, self.line), []))
        if self.merged: alts_r.append(DIVERGE.get((self.cat, self.line), []))
        for alt in alts_r:
            for grp in alt:
                ix = [self.st.index(s) for s in grp if s in self.st]
                if ix: rules |= {min(ix), max(ix) + 1}
        if self.merged:      # 끝 갈래 안쪽은 가르지 않는다 (물금·구포·부산은 한 덩어리)
            for grp in DIVERGE.get((self.cat, self.line), []):
                ix = [self.st.index(s) for s in grp if s in self.st]
                if ix: rules -= set(range(min(ix) + 1, max(ix) + 1))
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
        prev_block = 0
        prev_fl = None
        nft = (1 if has_to else 0) + (1 if cp and cp['pos'] == 'foot' else 0) + (1 if self.has_days else 0) + (1 if (has_day or self.rem_row) else 0)
        for tr in self.trains:
            if tr.get('block', 0) != prev_block: L.append('---'); prev_block = tr.get('block', 0)   # 덧붙인 덩어리 앞에 굵은 세로줄
            fl = self.from_line(tr) if self.notecol else None
            if fl and fl != prev_fl:                     # 주석 열: 첫 역 줄에 ↱, 그 밑에 「…선 경유」 세로 (필요한 칸만, 나머지는 ‥)
                need = 1 + math.ceil((len(fl) + 0.3) / 1.26) + 1          # 화살표 + 세로 글 + (인쇄의 쪽 번호)
                slots = [(k, p_) for k in range(len(self.st)) for p_ in range(2 if k in self.split else 1)]
                need = min(need, len(slots))
                toks, j = [], 0
                for k in range(len(self.st)):
                    ps = []
                    for p_ in range(2 if k in self.split else 1):
                        ps.append(q(f'^{need} va=t; ↱/VR{{{esc_txt(fl)}/경유}}') if j == 0 else '!' if j < need else 'x')
                        j += 1
                    toks.append(','.join(ps) if len(ps) > 1 and ps != ['x', 'x'] else ps[0])
                ph = ['_', '_'] + (['_'] if has_fr else []) + (['_'] if cp and cp['pos'] == 'head' else [])
                L.append(' '.join(ph) + ' : ' + ' '.join(compress(toks)) + (' : ' + ' '.join(['_'] * nft) if nft else ''))
            prev_fl = fl
            k = KIND.get(tr['type'], tr['type'])
            col = SUSEO_COLOR if self.is_suseo(tr) else KTX_COLOR       # 수서 발착은 자주색
            hdr = [q(badge(k, tr['type'])), tr['no']] + ([f'style=fc={col}', 'tstyle=fw=b'] if tr.get('ktx') else [f'style=fc={col}'] if ktx else [])   # 고속철도 표는 열차 칸을 모두 파랗게
            if has_fr:
                o, d = self.ends_of(tr)
                hdr.append(q(f'{esc_txt(END_ABBR.get(o, o))}/{hm(self.end_times(tr)[0])}'))
            # 열차번호 꼴. 짝이 요일로 바뀌면 칸에는 많이 다니는 짝, 다른 짝은 비고에 (금∼일/672)
            gs_ = self.cpl_main(tr)
            cpv = (q('/'.join(f'N{{{x}}}' for x in gs_)) if gs_ else '_') if cp else None   # 짝이 요일로 바뀌면 두 줄, 비고에 요일
            if cp and cp['pos'] == 'head': hdr.append(cpv)
            cells = self.cells(tr)
            ft = []
            if has_to:
                o, d = self.ends_of(tr)
                ft.append(q(f'{esc_txt(END_ABBR.get(d, d))}/{hm(self.end_times(tr)[1])}'))
            if cp and cp['pos'] == 'foot': ft.append(cpv)
            nt = tr['note']
            if self.has_days:
                if not isday(nt): ft.append('_')
                elif self.daysym: ft.append(self.daysym[nt])
                else: ft.append(q(esc_txt(day_short(nt))))      # 운행일 행: 요일 글자만 가로로 (이어지는 셋 이상은 월∼목), 넘치면 좁힌다
            if has_day:
                cn = self.cpl_note(tr)
                fl = self.from_line(tr)
                rv = self.rem_via(tr)
                if cn: ft.append(q(cn))
                elif rv: ft.append(q(vert(rv)))
                elif fl and not self.notecol and not (nt and '경유' in nt): ft.append(q(vert(f'↑{fl}/경유')))     # 표의 첫 역에서 다른 선에서 들어온 열차: 위 화살표 밑에 세로쓰기(…선 | 경유)
                elif self.to_line(tr) and not self.tl_col: ft.append(q(vert(f'{self.to_line(tr)}/경유')))     # 끝 역에서 다른 선으로 나가는 열차
                elif nt and not isday(nt): ft.append(q(vert(day_range(nt))))
                else: ft.append('_')
            elif self.rem_row: ft.append('_')
            line = ' '.join(hdr) + ' : ' + ' '.join(cells)
            if ft: line += ' : ' + ' '.join(ft)
            L.append(line)
            tl = self.to_line(tr) if self.tl_col else None
            ti = self.trains.index(tr)
            if tl and (ti + 1 == len(self.trains) or self.to_line(self.trains[ti + 1]) != tl or self.trains[ti + 1].get('block', 0) != tr.get('block', 0)):
                # 주석 열: 끝 역 줄에 ⬏, 그 위에 「…선 경유」 세로 (필요한 칸만, 나머지는 ‥)
                need = 1 + math.ceil((len(tl) + 0.3) / 1.26) + 1
                slots = [(k, p_) for k in range(len(self.st)) for p_ in range(2 if k in self.split else 1)]
                need = min(need, len(slots))
                s0 = len(slots) - need
                toks, j = [], 0
                for k in range(len(self.st)):
                    ps = []
                    for p_ in range(2 if k in self.split else 1):
                        ps.append(q(f'^{need} va=b; VR{{{esc_txt(tl)}/경유}}/⬏') if j == s0 else '!' if j > s0 else 'x')
                        j += 1
                    toks.append(','.join(ps) if len(ps) > 1 and ps != ['x', 'x'] else ps[0])
                ph = ['_', '_'] + (['_'] if has_fr else []) + (['_'] if cp and cp['pos'] == 'head' else [])
                L.append(' '.join(ph) + ' : ' + ' '.join(compress(toks)) + (' : ' + ' '.join(['_'] * nft) if nft else ''))
        L.append('')
        L.append('[notes]')
        notes = []
        kinds = [KIND.get(tr['type'], tr['type']) for tr in self.trains]
        if ktx:
            names = [('산천', 'KTX-산천'), ('청룡', 'KTX-청룡'), ('이음', 'KTX-이음')]
            parts = [f'S{{{k}}}은 `{full}`' for k, full in names if k in kinds]
            if parts: notes.append('차종 ' + ', '.join(parts))
            if any(self.is_suseo(tr) for tr in self.trains): notes.append('자주 글씨는 수서 발착')
        elif self.cat == 'tour': pass        # 관광열차: 등급 표지(V·S…)는 제목으로 명백하다
        else:
            types = {tr['type'] for tr in self.trains}
            parts = []
            if 'ITX-새마을' in types: parts.append('BS{k새마을.}은 `ITX-새마을`')
            if '새마을' in types: parts.append('S{새마을}은 새마을호')
            if 'ITX-마음' in types: parts.append('BS{k마음.}은 `ITX-마음`')
            if any(tr.get('ktx') for tr in self.trains):
                ks = sorted({tr['type'] for tr in self.trains if tr.get('ktx')})
                sub_ = [f'S{{{KIND[x]}}}은 `{x}`' for x in ks if KIND.get(x) and KIND[x] != 'KTX']
                parts.append('파란 글씨는 KTX' + (f"({', '.join(sub_)})" if sub_ else ''))
                if any(tr.get('ktx') and self.is_suseo(tr) for tr in self.trains): parts.append('자주 글씨는 수서 발착 KTX')
            if parts: notes.append('등급 ' + ', '.join(parts))
        if self.has_days:   # 운행일 관련은 한 줄로
            dn = []
            if self.daysym:
                used = {tr['note'] for tr in self.trains}
                if '월화수목금' in used: dn.append('◆ 평일(월∼금) 운행')
                if '토일' in used: dn.append('◇ 토·일 운행')
            if not all(isday(tr['note']) for tr in self.trains): dn.append('운행일 무표시는 매일 운행')
            if dn: notes.append(', '.join(dn))
        cp = getattr(self, 'cpl', None)
        if cp: pass                          # 어버이 열차는 비고에 「…로 분리·연결」
        elif (self.cat, self.line) in MERGE_GUEST:
            notes.append('굵은 줄 오른쪽은 수서 발착')
        elif (self.cat, self.line) in COUPLE_GUEST and self.variant != '수서':
            notes.append(f'수서 발착 열차는 수서 발착 병결 표에')
        if self.loop_note: notes.append(self.loop_note)
        ab_ = [k for k, v in END_ABBR.items() if any(k in self.ends_of(tr) for tr in self.trains)]
        if ab_ and not getattr(self, 'both', False): notes.append('시발·종착역의 ' + ', '.join(f'{END_ABBR[k]}는 {k}' for k in ab_))
        for st_, via_ in self.skipped:
            notes.append(f"{st_}에만 서는 KTX({via_} 경유)는 {via_.replace('고속선', '고속철도')} 표에")
        if any(c.startswith('_,') for tr in self.trains for c in self.cells(tr)):
            notes.append('着発 역의 빈 도착 시각은 자료 없음')
        L += notes
        return '\n'.join(L)

    def dwell_max(self):
        """따로 조사한 도착 시각을 믿는 정차 시간의 끝 (관광열차는 오래 머문다)"""
        return 60 if self.cat == 'tour' else 15

    def arr_unknown(self, i):
        """이 역에 서는(떠나거나 끝나지 않는) 열차 가운데 도착 시각을 알 수 없는 것이 있는가 (SPLIT_ALL 역은 늘 나눈다)"""
        st = self.st[i]
        if st in SPLIT_ALL: return False
        for tr in self.trains:
            x = tr['times'][i]
            if not isinstance(x, int): continue
            o, d = self.ends_of(tr)
            if st in (o, d): continue
            a = tr.get('arr_at', {}).get(st, ARR.get((tr['no'], st)))
            if a is not None and 0 <= (x - a) % 1440 <= self.dwell_max(): continue
            if DWELL.get((grade(tr['type']), st)) is None: return True
        return False

    def cpl_note(self, tr):
        """어버이 열차의 비고(가로, 줄마다): 「381/분리」(하행)·「382/연결」(상행). 짝이 요일로 바뀌면 「668/672/연결」. 열차번호는 명조"""
        gs = self.cpl_main(tr)
        if not gs: return None
        at = COUPLE.get((self.cat, self.line), (None, None, ''))[2]      # 갈림역(동대구·익산)을 앞에
        return (f'{at}/' if at else '') + '/'.join(f'N{{{x}}}' for x in gs) + '/' + ('분리' if self.dir == 'down' else '연결')

    def cpl_note_old(self, tr):
        """병결 짝이 요일로 바뀌는 열차의 비고: 짝마다 요일과 번호 「월∼목 668/금∼일 672」"""
        gs = self.cpl_main(tr)
        if len(gs) < 2: return None
        return '/'.join(f'{day_range(self.cpl["days"][x]).split("/")[0]} {x}' for x in gs)      # 「월∼목 668/금∼일 672」

    def cpl_main(self, tr):
        """짝 열차들. 운행일이 많은 것부터"""
        cp = getattr(self, 'cpl', None)
        gs = cp['map'].get(tr['no'], []) if cp else []
        return sorted(gs, key=lambda x: -len(week_days(cp['days'][x])))

    def rem_via(self, tr):
        """NOTES_TO_REM 표: 비고에 적을 경유 (↑들어온 선/경유, 나간 선/경유)"""
        if (self.cat, self.line) not in NOTES_TO_REM: return None
        o, d = self.ends_of(tr)
        idx = [i for i, x in enumerate(tr['times']) if isinstance(x, int)]
        up = tr.get('via_in') if tr.get('via_in') and o != self.st[idx[0]] else None
        up = up.replace(' 경유', '').replace('경유', '').strip() if up else self.from_line(tr)
        dn = tr.get('via_out') if tr.get('via_out') and d != self.st[idx[-1]] else None
        dn = dn.replace(' 경유', '').replace('경유', '').strip() if dn else None
        parts = ([f'↑{up}/경유'] if up else []) + ([f'{dn}/경유'] if dn else [])
        return '/'.join(parts) or None

    def from_line(self, tr):
        """표의 첫 역에서부터 서는데 시발역은 표 밖: 들어온 다른 노선(시발역과 첫 역을 함께 지나는 노선) 이름"""
        idx = [i for i, x in enumerate(tr['times']) if isinstance(x, int)]
        if not idx or idx[0] != 0 or tr.get('via_in') or tr.get('ktx'): return None
        o, _ = self.ends_of(tr)
        s0 = self.st[0]
        if o == s0 or o in self.st: return None
        for (c, ln), sts in LINE_STATIONS.items():
            if ln.split('(')[0] != self.line and o in sts and s0 in sts and c == self.cat: return ln.split('(')[0]
        return None

    def to_line(self, tr):
        """표의 끝 역까지 서는데 종착역은 표 밖: 나가는 다른 노선(종착역과 끝 역을 함께 지나는 노선) 이름"""
        idx = [i for i, x in enumerate(tr['times']) if isinstance(x, int)]
        if not idx or idx[-1] != len(self.st) - 1 or tr.get('via_out') or tr.get('ktx'): return None
        if tr['note'] and '경유' in tr['note']: return None          # 비고에 이미 (「중앙선 경유」)
        _, d = self.ends_of(tr)
        s1 = self.st[-1]
        if d == s1 or d in self.st: return None
        for (c, ln), sts in LINE_STATIONS.items():
            if ln.split('(')[0] != self.line and d in sts and s1 in sts and c == self.cat: return ln.split('(')[0]
        return None

    def is_suseo(self, tr):
        o, d = self.ends_of(tr)
        return '수서' in (clean_name(o), clean_name(d))

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
            horiz = via.startswith('=')                       # 「=수서/발/654」: 가로로 줄마다 한 행 (필요한 행만 합친다)
            text = via.lstrip('=')
            if not re.search(r'\S (분리|연결)$', text): text = text.replace(' ', '')       # 「익산 분리」만 띄어 쓴다
            if not horiz and '/' not in text: text = text.replace('경유', '/경유')             # 「태백선/경유」 두 줄 세로쓰기
            need = len(text.split('/')) if horiz else math.ceil((max(len(x) for x in text.split('/')) + 0.3) / 1.26)   # 긴 줄 1em씩(괄호 없이), 행 1.26em
            if need > len(slots): need = 0                   # 자리가 모자라면 주석 없이 ║ 만 (행이 굵어지지 않게)
            s0 = (len(slots) - need) // 2
            parts = collections.defaultdict(list)
            for j, (k, p) in enumerate(slots):
                if need and j == s0:
                    parts[k].append(q(f'^{need} va={va}; ' + (esc_txt(text) if horiz else f'VR{{{esc_txt(text)}}}')))   # 괄호 없이
                elif need and s0 < j < s0 + need: parts[k].append('!')
                else: parts[k].append('i')                   # 다른 선을 달림
            return {k: ','.join(v) if len(v) > 1 and v != ['i', 'i'] else v[0] for k, v in parts.items()}
        tail = note_slots(tail_at, n - 1, tr['via_out'], 'm') if d != self.st[b] and tr.get('via_out') and tail_at < n else None
        head = note_slots(0, head_at, tr['via_in'], 'm') if o != self.st[a] and tr.get('via_in') and head_at >= 0 else None
        rem_mode = (self.cat, self.line) in NOTES_TO_REM          # 표 안의 경유 주를 모두 비고로 (칸은 ‥)
        if rem_mode:                                   # 주는 비고로, 다른 선을 달리는 칸은 ║
            if tail: tail = {k: 'i' for k in tail}
            if head: head = {k: 'i' for k in head}
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
            elif x == 'v' and tr.get('pass_from') is not None and (i < a or i > b):   # 수서 직결: 표 밖에서 들어오고 나가는 길
                out.append('v')
            elif i < a or i > b + 1 or (i == b + 1 and bar):
                out.append('x')
            elif i == b + 1 and tr.get('pass_from') is not None:   # 수서 직결: 표 밖(수서)으로 나가니 끝 표시 없이
                out.append('x')
            elif i == b + 1 and rem_mode and tr.get('via_out'):   # 비고로 옮긴 경유: 끝 표시 없이 ‥
                out.append('x')
            elif i == b + 1:                              # 마지막 정차역 다음 칸: 끝 표시
                out.append('-,x' if sp else '-')
            elif isinstance(x, int):
                t = hm(x)
                if not sp: out.append(t); continue
                st = self.st[i]
                arr = tr.get('arr_at', {}).get(st, ARR.get((tr['no'], st)))   # 따로 조사한 도착 시각 (TAGO 열차정보, 시발 시각이 맞는 것만)
                if arr is None or not 0 <= (x - arr) % 1440 <= self.dwell_max():
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
                out.append({'v': 'v', 'x': 'x', 'I': 'i'}.get(x, 'x'))   # None: 갈라진 다른 갈래 (‥)
        if tr.get('cont'):                                # 갈림역 너머로 이어지는 홀로 열차(하행): 끝 표시 대신 ‥
            out = ['x' if c in ('-', '-,x') else c for c in out]
            out = [f'{c.split(",")[0]},x' if c.endswith(',-') else c for c in out]
        return compress(out)


def compress(out):
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


# 고속철도 표 이름 (KTX 경부선 → 경부고속철도)
HSR_NAME = {('ktx', '경부선'): '경부고속철도', ('ktx', '호남선'): '호남고속철도'}
# 고속선에서 갈라지는 KTX: 고속철도 표에 「…선 경유」로 빠지는 열차로 넣고, 그 노선 표는 갈림역부터만
HSR_SPUR = {('ktx', '경부선'): [('울산', '포항')]}      # 고속철도 표에 넣는 막다른 지선 역: (이 역 다음(하행 차례), 지선 끝 역). 서울–포항 KTX 를 끝까지
DEAD_SPUR = {}                                          # 그 역에 가지 않는 열차는 ‥ (║ 아님). 지금은 없음 (지나가는 열차는 ║ 미경유)
SPUR_OFF = {('ktx', '경부선'): {'포항': ['울산']}}        # 지선 역에 서는 열차는 이 역들을 지나지 않는다(║): 포항 열차는 경주에서 갈라져 울산 미경유
HSR_GUESTS = {('ktx', '경부선'): [('ktx', '경전선'), ('ktx', '동해선(서울~포항)')], ('ktx', '호남선'): [('ktx', '전라선')]}
BRANCH_AT = {('ktx', '경전선'): '동대구', ('ktx', '전라선'): '익산', ('ktx', '동해선(서울~포항)'): '동대구'}

def real_ends_of(tr, names):
    ix = [i for i, x in enumerate(tr['times']) if isinstance(x, int)]
    return {'from': tr.get('from') or names[ix[0]], 'to': tr.get('to') or names[ix[-1]],
            'fromT': tr.get('fromT') or tr['times'][ix[0]], 'toT': tr.get('toT') or tr['times'][ix[-1]]}

def via_trains(t, trs, gst, gline):
    """다른 노선 KTX 열차를 고속철도 표 t 의 역에 맞춰 싣는다: 같은 역은 시각, 표를 벗어나는 쪽은 「…선 경유」"""
    hn = [clean_name(x) for x in t['stations']]
    gn = [clean_name(x) for x in gst]
    out = []
    for tr in trs:
        tt = [None] * len(hn)
        for j, x in enumerate(gn):
            if x in hn and isinstance(tr['times'][j], int): tt[hn.index(x)] = tr['times'][j]
        ix = [i for i, x in enumerate(tt) if isinstance(x, int)]
        if not ix: continue
        lab = f"{gline.split('(')[0]} 경유"
        ends = real_ends_of(tr, gst)
        if t['dir'] == 'down' and clean_name(ends['to']) != hn[ix[-1]] and ix[-1] + 1 < len(hn): tt[ix[-1] + 1] = lab
        if t['dir'] == 'up' and clean_name(ends['from']) != hn[ix[0]] and ix[0] >= 1: tt[ix[0] - 1] = lab
        out.append(dict(tr, times=tt, **ends))
    return out

def branch_only(t, at):
    """갈림역 at 부터(하행)·까지(상행)만. 시발·종착은 원래대로"""
    nm = [clean_name(x) for x in t['stations']]
    k = nm.index(at)
    rng = range(k, len(nm)) if t['dir'] == 'down' else range(0, k + 1)
    trs = []
    for tr in t['trains']:
        tt = [tr['times'][i] for i in rng]
        if not any(isinstance(x, int) for x in tt): continue
        trs.append(dict(tr, times=tt, **real_ends_of(tr, t['stations'])))
    return dict(t, stations=[t['stations'][i] for i in rng], trains=trs)

def couple(t, g, at):
    """주인 표 t(수서 발착)와 손님 노선 표 g 의 수서 열차를 병결로 짝짓는다.
    짝: 갈림역 at 앞에서 함께 서는 역의 시각이 모두 같고 운행일이 겹치는 주인 열차. 짝이 없으면 홀로 다니는 열차로 주인 표에도 싣는다.
    → (새 주인 표, {주인 번호: [손님 번호]}, 손님 별표(갈림역 ─ 손님 노선 끝), {손님 번호: [주인 번호]})"""
    gn = [clean_name(x) for x in g['stations']]
    hn = [clean_name(x) for x in t['stations']]
    gk = gn.index('수서'); ka = gn.index(at)
    down = t['dir'] == 'down'
    # 하행은 갈림역에서 떨어진 뒤 손님이 늦게 떠난다(갈림역 시각이 다름): 견주는 건 갈림역 앞까지. 상행은 갈림역에서 합쳐 함께 떠난다
    trunk = range(0, ka) if down else range(ka, len(gn))
    gtr = [tr for tr in g['trains'] if isinstance(tr['times'][gk], int)]
    hmap, gmap, extra = collections.defaultdict(list), {}, []
    def real_ends(tr):
        ix = [i for i, x in enumerate(tr['times']) if isinstance(x, int)]
        return {'from': tr.get('from') or g['stations'][ix[0]], 'to': tr.get('to') or g['stations'][ix[-1]],
                'fromT': tr.get('fromT') or tr['times'][ix[0]], 'toT': tr.get('toT') or tr['times'][ix[-1]]}
    small = []
    for tr in gtr:
        hits = []
        for h in t['trains']:
            com = [(i, hn.index(gn[i])) for i in trunk if gn[i] in hn and isinstance(tr['times'][i], int) and isinstance(h['times'][hn.index(gn[i])], int)]
            if len(com) >= 2 and all(tr['times'][i] == h['times'][j] for i, j in com) and week_days(tr['note']) & week_days(h['note']):
                hits.append(h)
        for h in hits: hmap[h['no']].append(tr['no'])
        gmap[tr['no']] = [h['no'] for h in hits]
        ends = real_ends(tr)
        if not hits:          # 홀로 다니는 열차: 주인 표에도, 다른 선으로 빠지는 열차처럼 (「경전선 경유」)
            extra += via_trains(t, [tr], g['stations'], g['line'])
        # 손님 별표: 하행은 갈림역 도착 = 짝의 도착 시각
        arr_at = {}
        if down and hits:
            h = hits[0]; j = hn.index(at); x = h['times'][j]
            a = ARR.get((h['no'], at))
            if a is None or not 0 <= (x - a) % 1440 <= 15:
                w = DWELL.get((grade(h['type']), at)); a = x - w if w is not None else None
            if a is not None: arr_at[at] = a
        rng = range(ka, len(gn)) if down else range(0, ka + 1)
        small.append(dict(tr, **ends, arr_at=arr_at, times=[tr['times'][i] for i in rng]))
        print('  병결', t['line'], t['dir'], tr['no'], '↔', [h['no'] for h in hits] or '홀로')
    rng = range(ka, len(gn)) if down else range(0, ka + 1)
    gt = dict(g, stations=[g['stations'][i] for i in rng], trains=small, variant='수서')
    return dict(t, trains=t['trains'] + extra), dict(hmap), gt, gmap


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
    if TOUR:
        data['tables'] = data['tables'] + TOUR['tables']
        for t in TOUR['tables']:
            for tr in t['trains']:
                for st_, a_ in tr.get('arr', {}).items(): ARR[(tr['no'], st_)] = a_
    tabs = {(t['cat'], t['line'], t['dir']): t for t in data['tables']}
    for t in data['tables']: LINE_STATIONS.setdefault((t['cat'], t['line']), set()).update(clean_name(x) for x in t['stations'])
    book_items = []
    index = []
    for line, parts in BOOK:
        P = [f'{{{{시각표테마}}}}', f'{{{{상위문서|{PREFIX}}}}}',
             f"'''{line}'''({LINE_HANJA[line]}) 시각표. {EDITION}(가상), 코레일 {'관광열차 시각(2026년 9월 1일)' if line == '관광열차' else '2026년 10월 발표 자료'} 기준." + ''.join(f" {k[1]}(동대구–경주) 열차도 이 표에 함께 싣는다." for k, v in MERGE_GEN.items() if v[1] == line), '']
        book_items.append({'type': 'divider', 'text': line, 'sub': '', 'inline': True})
        idx = 0
        title = f'{PREFIX}/{line}'
        expanded = []
        for cat, sheet, sub in parts:
            if (cat, sheet) in MERGE_KTX: continue          # 재래선 표에 합침
            if (cat, sheet) in SPLIT_SUSEO or ((cat, sheet) in COUPLE_GUEST and (cat, sheet) not in MERGE_GUEST):
                expanded += [(cat, sheet, sub, None), (cat, sheet, sub, '수서')]
            elif (cat, sheet) in SPLIT_LOOP:
                expanded += [(cat, sheet, sub, None), (cat, sheet, sub, '순환')]
            else: expanded.append((cat, sheet, sub, None))
        for cat, sheet, sub, variant in expanded:
            head = (HSR_NAME.get((cat, sheet)) or ('KTX' if cat == 'ktx' else sheet.replace('(', ' (') if cat == 'tour' else '일반열차')) + (f" ({sub.replace(' ─ ', '–')})" if sub else '') + (' (수서 발착)' if variant == '수서' else '') + (f" ({LOOP_NAME.get((cat, sheet), '순환')})" if variant == '순환' else '')
            if variant == '수서' and (cat, sheet) in COUPLE_GUEST: head = 'KTX (수서 발착 병결)'
            P.append(f'== {head} ==')
            pair = {}
            for d in ('down', 'up'):
                t = tabs.get((cat, sheet, d))
                if not t: continue
                for kk in MERGE_INTO.get((cat, sheet), []):
                    kt = tabs.get(kk + (d,))
                    if not kt: continue
                    if kk in BRANCH_AT:            # 고속선 구간은 고속철도 표에: 갈림역부터만
                        gt_, gmap_ = GUEST_SUSEO.get(kk + (d,), ({'trains': []}, {}))
                        gby_ = {x['no']: x for x in gt_['trains']}
                        cat_ = COUPLE[COUPLE_GUEST[kk]][2] if kk in COUPLE_GUEST else None      # 병결 짝이 있는 열차: 갈림역에서 분리·연결
                        kt = dict(kt, trains=[dict(tr, arr_at=gby_.get(tr['no'], {}).get('arr_at', {}),
                                                   **({'cpl_at': cat_} if cat_ and gmap_.get(tr['no']) else {})) for tr in kt['trains']])
                        kt = branch_only(kt, BRANCH_AT[kk])
                    t = merge_into(t, kt, insert=kk not in BRANCH_AT, via=VIA_HSR.get(kk))
                for gk in MERGE_GEN_INTO.get((cat, sheet), []):
                    if gk + (d,) in tabs: t = merge_gen(t, tabs[gk + (d,)])
                if (cat, sheet) in SPLIT_SUSEO or (cat, sheet) in SUSEO_TO:
                    k = next(i for i, x in enumerate(t['stations']) if clean_name(x) == '수서')
                    t = dict(t, variant=variant, trains=[tr for tr in t['trains'] if isinstance(tr['times'][k], int) == (variant == '수서')])
                    # 수서 발착 표에 다른 노선(경전선·전라선)의 수서 열차를 합친다: 그 노선에만 있는 역은 끝의 갈래로
                    if variant == '수서':
                        for (gc, gs), host in SUSEO_TO.items():
                            if host != (cat, sheet) or (gc, gs, d) not in tabs: continue
                            g = tabs[(gc, gs, d)]
                            gk = next(i for i, x in enumerate(g['stations']) if clean_name(x) == '수서')
                            gtr = [tr for tr in g['trains'] if isinstance(tr['times'][gk], int)]
                            hn = [clean_name(x) for x in t['stations']]
                            extra = [x for x in g['stations'] if clean_name(x) not in hn]
                            st2 = (list(t['stations']) + extra) if d == 'down' else (extra + list(t['stations']))
                            nm2 = [clean_name(x) for x in st2]
                            def remap(tr, names):
                                pos = {clean_name(x): i for i, x in enumerate(names)}
                                tt = [None] * len(st2)
                                for j, x in enumerate(nm2):
                                    if x in pos: tt[j] = tr['times'][pos[x]]
                                return dict(tr, times=tt)
                            t = dict(t, stations=st2, trains=[remap(tr, t['stations']) for tr in t['trains']] + [remap(tr, g['stations']) for tr in gtr])
                            t['merged'] = gs
                cpl = None
                if variant == '수서' and (cat, sheet) in COUPLE:
                    gc, gs, at = COUPLE[(cat, sheet)]
                    t, hmap, gt, gmap = couple(t, tabs.get((gc, gs, d)), at)
                    GUEST_SUSEO[(gc, gs, d)] = (gt, gmap)
                    cpl = {'map': hmap, 'pos': None, 'with': gs, 'at': at,
                           'days': {tr['no']: tr['note'] for tr in gt['trains']}}
                elif variant == '수서' and (cat, sheet) in COUPLE_GUEST:
                    t, gmap = GUEST_SUSEO[(cat, sheet, d)]      # 별표는 직결 열차처럼 (시발·종착역이 수서). 병결열차 행 없이
                elif (cat, sheet) in MERGE_GUEST:      # 수서 열차는 표 끝(굵은 줄 뒤)에. 고속선 구간은 고속철도 표에 있으니 갈림역부터
                    nm = [clean_name(x) for x in t['stations']]
                    k = nm.index('수서')
                    gt, gmap = GUEST_SUSEO.get((cat, sheet, d), ({'trains': []}, {}))
                    gby = {x['no']: x for x in gt['trains']}
                    trs = []
                    for tr in t['trains']:
                        if not isinstance(tr['times'][k], int): trs.append(tr); continue
                        trs.append(dict(tr, block=1, arr_at=gby.get(tr['no'], {}).get('arr_at', {})))
                    t = dict(t, trains=trs)
                elif (cat, sheet) in COUPLE_GUEST:     # 수서 열차는 병결 별표로
                    k = next(i for i, x in enumerate(t['stations']) if clean_name(x) == '수서')
                    t = dict(t, trains=[tr for tr in t['trains'] if not isinstance(tr['times'][k], int)])
                for at_, sp_ in HSR_SPUR.get((cat, sheet), []):     # 고속철도 표에 막다른 지선 역(포항)을 갈림역 옆에
                    nm_ = [clean_name(x) for x in t['stations']]
                    if at_ not in nm_ or sp_ in nm_: continue
                    k_ = nm_.index(at_) + (1 if d == 'down' else 0)
                    t = dict(t, stations=t['stations'][:k_] + [sp_] + t['stations'][k_:],
                             trains=[dict(tr, times=tr['times'][:k_] + [None] + tr['times'][k_:]) for tr in t['trains']])
                if (cat, sheet) in HSR_GUESTS:          # 고속선에서 갈라지는 다른 노선 KTX 를 「…선 경유」로
                    for gk in HSR_GUESTS[(cat, sheet)]:
                        g = tabs.get(gk + (d,))
                        if not g: continue
                        gnm = [clean_name(x) for x in g['stations']]
                        sk = gnm.index('수서') if '수서' in gnm else None
                        if variant == '수서' and gk in COUPLE_GUEST: continue      # 병결 열차는 couple 에서 (홀로 다니는 것만 실림)
                        gtr = [tr for tr in g['trains'] if (sk is not None and isinstance(tr['times'][sk], int)) == (variant == '수서')]
                        t = dict(t, trains=t['trains'] + via_trains(t, gtr, g['stations'], gk[1]))
                if (cat, sheet) in BRANCH_AT and variant is None:
                    t = branch_only(t, BRANCH_AT[(cat, sheet)])
                if cat == 'gen':                   # 순환 열차는 순환 표에만 (뺀 표에는 주로 어디 있는지)
                    out_ = [tr for tr in t['trains'] if is_loop(tr)] if variant != '순환' else []
                    t = dict(t, trains=[tr for tr in t['trains'] if is_loop(tr) == (variant == '순환')])
                    if variant == '순환': t['variant'] = '순환'
                    elif out_: t['loop_note'] = f"{clean_name(out_[0]['from'])} 순환 열차는 {next(iter(LOOP_NAME.values()))} 표에"
                    if (cat, sheet) in SPLIT_LOOP and variant is None and any(is_loop(tr) for tr in tabs[(cat, sheet, d)]['trains']):
                        t['loop_note'] = f"{clean_name(next(tr for tr in tabs[(cat, sheet, d)]['trains'] if is_loop(tr))['from'])} 순환 열차는 {LOOP_NAME[(cat, sheet)]} 표에"
                T = Table(t, data['hanja']); T.line_disp = LINE_DISP.get((cat, sheet), sheet.replace('(', ' (') if cat == 'tour' else line); T.cpl = cpl
                T.both = cat == 'tour'
                T.wiki(sub); pair[d] = T
            shared = share(list(pair.values()))
            if cat == 'tour' and len(pair) == 2:          # 관광열차: 상하행을 한 표에 (가운데 역명)
                for T in pair.values(): T.shared = shared
                P.append('{{#invoke:Timetable|main|data=')
                P.append(combine_both(pair['down'], pair['up'], sub, sheet))
                P.append('}}')
                P.append('')
                book_items.append({'type': 'table', 'title': title, 'idx': idx, 'label': f"{line} {head}", 'fit': 'split', 'scale': 100})
                idx += 1
                print(f'{line:6} {head:16} both {len(pair["down"].st):3} st {len(pair["down"].trains) + len(pair["up"].trains):4} tr')
                continue
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
    for (c_, ln_), (hc_, hl_) in MERGE_GEN.items():      # 합친 노선의 문서는 넘겨주기
        open(os.path.join(outdir, f'{ln_}.wiki'), 'w').write(f'#REDIRECT [[{PREFIX}/{hl_}]]\n')
    # 목차 문서
    I = ['{{시각표테마}}', f'시각표 {EDITION}(가상). 코레일 2026년 10월 발표 자료(일반열차·고속열차) 기준, JTB 시각표 꼴로 재구성.', '',
         '* 시각은 분 단위(초 버림)', '* 오른쪽 역명은 한자'] + (['* 관광열차는 코레일 관광열차 시각(2026년 9월 1일) 기준'] if TOUR else []) + ['', '== 노선 ==']
    I += [f'* [[{PREFIX}/{l}|{l}]]' for l in index]
    open(os.path.join(outdir, '_index.wiki'), 'w').write('\n'.join(I) + '\n')
    json.dump(book_items, open(os.path.join(outdir, 'items.json'), 'w'), ensure_ascii=False, indent=1)
    json.dump(sorted(NEED), open(os.path.join(outdir, 'need-arrivals.json'), 'w'), ensure_ascii=False)
    print(len(NEED), 'arrivals to look up,', len({(o, s) for _, o, s, _ in NEED}), 'station pairs')


if __name__ == '__main__':
    main()
