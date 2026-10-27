#!/usr/bin/env python3
"""ttbook — 위키 시각표(Module:Timetable)를 LuaLaTeX 로 조판해 PDF 를 만든다.

  python3 ttbook.py book.json            → build/book.tex → build/book.pdf

흐름
  1. 위키 문서 원문에서 {{#invoke:Timetable|main|data=…}} 블록을 꺼낸다.
  2. 위키 모듈(src/Timetable.lua)을 texlua 로 그대로 돌려 HTML 표를 얻는다.
     → 내용(기호·서식 규칙)의 정본은 위키 하나. 여기서는 '그리는 법'만 따로 가진다.
  3. HTML 의 class·style 을 위키 CSS 와 같은 뜻으로 읽어, 칸의 자리·괘선을 직접 계산한다.
  4. 모든 것을 절대 위치(picture)로 내보낸다. 괘선은 PDF 사각형으로 — 굵기를 반올림하지 않는다.
"""
import collections, copy, json, math, os, re, subprocess, sys
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
MM = 72 / 25.4            # 1 mm 를 bp 로

# ───────────────────────── HTML → 간단한 트리 ─────────────────────────
class Node:
    __slots__ = ('tag', 'attrs', 'kids', 'cls', 'style')
    def __init__(self, tag, attrs):
        self.tag = tag
        self.attrs = dict(attrs)
        self.kids = []
        self.cls = set((self.attrs.get('class') or '').split())
        self.style = parse_style(self.attrs.get('style') or '')
    def find(self, pred):
        if pred(self): return self
        for k in self.kids:
            if isinstance(k, Node):
                r = k.find(pred)
                if r: return r
        return None
    def findall(self, pred, out=None):
        out = [] if out is None else out
        if pred(self): out.append(self)
        for k in self.kids:
            if isinstance(k, Node): k.findall(pred, out)
        return out
    def text(self):
        return ''.join(k if isinstance(k, str) else k.text() for k in self.kids)

def parse_style(s):
    d = {}
    for part in s.split(';'):
        if ':' in part:
            k, v = part.split(':', 1)
            d[k.strip()] = v.strip()
    return d

VOID = {'br', 'img', 'hr'}
class TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('root', [])
        self.stack = [self.root]
    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs)
        self.stack[-1].kids.append(n)
        if tag not in VOID: self.stack.append(n)
    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break
    def handle_data(self, data):
        if data: self.stack[-1].kids.append(data)

def parse_html(h):
    b = TreeBuilder(); b.feed(h); b.close()
    return b.root

# ───────────────────────── 위키 원문 → 표 HTML ─────────────────────────
def invoke_blocks(page_text):
    return re.findall(r'\{\{#invoke:Timetable\|main\|data=\n(.*?)\n\}\}', page_text, re.S)

def run_module(data, mod, workdir):
    os.makedirs(workdir, exist_ok=True)
    dp = os.path.join(workdir, '_data.txt')
    with open(dp, 'w', encoding='utf-8') as f: f.write(data)
    r = subprocess.run(['texlua', os.path.join(HERE, 'src', 'run_module.lua'), mod, dp],
                       capture_output=True, check=True)
    return r.stdout.decode('utf-8')

# ───────────────────────── 표 모형 ─────────────────────────
class Cell:
    def __init__(self, node, r, c, rs, cs):
        self.node, self.r, self.c, self.rs, self.cs = node, r, c, rs, cs
        self.cls = node.cls
        self.style = node.style

class Table:
    pass

class Ghost:
    """빈 열의 칸: 마지막 열차 열의 칸과 같은 괘선. 역 행에는 ‥ (달리는 열차 없음)"""
    def __init__(self, ref, r):
        self.ref = ref
        self.r, self.c, self.rs, self.cs = r, ref.c, 1, ref.cs
        self.cls = ref.cls - {'jtt-t1'}
        self.style = {k: v for k, v in ref.style.items() if k.startswith('border')}
        self.lines = []

def cell_of(T, r, j):
    if isinstance(j, tuple):
        ref = T.occ.get((r, j[1]))
        if ref is None: return None
        key = (r, j[2])
        g = T.ghosts.get(key)
        if g is None: g = T.ghosts[key] = Ghost(ref, r)
        return g
    return T.occ.get((r, j))

def kind_of(T, j):
    return ('T', None) if isinstance(j, tuple) else T.kind[j]

def width_of(T, j):
    return T.colW[j[1]] if isinstance(j, tuple) else T.colW[j]

def weight_of(v):
    """CSS border 값 → 괘선 종류 0 / 1 / 2 / 3 / 'd'"""
    if not v: return 0
    v = v.strip()
    if v.startswith('none') or v.startswith('0'): return 0
    if 'double' in v: return 'd'
    m = re.match(r'([\d.]+)px', v)
    if not m: return 1
    x = float(m.group(1))
    return 1 if x < 1.75 else 2 if x < 2.75 else 3

def wrank(w):
    return {0: 0, 1: 1, 2: 2, 'd': 2.5, 3: 3}[w]

def wmax(a, b):
    return a if wrank(a) >= wrank(b) else b

def build_table(wrap):
    T = Table()
    T.wrap = wrap
    T.title = wrap.find(lambda n: 'jtt-title' in n.cls)
    T.head = wrap.find(lambda n: 'jtt-head' in n.cls)
    T.notes = wrap.find(lambda n: 'jtt-notes' in n.cls)
    tb = wrap.find(lambda n: n.tag == 'table')
    T.vars = tb.style
    rows = [n for n in tb.kids if isinstance(n, Node) and n.tag == 'tr']
    T.rowcls = [r.cls for r in rows]
    occ = {}
    T.cells = []
    for ri, tr in enumerate(rows):
        c = 0
        for td in [k for k in tr.kids if isinstance(k, Node) and k.tag == 'td']:
            while (ri, c) in occ: c += 1
            rs = int(td.attrs.get('rowspan', 1)); cs = int(td.attrs.get('colspan', 1))
            cell = Cell(td, ri, c, rs, cs)
            T.cells.append(cell)
            for i in range(rs):
                for j in range(cs): occ[(ri + i, c + j)] = cell
            c += cs
    T.nrow = len(rows)
    T.ncol = max(c for (_, c) in occ) + 1
    T.occ = occ
    # 열의 종류
    kind = [None] * T.ncol
    for cell in T.cells:
        if cell.cs != 1: continue
        k = None
        if 'jtt-st' in cell.cls: k = ('L', 'st')
        elif 'jtt-ad' in cell.cls: k = ('L', 'ad')
        elif 'jtt-km' in cell.cls: k = ('L', 'km')
        elif 'jtt-mk' in cell.cls: k = ('L', 'mk')
        elif 'jtt-t' in cell.cls: k = ('T', None)
        elif 'jtt-rc' in cell.cls:
            role = next((x[6:] for x in cell.cls if x.startswith('jtt-r-')), 'st')
            k = ('R', role)
        if k and kind[cell.c] is None: kind[cell.c] = k
    T.kind = [k or ('T', None) for k in kind]
    # 열차 사이 굵은 세로줄(원문 [trains] 의 ---): 그 왼쪽에서 표를 나눌 수 있다 (덧붙인 덩어리 등)
    T.rules = sorted({cell.c for cell in T.cells if cell.cs == 1 and T.kind[cell.c][0] == 'T'
                      and re.search(r'border-left:\s*2px', cell.node.attrs.get('style', ''))})
    T.hEnd = sum(1 for c in T.rowcls if 'jtt-hr' in c)
    f1 = next((i for i, c in enumerate(T.rowcls) if 'jtt-f1' in c), T.nrow)
    T.fStart = f1
    T.ghosts = {}
    return T

# ───────────────────────── 글꼴·글자 ─────────────────────────
TEX_ESC = {'\\': r'\textbackslash{}', '{': r'\{', '}': r'\}', '$': r'\$', '&': r'\&',
           '#': r'\#', '^': r'\^{}', '_': r'\_', '%': r'\%', '~': r'\~{}'}
def esc(s):
    return ''.join(TEX_ESC.get(ch, ch) for ch in s)

def is_latin(ch):
    return ord(ch) < 0x2000 and ch != ' '

class Ctx:
    def __init__(self, font='DM', size=1.0, color=None):
        self.font, self.size, self.color = font, size, color
    def but(self, **kw):
        c = Ctx(self.font, self.size, self.color)
        c.track = getattr(self, 'track', 0.0)
        for k, v in kw.items(): setattr(c, k, v)
        return c

# 글꼴 묶음 (TeX 명령 이름) — 위키 CSS 의 역할과 같게
#   DM  표 본문: DiaPro → 명조            M   명조
#   DGB 굵게(k·b): DiaPro 굵은 숫자 → 고딕 굵게   DG 배지: DiaPro → 고딕
#   GB  제목: 고딕 굵게                    G   고딕
FONT_OF_CLASS = {'jtt-st': 'M', 'jtt-ad': 'M', 'jtt-th': 'M', 'jtt-r-st': 'M', 'jtt-r-ad': 'M',
                 'jtt-lit': 'M', 'jtt-td': 'M', 'jtt-no': 'M', 'jtt-tcy': 'M'}

# ───────────────────────── 글꼴 찾기·재기 ─────────────────────────
# 미세 조정 값을 손으로 정하지 않는다: 조판할 때마다 쓰는 글꼴에서 글자의 높이를 재어 맞춘다.
# 글꼴을 바꾸면 이름만 바꾸면 된다 (사람이 정하는 것은 '얼마나 맞출지'의 비율 alignStrength 뿐)
FONT_EXT = ('.ttf', '.otf', '.ttc', '.otc')

class FontDB:
    def __init__(self, dirs, cache_path):
        self.map = {}
        try: cache = json.load(open(cache_path, encoding='utf-8'))
        except Exception: cache = {}
        new = {}
        for d in dirs:
            for root, _, files in os.walk(d):
                for fn in files:
                    if not fn.lower().endswith(FONT_EXT): continue
                    path = os.path.join(root, fn)
                    try: mt = os.path.getmtime(path)
                    except OSError: continue
                    ent = cache.get(path)
                    if not ent or ent['mt'] != mt:
                        ent = {'mt': mt, 'faces': self._names(path)}
                    new[path] = ent
                    for idx, names in enumerate(ent['faces']):
                        for n in names: self.map.setdefault(n.lower(), (path, idx))
        try: json.dump(new, open(cache_path, 'w', encoding='utf-8'), ensure_ascii=False)
        except Exception: pass
        self.fonts = {}

    @staticmethod
    def _names(path):
        from fontTools.ttLib import TTFont, TTCollection
        faces = []
        try:
            if path.lower().endswith(('.ttc', '.otc')):
                fl = TTCollection(path, lazy=True).fonts
            else:
                fl = [TTFont(path, lazy=True)]
            for f in fl:
                nm = f['name']
                g = lambda i: (nm.getDebugName(i) or '')
                ns = {g(4), g(6), (g(1) + ' ' + g(2)).strip(), (g(16) + ' ' + g(17)).strip(), g(1) if g(2) in ('Regular', '') else ''}
                faces.append(sorted(x for x in ns if x))
        except Exception:
            pass
        return faces

    def get(self, name):
        key = name.lower()
        if key not in self.map:
            for suf in (' regular', ' r'):
                if key + suf in self.map: key += suf; break
        if key not in self.map: return None
        if key not in self.fonts: self.fonts[key] = FontInfo(*self.map[key])
        return self.fonts[key]

class FontInfo:
    def __init__(self, path, idx):
        from fontTools.ttLib import TTFont
        self.path, self.idx = path, idx
        self.f = TTFont(path, fontNumber=idx, lazy=True)
        self.cmap = self.f.getBestCmap()
        self.gs = self.f.getGlyphSet()
        self.upm = self.f['head'].unitsPerEm
        self._bb = {}
    def has(self, ch): return ord(ch) in self.cmap
    def adv(self, ch):
        """전진폭 (em)"""
        g = self.cmap.get(ord(ch))
        return self.f['hmtx'][g][0] / self.upm if g else None
    def bbox(self, ch):
        """잉크 상자 (em) 와 전진폭"""
        if ch in self._bb: return self._bb[ch]
        from fontTools.pens.boundsPen import BoundsPen
        g = self.cmap.get(ord(ch))
        r = None
        if g:
            pen = BoundsPen(self.gs); self.gs[g].draw(pen)
            if pen.bounds:
                u = self.upm
                b = pen.bounds
                r = (b[0] / u, b[1] / u, b[2] / u, b[3] / u, self.gs[g].width / u)
        self._bb[ch] = r
        return r
    def center(self, chars):
        cs = [self.bbox(c) for c in chars]
        cs = [(b[1] + b[3]) / 2 for b in cs if b]
        return sum(cs) / len(cs) if cs else None

SAMPLE_HANGUL = '가나다라마바사아자차카타파하서울부산경행역'
SAMPLE_HANGUL_W = '서울부산경행역대전동구광명수원천안김천'   # 폭을 잴 한글: 받침 있는 글자가 많은 역 이름 같은 것
SAMPLE_KANJI = '東西南北大田釜山駅京水原永登浦光明'
SAMPLE_DIGIT = '0123456789'

# ───────────────────────── 줄 안 요소 ─────────────────────────
# 줄(line) = 요소 목록. 요소: ('tex', tex, size)  ('just', [tex…], size)  ('obj', tex, w_em, h_em, size)
GOTHIC = {'DG', 'DGB', 'GB', 'G'}
TEXT_FAMS = {'M', 'G', 'GB'}      # DiaPro 를 앞세우지 않는 본문 글꼴
KO_OF = {'M': 'KM', 'DM': 'KM', 'G': 'KG', 'DG': 'KG', 'GB': 'KGB', 'DGB': 'KGB', 'FO': 'KGB'}
JP_OF = {'M': 'mincho', 'DM': 'mincho', 'G': 'gothic', 'DG': 'gothic', 'GB': 'gothicBold', 'DGB': 'gothicBold', 'FO': 'gothicBold'}
KO_ROLE = {'KM': 'minchoKo', 'KG': 'gothicKo', 'KGB': 'gothicKoBold'}
# 한글 문맥의 문장 부호: 한글 글꼴의 것을 먼저 쓴다
KO_PUNCT = set('()[]{}<>,.:;!?\'"-/·「」『』（）〔〕［］《》〈〉―—–‐～〜…')

def char_kind(ch):
    o = ord(ch)
    if 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F: return 'ko'
    if ch in KO_PUNCT: return 'kp'
    if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF or 0x3040 <= o <= 0x30FF: return 'jp'
    return 'base'

# 세로쓰기에서 돌려 쓸 글자 (세로쓰기 전용 글자 → 가로 글자)
OPENING, CLOSING = set('（〔「『'), set('）〕」』')
# 세로 제목에서 돌려 쓸 전각 가로 글자
HFULL = {'(': '（', '（': '（', '︵': '（', ')': '）', '）': '）', '︶': '）',
         '―': '―', '—': '―', '︱': '―', '〔': '〔', '︹': '〔', '〕': '〕', '︺': '〕'}
SUBST = {'∼': ['～', '〜', '~'], '～': ['〜', '∼', '~'], '〜': ['～', '∼', '~'], '―': ['—', '─'], '—': ['―', '─'], '・': ['·'], '·': ['・']}
VALT = {'―': ['—', '─', '－'], '(': ['（'], ')': ['）']}
VROT = {'∼': '∼', '～': '～', '〜': '〜', '〔': '〔', '〕': '〕', '︵': '(', '︶': ')', '︱': '―', '︹': '〔', '︺': '〕', '(': '(', ')': ')', '（': '(', '）': ')', '―': '―', '—': '―'}

class Metrics:
    """글꼴에서 잰 값: 기준 중심(명조 한자), 글꼴마다 옮길 양"""
    def __init__(self, db, fonts, strength, jp_scale='auto'):
        self.db, self.fonts, self.k = db, fonts, strength
        self.info = {role: db.get(name) for role, name in fonts.items() if isinstance(name, str)}
        ref = self.info.get('mincho')
        self.ref = (ref and ref.center(SAMPLE_KANJI)) or 0.37
        self.shift = {}
        for role, fi in self.info.items():
            if not fi: continue
            if 'Ko' in role:
                c = fi.center(SAMPLE_HANGUL)
            elif role == 'dia':
                c = fi.center(SAMPLE_DIGIT)
            else:
                c = fi.center(SAMPLE_KANJI)
            self.shift[role] = (self.ref - c) * self.k if c is not None else 0.0
        self.missing = [n for r, n in fonts.items() if isinstance(n, str) and not self.info.get(r)]
        # 한자·가나는 한글보다 커 보인다 (네모를 꽉 채우고 획이 많다). 짝이 되는 한글 글꼴의 한글 폭에 맞춰 줄인다
        self.jscale = {}
        for jp, ko in (('mincho', 'minchoKo'), ('gothic', 'gothicKo'), ('gothicBold', 'gothicKoBold')):
            if isinstance(jp_scale, (int, float)): self.jscale[jp] = float(jp_scale); continue
            fj, fk = self.info.get(jp), self.info.get(ko)
            wj = fj and self._width(fj, SAMPLE_KANJI); wk = fk and self._width(fk, SAMPLE_HANGUL_W)
            self.jscale[jp] = min(1.0, max(0.85, wk / wj)) if (wj and wk) else 1.0

    @staticmethod
    def _width(fi, chars):
        bs = [fi.bbox(c) for c in chars]; bs = [b for b in bs if b]
        return sum(b[2] - b[0] for b in bs) / len(bs) if bs else None
    def report(self):
        return ', '.join('%s %+.3f' % (r, v) for r, v in sorted(self.shift.items())) + \
            ' | kanji scale ' + ', '.join('%s %.3f' % (r, v) for r, v in sorted(self.jscale.items()))

class Inline:
    def __init__(self, fs, metrics=None):
        self.fs = fs          # 기준 글자 크기 (bp)
        self.m = metrics
        self.wc = {}          # run() 이 만든 TeX → 폭(기준 em). 띠를 몇 줄로 짤지 어림할 때

    @property
    def c(self):              # 글자 중심의 높이 (em) — 줄 높이의 가운데에 둘 곳
        return self.m.ref if self.m else 0.37

    def font(self, ctx, fam=None):
        s = ctx.size * self.fs
        t = r'\f%s\fontsize{%.3fbp}{%.3fbp}\selectfont ' % (fam or ctx.font, s, s * 1.25)
        if ctx.color: t += r'\color[HTML]{%s}' % ctx.color
        return t

    def shift_for(self, kind, fam):
        if not self.m: return 0.0
        if kind in ('ko', 'kp'): return self.m.shift.get(KO_ROLE[KO_OF[fam]], 0.0)
        if kind == 'jp': return self.m.shift.get(JP_OF[fam], 0.0)
        return 0.0

    def run(self, s, ctx, vertical=False):
        """글자들을 글꼴별 토막으로: 한글·문장 부호는 한글 글꼴, 한자·가나는 일본 글꼴, 나머지(숫자·로마자·기호)는 그대로.
        가로쓰기에서는 글꼴마다 잰 만큼 위아래를 맞춘다"""
        if not s: return ''
        s = self.cover(s, ctx.font)
        s = re.sub(r' (?=[〔（「『])', '\u2002', s)      # 여는 괄호 앞은 조금 더 띄운다
        segs = []
        for ch in s:
            k = char_kind(ch)
            # 본문 글꼴(명조·고딕)에서는 숫자·로마자·기호도 한글 글꼴을 먼저 (한자·가나만 일본 글꼴)
            if k == 'base' and ctx.font in TEXT_FAMS and ch != ' ': k = 'kp'
            if k == 'kp' and self.m:
                ki = self.m.info.get(KO_ROLE[KO_OF[ctx.font]])
                if not (ki and ki.has(ch)): k = 'base'
            if ch == ' ': k = segs[-1][0] if segs else 'base'
            if segs and segs[-1][0] == k: segs[-1][1].append(ch)
            else: segs.append([k, [ch]])
        out = []
        wsum = 0.0
        for k, chs in segs:
            sp = r'\hskip %.3fbp ' % (0.3 * ctx.size * self.fs)
            sp2 = r'\hskip %.3fbp ' % (0.55 * ctx.size * self.fs)
            fam = KO_OF[ctx.font] if k in ('ko', 'kp') else ctx.font
            # 가로쓰기 괄호: 잉크를 안쪽 글자에 붙이고(0.1em) 바깥쪽 여백은 앞의 띄움이 맡는다 (세로쓰기와 같게)
            fi_b = self.m.info.get(KO_ROLE[fam]) if (self.m and k == 'kp' and fam in KO_ROLE) else None
            em_b = ctx.size * self.fs
            def one(ch):
                if ch == ' ': return sp
                if ch == '\u2002': return sp2
                if fi_b and ch in '〔（「『〕）」』':
                    bb = fi_b.bbox(ch)
                    if bb:
                        x0, _, x1, _, adv = bb
                        if ch in '〔（「『':
                            return r'\kern%.3fbp %s\kern%.3fbp ' % (-x0 * em_b, esc(ch), (-(adv - x1) + 0.1) * em_b)
                        return r'\kern%.3fbp %s\kern%.3fbp ' % ((-x0 + 0.1) * em_b, esc(ch), -(adv - x1) * em_b)
                return esc(ch)
            tr_ = getattr(ctx, 'track', 0.0)          # 자간 (em). 열차번호의 숫자는 살짝 좁게
            t = (r'\kern%.3fbp ' % (tr_ * ctx.size * self.fs)).join(one(ch) for ch in chs) if tr_ else ''.join(one(ch) for ch in chs)
            c2 = ctx
            up = self.shift_for(k, ctx.font)
            if k == 'jp' and self.m:
                sc = self.m.jscale.get(JP_OF[ctx.font], 1.0)
                if sc < 0.999:
                    c2 = ctx.but(size=ctx.size * sc)
                    up += (1 - sc) * self.c          # 작아진 글자의 가운데를 제자리에
            body = '{' + self.font(c2, fam) + t + '}'
            wsum += c2.size * sum(self.adv(ch, fam) for ch in chs) + (tr_ * ctx.size * (len(chs) - 1) if tr_ else 0.0)
            if abs(up) > 0.002 and not (vertical and k == 'base'):
                body = r'\raisebox{%.3fbp}{%s}' % (up * ctx.size * self.fs, body)
            out.append(body)
        res = '{' + ''.join(out) + '}'
        self.wc[res] = wsum
        return res

    def adv(self, ch, fam):
        """글꼴 묶음 fam 에서 ch 의 폭 (em). 묶음의 글꼴을 차례로 보아 처음 가진 것의 폭"""
        if ch in ' \u00a0': return 0.3
        if ch == '\u2002': return 0.55
        if not self.m: return 1.0 if not is_latin(ch) else 0.55
        for role in FAMCHAIN.get(fam, []):
            fi = self.m.info.get(role)
            a = fi and fi.adv(ch)
            if a:
                if role in ('mincho', 'gothic', 'gothicBold'):
                    a *= self.m.jscale.get(role, 1.0) if char_kind(ch) == 'jp' else 1.0
                return a
        return 1.0

    def line_w(self, line):
        """줄 하나의 폭 (기준 em)"""
        w = 0.0
        for it in line:
            if it[0] == 'tex': w += self.wc.get(it[1], 1.0 * len(it[1]) / 20)
            elif it[0] == 'just': w += sum(self.wc.get(x, 1.0) for x in it[1])
            elif it[0] == 'obj': w += it[2]
            elif it[0] == 'sq': w += 2.0 * it[3]
        return w

    CHAIN = {'M': ['mincho', 'minchoKo', 'dia'], 'DM': ['dia', 'mincho', 'minchoKo'],
             'G': ['gothic', 'gothicKo', 'dia'], 'DG': ['dia', 'gothic', 'gothicKo'],
             'GB': ['gothicBold', 'gothicKoBold', 'dia'], 'DGB': ['dia', 'gothicBold', 'gothicKoBold']}
    def cover(self, s, fam):
        """이 글꼴 묶음 어디에도 없는 글자는 비슷한 글자로 바꾼다 (∼ → ～ 〜 ~, ― → — ─ …)"""
        if not self.m: return s
        fonts = [self.m.info.get(r) for r in self.CHAIN.get(fam, []) + [KO_ROLE[KO_OF[fam]]]]
        fonts = [f for f in fonts if f]
        out = []
        for ch in s:
            if ch in SUBST and not any(f.has(ch) for f in fonts):
                ch = next((a for a in SUBST[ch] if any(f.has(a) for f in fonts)), ch)
            out.append(ch)
        return ''.join(out)

    def vform(self, ch, ctx, col_w):
        """세로 제목의 괄호·줄표: 같은 한글 글꼴의 전각 가로 글자(（）―)를 돌려 쓴다.
        전각 글자는 한 자 폭에 바깥쪽 여백을 품고 있어, 돌리기만 하면 앞뒤가 알맞게 빈다.
        글자를 가로지르는 쪽은 잉크의 가운데를 열의 가운데에. 한글 글꼴에 없으면 일본 글꼴의 것을"""
        h = HFULL.get(ch)
        if not h or not self.m: return self.vglyph(ch, ctx, col_w)
        em = ctx.size * self.fs
        for fam, role in ((KO_OF[ctx.font], KO_ROLE[KO_OF[ctx.font]]), (ctx.font, JP_OF[ctx.font])):
            fi = self.m.info.get(role)
            bb = fi.bbox(h) if fi else None
            if not bb: continue
            x0, y0, x1, y1, adv = bb
            yc = (y0 + y1) / 2
            hh = max(y1 - yc, yc - y0) * em
            g = '{' + self.font(ctx, fam) + esc(h) + '}'
            # 글 방향(돌린 뒤 세로)의 자리: 한 자 폭. 여는 괄호는 잉크를 뒤 글자 쪽에, 닫는 괄호는 앞 글자 쪽에
            slot, L, pad = adv * em, (x1 - x0) * em, 0.1 * em
            if h in OPENING: start = slot - pad - L
            elif h in CLOSING: start = pad
            else: start = (slot - L) / 2
            box = r'\rotatebox{-90}{\raisebox{%.3fbp}[%.3fbp][%.3fbp]{\hbox to %.3fbp{\kern%.3fbp%s\hss}}}' % (
                -yc * em, hh, hh, slot, start - x0 * em, g)
            return r'\hbox to %.3fbp{\hss %s\hss}' % (col_w, box), adv
        return self.vglyph(ch, ctx, col_w)

    def vglyph(self, ch, ctx, col_w):
        """세로쓰기의 괄호·줄표: 한글 글꼴의 가로 글자를 돌려, 잉크의 가운데를 열의 가운데에"""
        base = VROT.get(ch, ch)
        em = ctx.size * self.fs
        # 한글 글꼴에 없으면 일본 글꼴의 것을 (어느 쪽이든 잉크를 재어 가운데에)
        fam, bb = None, None
        for cand in [base] + VALT.get(base, []):          # 그 글자가 없으면 비슷한 글자로 (― → — → ─)
            for f2, role in ((KO_OF[ctx.font], KO_ROLE[KO_OF[ctx.font]]), (ctx.font, JP_OF[ctx.font])):
                fi = self.m and self.m.info.get(role)
                if fi and fi.bbox(cand):
                    fam, bb, base = f2, fi.bbox(cand), cand; break
            if bb: break
        if not bb:
            return r'\hbox to %.3fbp{\hss\rotatebox{-90}{%s}\hss}' % (col_w, self.run(base, ctx, True)), 0.5
        x0, y0, x1, y1, adv = bb
        yc, hh = (y0 + y1) / 2 * em, (y1 - y0) / 2 * em
        g = '{' + self.font(ctx, fam) + esc(base) + '}'
        # 돌린 뒤 세로(글 방향) 자리는 잉크 길이 + 앞뒤 조금
        L = (x1 - x0) * em
        pad = 0.12 * em
        box = r'\rotatebox{-90}{\raisebox{%.3fbp}[%.3fbp][%.3fbp]{\hbox to %.3fbp{\kern%.3fbp%s\hss}}}' % (
            -yc, hh, hh, L + 2 * pad, pad - x0 * em, g)
        return r'\hbox to %.3fbp{\hss %s\hss}' % (col_w, box), (L + 2 * pad) / em

    def lines(self, node, ctx):
        """노드 → 줄 목록"""
        lines = [[]]
        self._walk(node, ctx, lines)
        return lines

    def _walk(self, node, ctx, lines):
        for k in node.kids:
            if isinstance(k, str):
                k = k.replace('\n', '')
                if k: lines[-1].append(('tex', self.run(k, ctx), ctx.size))
                continue
            if k.tag == 'br':
                lines.append([]); continue
            cls = k.cls
            c2 = ctx
            for cl, f in FONT_OF_CLASS.items():
                if cl in cls: c2 = c2.but(font=f)
            if 'jtt-no' in cls: c2 = c2.but(track=-0.04)     # 열차번호(명조) 숫자는 자간을 살짝 좁게
            if 'jtt-lit' in cls and ctx.font in ('DGB', 'GB'): c2 = c2.but(font='GB')   # 굵은 글 안의 로마자(KTX 등)는 고딕 굵게 그대로
            if 'jtt-j' in cls:
                chars = [self.run(x.text(), c2) for x in k.kids if isinstance(x, Node)]
                lines[-1].append(('just', chars, c2.size)); continue
            if 'jtt-bd' in cls:
                lines[-1].append(self.badge(k, c2)); continue
            if 'jtt-v' in cls and 'jtt-vbox' not in cls:
                lines[-1].append(self.vert(k, c2, lr='tt-rl' not in cls)); continue
            if 'jtt-vbox' in cls:
                lines[-1].append(self.vbox(k, c2)); continue
            if 'jtt-sq' in cls:
                r = float(k.style.get('--r', '1'))
                inner = self.lines(k, c2)
                tex = ''.join(self.flat(l) for l in inner)
                lines[-1].append(('sq', tex, r, c2.size)); continue
            if 'jtt-td' in cls:
                lines[-1].append(('obj', r'\hbox to %.3fbp{\hss %s\hss}' % (0.36 * c2.size * self.fs, self.run(k.text(), c2.but(font='M'))),
                                  0.36 * c2.size, 1.25 * c2.size, c2.size)); continue
            if 'tt-small' in cls: c2 = c2.but(size=c2.size * 0.75)
            if 'tt-bold' in cls: c2 = c2.but(font='GB')
            if 'tt-darrow' in cls:          # 이어짐 화살표(모듈의 굵은 화살표 ➡ 를 아래로)
                em_ = c2.size * self.fs
                # 위 괘선에 붙이고 밑에 반 줄 비운다
                lines[-1].append(('obj', r'\vbox{\hbox to %.3fbp{\hss\rotatebox{-90}{%s}\hss}\kern%.3fbp}' % (
                    1.0 * em_, self.run('➡', c2.but(font='DG')), 0.1 * em_), 1.0 * c2.size, 1.2 * c2.size, c2.size))
                continue
            if 'jtt-b' in cls: c2 = c2.but(font='DGB', size=c2.size * 1.2)
            elif 'jtt-k' in cls: c2 = c2.but(font='DGB')
            if 'jtt-g' in cls: c2 = c2.but(size=c2.size * 1.2)
            self._walk(k, c2, lines)

    def flat(self, line):
        o = []
        for it in line:
            if it[0] == 'tex': o.append(it[1])
            elif it[0] == 'just': o.append(''.join(it[1]))
            elif it[0] == 'obj': o.append(it[1])
            elif it[0] == 'sq': o.append(it[1])
        return ''.join(o)

    # 배지 S{} BS{}: 1.3em 네모, 글자는 고딕 .8
    def badge(self, k, ctx):
        sm = ctx.size * 0.8
        c2 = ctx.but(font='DG', size=sm)
        filled = 'jtt-bd--f' in k.cls
        if filled: c2 = c2.but(color='FFFFFF')
        inner_node = next((x for x in k.kids if isinstance(x, Node)), k)
        inner = self.flat(self.lines(inner_node, c2)[0])
        w, sx = 1.3, 1.0
        if 'jtt-bd--w2' in k.cls: w = 2.2
        elif 'jtt-bd--w3' in k.cls: w, sx = 2.4, 0.78
        elif 'jtt-bd--w4' in k.cls: w, sx = 2.4, 0.6
        h = 1.3
        if 'jtt-bd--n' in k.cls: w = max(1.3, len(inner_node.text()) * 0.55 + 0.4)
        wb, hb = w * sm * self.fs, h * sm * self.fs
        tex = r'\ttbadge{%.3f}{%.3f}{%d}{%.3f}{%.3f}{%s}' % (wb, hb, 1 if filled else 0, sx, self.c * ctx.size * self.fs, inner)
        return ('obj', tex, w * sm, h * sm, ctx.size)

    # 세로쓰기 (jtt-v: 왼쪽→오른쪽 열, jtt-vb: 오른쪽→왼쪽)
    def vcol(self, line_items, ctx):
        """한 열의 글자들을 쌓은 \\vbox 와 높이(em)"""
        rows, h = [], 0.0
        em = ctx.size * self.fs
        for (txt, c) in line_items:
            i = 0
            while i < len(txt):
                ch = txt[i]
                if ch == ' ':
                    rows.append(r'\kern%.3fbp' % (0.33 * em)); h += 0.33; i += 1; continue
                if ch in VROT:
                    t, l = self.vform(ch, c, em)
                    rows.append(t); h += l; i += 1; continue
                if ch.isdigit():                 # 숫자(열차번호 등): 명조로, 세로쓰기 안에서 글자를 눕혀(오른쪽으로 90°) 한 덩어리로
                    j = i
                    while j < len(txt) and txt[j].isdigit(): j += 1
                    run = txt[i:j]
                    wl = 0.52 * len(run) + 0.1
                    rows.append(r'\kern%.3fbp\hbox to %.3fbp{\hss\rotatebox{-90}{%s}\hss}' % (
                        0.05 * em, em, self.run(run, c.but(font='M'))))
                    h += wl; i = j; continue
                if is_latin(ch):
                    j = i
                    while j < len(txt) and is_latin(txt[j]): j += 1
                    run = txt[i:j]
                    wl = sum(0.55 if x.isupper() else 0.5 for x in run)
                    rows.append(r'\hbox to %.3fbp{\hss\rotatebox{-90}{%s}\hss}' % (em, self.run(run, c)))
                    h += wl; i = j; continue
                rows.append(r'\hbox to %.3fbp{\hss\rule[%.3fbp]{0pt}{%.3fbp}%s\hss}' % (em, -0.12 * em, em, self.run(ch, c, True)))
                h += 1; i += 1
        return r'\vbox{\offinterlineskip ' + ''.join(rows) + '}', h

    def text_cols(self, node, ctx):
        cols = [[]]
        def walk(n, c):
            for k in n.kids:
                if isinstance(k, str):
                    k = k.replace('\n', '')
                    if k: cols[-1].append((k, c))
                elif k.tag == 'br': cols.append([])
                else:
                    c2 = c
                    for cl, f in FONT_OF_CLASS.items():
                        if cl in k.cls: c2 = c2.but(font=f)
                    walk(k, c2)
        walk(node, ctx)
        return cols

    def vert(self, k, ctx, lr=True, pitch=1.0):
        cols = self.text_cols(k, ctx)
        boxes, hmax = [], 0
        for col in cols:
            b, h = self.vcol(col, ctx)
            boxes.append(b); hmax = max(hmax, h)
        if not lr: boxes = boxes[::-1]
        em = ctx.size * self.fs
        tex = r'\hbox{' + ''.join(r'\hbox to %.3fbp{\hss\vtop{\kern0pt %s}\hss}' % (pitch * em, b) for b in boxes) + '}'
        return ('obj', tex, pitch * len(boxes), hmax, ctx.size, 'v')

    def vbox(self, k, ctx):
        # VP{…}: 괄호(DiaPro 세로 괄호, 1em 줄 하나씩) + 오른쪽→왼쪽 세로 글
        em = ctx.size * self.fs
        parts, h = [], 0.0
        vb = k.find(lambda n: 'jtt-vb' in n.cls)
        bks = [x for x in k.kids if isinstance(x, Node) and 'jtt-bk' in x.cls]
        GAP = 0.12                                # 괄호 잉크와 글자 사이 (em)
        fd = self.m.info.get('dia') if self.m else None
        def bslot(ch, opening):
            """괄호 자리: 잉크를 재어, 글자에서 GAP 만큼 떨어지게. (tex, 높이 em)"""
            g = self.run(ch, ctx.but(font='DM'))
            bb = fd.bbox(ch) if fd else None
            if not bb:
                return r'\hbox to %.3fbp{\hss\raisebox{%.3fbp}[%.3fbp][0pt]{%s}\hss}' % (cwid, 0.0 if opening else -0.4 * em, 0.6 * em, g), 0.6
            _, y0, _, y1, _ = bb
            S = (y1 - y0) + GAP + (0 if opening else 0.08)
            r = (GAP - y0) if opening else (S - GAP - y1 - 0.08)     # 닫는 괄호는 조금 더 아래로
            return r'\hbox to %.3fbp{\hss\raisebox{%.3fbp}[%.3fbp][0pt]{%s}\hss}' % (cwid, r * em, S * em, g), S
        def bk(n, top):
            nonlocal h
            t_, hh_ = bslot(n.text(), True)
            parts.append(t_); h += hh_
        ncol = max(1, len(self.text_cols(vb, ctx))) if vb is not None else 1
        cwid = 1.05 * em * ncol                 # 여러 줄이면 괄호는 줄들 가운데에
        if bks and 'jtt-bk--o' in bks[0].cls: bk(bks[0], True)
        if vb is not None:
            cols = self.text_cols(vb, ctx)
            boxes, hm = [], 0
            hs_ = []
            for col in cols:
                b, hh = self.vcol(col, ctx)
                boxes.append(b); hs_.append(hh); hm = max(hm, hh)
            boxes, hs_ = boxes[::-1], hs_[::-1]
            # 짧은 줄은 괄호 사이 가운데에
            parts.append(r'\hbox{' + ''.join(r'\hbox to %.3fbp{\hss\vtop{\kern%.3fbp %s}\hss}' % (1.05 * em, (hm - hh) / 2 * em, b)
                                             for b, hh in zip(boxes, hs_)) + '}')
            h += hm
        cl = [b for b in bks if 'jtt-bk--c' in b.cls]
        if cl:
            for b in cl:
                t_, hh_ = bslot(b.text(), False)
                parts.append(t_); h += hh_
        tex = r'\vtop{\kern0pt\vbox{\offinterlineskip ' + ''.join(parts) + '}}'
        return ('obj', tex, 1.05 * ncol, h, ctx.size, 'v')

# ───────────────────────── 칸 그리기 ─────────────────────────
def line_height(line, fs_em=1.0):
    h = 0
    for it in line:
        if it[0] == 'obj': h = max(h, it[3], 1.25 * it[4] if len(it) < 6 else 0)
        else: h = max(h, 1.25 * it[-1])
    return h or 1.25

REF_C = 0.37      # 글자 중심의 높이(em). 조판할 때 명조 한자에서 잰 값으로 바뀐다

def strut(size, fs):
    s = size * fs
    L = 1.25 * s
    c = REF_C * s
    return r'\rule[%.3fbp]{0pt}{%.3fbp}' % (-(L / 2 - c), L)

def line_tex(line, W, halign, fs, inl, sqcenter=False, padem=0.06):
    """줄 하나 → \\hbox to W"""
    if not line: return None
    size = max(it[-1] if it[0] != 'obj' else it[4] for it in line)
    has_v = any(it[0] == 'obj' and len(it) > 5 for it in line)
    st = '' if has_v else strut(size, fs)
    pad = padem * size * fs                # 칸 양옆에 남길 여백: 넘치는 것만 글자를 가로로 좁힌다 (시각·두 글자는 그대로)
    if len(line) == 1 and line[0][0] == 'just':
        chars = line[0][1]
        wj = sum(inl.wc.get(x, 1.0) for x in chars) * fs if inl else 0
        if wj > W - 2 * pad and wj > 0:
            return r'\hbox to %.3fbp{%s\hss\scalebox{%.3f}[1]{%s}\hss}' % (W, st, (W - 2 * pad) / wj, ''.join(chars))
        if len(chars) <= 1:
            return r'\hbox to %.3fbp{%s\hss %s\hss}' % (W, st, ''.join(chars))
        return r'\hbox to %.3fbp{%s%s}' % (W, st, r'\hfill '.join(chars))
    body = []
    for it in line:
        if it[0] == 'tex': body.append(it[1])
        elif it[0] == 'just': body.append(''.join(it[1]))
        elif it[0] == 'obj': body.append(it[1])
        elif it[0] == 'sq':
            w2 = 2.0 * it[3] * fs
            al = r'\hss' if sqcenter else r'\hss'
            body.append(r'\hbox to %.3fbp{%s\scalebox{%.3f}[1]{%s}%s}' % (w2, al, it[2], it[1], r'\hss' if sqcenter else ''))
    b = ''.join(body)
    wl = inl.line_w(line) * fs if inl and not any(it[0] == 'sq' for it in line) else 0
    if wl > W - 2 * pad and wl > 0:
        b = r'\scalebox{%.3f}[1]{%s}' % ((W - 2 * pad) / wl, b)
    if halign == 'l': return r'\hbox to %.3fbp{%s%s\hss}' % (W, st, b)
    if halign == 'r': return r'\hbox to %.3fbp{%s\hss %s}' % (W, st, b)
    return r'\hbox to %.3fbp{%s\hss %s\hss}' % (W, st, b)

def just_th(line, W, jn, fs):
    """th.jtt-jn: 가장 긴 이름(jn 자)의 자간으로 양끝을 맞춘다"""
    if not (len(line) == 1 and line[0][0] == 'just'): return None
    em = line[0][2] * fs
    pad = max(0.0, (W - jn * em) / (jn + 1))
    chars = line[0][1]
    st = strut(line[0][2], fs)
    if len(chars) == 1:
        return r'\hbox to %.3fbp{%s\hss %s\hss}' % (W, st, chars[0])
    return r'\hbox to %.3fbp{%s\kern%.3fbp %s\kern%.3fbp}' % (W, st, pad, r'\hfill '.join(chars), pad)

# ───────────────────────── 책 ─────────────────────────
class Book:
    def __init__(self, cfg, base):
        self.cfg, self.base = cfg, base
        self.fs = cfg.get('fs', 6.5)
        P = cfg['page']
        self.W, self.H = P['w'] * MM, P['h'] * MM
        m = P['margin']
        self.mt, self.mb, self.mi, self.mo = (m['top'] * MM, m['bottom'] * MM, m['inner'] * MM, m['outer'] * MM)
        self.cw = self.W - self.mi - self.mo
        self.ch = self.H - self.mt - self.mb
        r = cfg.get('rules', {})
        self.rw = {1: r.get('thin', 0.1) * MM, 2: r.get('mid', 0.25) * MM, 3: r.get('thick', 0.35) * MM}
        self.dbl = [x * MM for x in r.get('double', [0.1, 0.15])]
        self.R = cfg.get('lineHeight', 1.26) * self.fs           # 한 줄(행) 높이
        self.P0 = cfg.get('colWidth', 2.3) * self.fs             # 열차 열 폭
        self.frame_w = self.rw[2]                                 # 틀 굵기
        self.frame_pad = cfg.get('framePad', 0.5) * MM            # 틀과 표 사이
        self.hang_title = cfg.get('titleInMargin', False)         # 세로 제목을 바깥 여백에 내어 달기
        self.page_title = cfg.get('pageTitle', False)              # 표마다의 세로 제목 대신, 쪽마다 노선 이름을 하나 크게 (바깥 여백)
        if self.page_title: self.hang_title = True
        self.band_inset = cfg.get('bandInset', 0.9) * self.fs
        self.band_lead = cfg.get('bandLead', 0.3) * self.fs        # 띠가 두 줄 이상일 때 줄 사이 더 벌림
        self.vband_w = cfg.get('leftBandWidth', 2.2) * self.fs      # 띠를 표 왼쪽 끝에 세로로 둘 때의 폭
        self.vpad = cfg.get('leftBandPad', 1.2) * self.fs           # 세로 띠 글의 위아래 여백     # 띠의 왼쪽·오른쪽 글을 틀에서 띄우는 만큼
        self.notes = cfg.get('notes', True)                        # false: 표 밑의 주기(공통 범례)를 싣지 않는다
        self._bands = {}
        self.fold = cfg.get('fold', 'off')                          # off | on | auto: 표를 한 쪽 폭의 띠로 접어 위아래로 쌓기
        self.strip_side = 'B' if cfg.get('stripStubs', 'both') == 'both' else 'L'
        self.strip_rule = cfg.get('stripRule', 2)                   # 같은 표의 띠 사이 괘선 (0 가는 1 중간 2 굵은 'd' 겹)
        self.table_rule = cfg.get('tableRule', 'd')                 # 다른 표 사이 괘선
        self.squeeze = cfg.get('squeeze', 0.93)                    # 열 폭을 좁혀도 되는 한도 (넘치는 한두 편을 싣기 위해)
        # 글꼴: 이름으로 찾고, 조판 전에 재어 둔다
        dirs = cfg.get('fontDirs') or DEFAULT_FONT_DIRS
        self.font_dirs = [os.path.expanduser(d) if os.path.isabs(os.path.expanduser(d)) else os.path.join(base, d) for d in dirs]
        self.font_dirs = [d for d in self.font_dirs if os.path.isdir(d)]
        os.makedirs(os.path.join(HERE, 'build'), exist_ok=True)
        db = FontDB(self.font_dirs, os.path.join(HERE, 'build', 'fontdb.json'))
        self.fonts = dict(DEFAULT_FONTS, **cfg.get('fonts', {}))
        self.metrics = Metrics(db, self.fonts, cfg.get('alignStrength', 0.85), cfg.get('kanjiScale', 'auto'))
        global REF_C
        REF_C = self.metrics.ref
        self.inl = Inline(self.fs, self.metrics)
        self.pages = []                                           # [(side, [tex…], runhead)]

    # ── 칸의 괘선(위키 CSS 와 같은 셈) ──
    def borders(self, T, cell):
        cls, st = cell.cls, cell.style
        rc = T.rowcls[cell.r]
        left = 1
        if cls & {'jtt-c1', 'jtt-t1', 'jtt-st', 'jtt-ad', 'jtt-rc', 'jtt-cx'}: left = 0
        if 'jtt-rc1' in cls: left = 2
        right = 0
        if 'jtt-ad' in cls and 'jtt-adin' not in cls: right = 2
        if 'jtt-lend' in cls: right = 2
        nxt = T.occ.get((cell.r, cell.c + cell.cs))
        if nxt is not None and 'jtt-t1' in nxt.cls and not isinstance(cell, Ghost): right = 2
        top = 0
        if 'jtt-hr' in rc: top = 1
        if cell.r == 0: top = 0
        if rc & {'jtt-b1', 'jtt-f1'}: top = 'd'
        if 'jtt-fr' in rc: top = 1
        if 'jtt-ln' in rc: top = 1
        if 'jtt-nl' in rc: top = 0
        bottom = 0
        for side in ('left', 'right', 'top', 'bottom'):
            v = st.get('border-' + side)
            if v is not None:
                w = weight_of(v)
                if side == 'left': left = w
                elif side == 'right': right = w
                elif side == 'top': top = w
                else: bottom = w
        return left, right, top, bottom

    def col_widths(self, T):
        em = self.fs
        w = [0.0] * T.ncol
        stw = 6.4
        m = re.search(r'calc\(([\d.]+)', T.vars.get('--jtt-st', ''))
        if m: stw = float(m.group(1))
        for j, (k, role) in enumerate(T.kind):
            if k == 'L':
                w[j] = {'st': stw, 'ad': 1.2, 'km': 3.0, 'mk': 2.6}.get(role, 3.6) * em
            elif k == 'T':
                w[j] = self.P0
            else:
                need = 5.0
                for c in T.cells:
                    if c.c == j and c.cs == 1 and 'jtt-th' not in c.cls:
                        need = max(need, len(c.node.text().strip()) * (1.2 if 'jtt-b' in str(c.node.cls) else 1.0) + 0.6)
                w[j] = need * em
        return w

    # ── 칸 내용의 높이(em) ──
    def cell_need(self, T, cell, lines):
        h = 0
        for ln in lines:
            if not ln: continue
            h += line_height(ln)
        if any(it[0] == 'obj' and len(it) > 5 for ln in lines for it in ln):
            rc = T.rowcls[cell.r]
            if rc & {'jtt-f1', 'jtt-fr'}: h += 0.4
            else: h += 0.2
        return h

    def prepare(self, T):
        """칸마다 줄 목록·필요 높이, 행 높이(R 의 배수)"""
        fs = self.fs
        base = Ctx('DM', 1.0)
        # 오른쪽 역명을 한글로 (왼쪽 역명과 같은 글, 주요역은 키우지 않고 굵게만)
        if self.cfg.get('rightHangul', False):
            left = {cl.r: cl for cl in T.cells if 'jtt-st' in cl.cls and 'jtt-th' not in cl.cls and T.kind[cl.c][0] == 'L'}
            # 머리·꼬리 행의 이름(열차번호·시발역·종착역·비고 …)도 왼쪽 것으로
            for cl in T.cells:
                if 'jtt-th' in cl.cls and T.kind[cl.c][0] == 'L' and cl.r not in left: left[cl.r] = cl
            def unbig(n):
                for k in n.kids:
                    if isinstance(k, Node):
                        if 'jtt-b' in k.cls: k.cls = (k.cls - {'jtt-b'}) | {'tt-bold'}
                        unbig(k)
            for cl in T.cells:
                if T.kind[cl.c][0] == 'R' and cl.r in left and ('jtt-r-st' in cl.cls or 'jtt-th' in cl.cls) and \
                        ('jtt-th' in cl.cls) == ('jtt-th' in left[cl.r].cls):
                    nd = copy.deepcopy(left[cl.r].node)
                    unbig(nd)
                    cl.node = nd
        # 운행일(비고) 행: 세로쓰기 대신 작은 글자로 가로로 (한 줄에 세 자까지, 고르게 나눠 여러 줄)
        dayrows = {cl.r for cl in T.cells if cl.c == 0 and re.sub(r'\s', '', cl.node.text()) in ('운행일', '운행일주의', '비고')}
        T.dayrow = max(dayrows) if dayrows else None
        for cl in T.cells:             # 비고 행: 내용은 위에 붙이고(쪽의 남는 자리만큼 늘어난다), 이름 칸은 가운데
            if cl.r in dayrows:
                cl.style = dict(cl.style)
                cl.style['vertical-align'] = 'middle' if T.kind[cl.c][0] in ('L', 'R') else 'top'
        if self.cfg.get('daysCompact', True):
            for cl in T.cells:
                if cl.r in dayrows and cl.c > 0 and cl.node.find(lambda n: 'jtt-v' in n.cls):
                    t = re.sub(r'\s', '', cl.node.text())
                    # 요일 뭉치만 작은 가로 글씨로(세 자까지 한 줄, 넷~여섯 자는 두 자씩 세 줄까지).
                    # 나머지(「운행」, 「…선 경유」 등)는 관습대로 보통 크기 세로쓰기
                    mv = re.match(r'(.+선)경유$', t)
                    if mv:          # 「…선 경유」: 굵은 화살표 밑에 두 줄 세로쓰기(…선 | 경유)
                        ar = Node('span', [('class', 'tt-darrow')])
                        vt = Node('span', [('class', 'jtt-v tt-rl')]); vt.kids += [mv.group(1), Node('br', []), '경유']
                        nd = Node('td', []); nd.kids += [ar, Node('br', []), vt]
                        cl.node = nd
                        cl.style = dict(cl.style); cl.style['vertical-align'] = 'top'
                        continue
                    pr = re.findall(r'([월화수목금토일∼~·・요]+)(\d+)', t)
                    if pr and ''.join(a + b for a, b in pr) == t:     # 「월∼목 668/금∼일 672」(병결 짝): 짝마다 한 줄, 보통 크기 세로쓰기
                        vt = Node('span', [('class', 'jtt-v tt-rl')])
                        for k_, (a, b) in enumerate(pr):
                            if k_: vt.kids.append(Node('br', []))
                            vt.kids.append(a + ' ' + b)
                        nd = Node('td', []); nd.kids.append(vt)
                        cl.node = nd
                        cl.style = dict(cl.style); cl.style['vertical-align'] = 'top'
                        continue
                    m = re.match(r'[월화수목금토일∼~·・요]+', t)
                    if not m: continue
                    days, rest = m.group(0), t[m.end():]
                    if len(days) <= 3:               # 범위(금∼일)·두 자 이하: 보통 크기 세로쓰기로 「…운행」
                        # 두 줄 세로쓰기(오른쪽 줄이 먼저): 요일 | 운행
                        vt = Node('span', [('class', 'jtt-v tt-rl')]); vt.kids += [days, Node('br', []), rest or '운행']
                        nd = Node('td', []); nd.kids.append(vt)
                        cl.node = nd
                        cl.style = dict(cl.style); cl.style['vertical-align'] = 'top'
                        continue
                    per = 3 if len(days) <= 3 or len(days) > 6 else 2
                    sm = Node('span', [('class', 'tt-small')])
                    for i in range(0, len(days), per):
                        if i: sm.kids.append(Node('br', []))
                        sm.kids.append(days[i:i + per])
                    vt = Node('span', [('class', 'jtt-v')])
                    vt.kids.append(rest or '운행')
                    nd = Node('td', [])
                    nd.kids += [sm, Node('br', []), vt]
                    cl.node = nd
                    cl.style = dict(cl.style); cl.style['vertical-align'] = 'top'
        for cell in T.cells:
            c = base
            if getattr(cell, 'small', None): c = c.but(size=cell.small)
            for cl, f in FONT_OF_CLASS.items():
                if cl in cell.cls: c = c.but(font=f)
            if ('jtt-ad' in cell.cls or 'jtt-mk' in cell.cls) and 'jtt-th' not in cell.cls: c = c.but(size=0.8)
            if 'jtt-r-ad' in cell.cls and 'jtt-th' not in cell.cls: c = c.but(size=0.8)
            cell.lines = self.inl.lines(cell.node, c)
            cell.lines = [l for l in cell.lines] if any(cell.lines) else []
            cell.need = self.cell_need(T, cell, cell.lines)
        R = self.R / fs                     # em
        rows = [1] * T.nrow
        for cell in T.cells:
            if cell.rs != 1: continue
            loose = bool(T.rowcls[cell.r] & {'jtt-hr', 'jtt-f1', 'jtt-fr'})
            tol = 0.4 * R if loose else 0.05
            n = max(1, math.ceil((cell.need - tol) / R - 1e-9))
            rows[cell.r] = max(rows[cell.r], n)
        for cell in T.cells:
            if cell.rs <= 1: continue
            tot = sum(rows[cell.r:cell.r + cell.rs])
            n = math.ceil((cell.need - 0.05) / R - 1e-9)
            if n > tot: rows[cell.r + cell.rs - 1] += n - tot
        T.rowH = [n * self.R for n in rows]
        T.colW = self.col_widths(T)

    def dir_badge(self, t, down, hollow, size, colw):
        """방향 표지(모듈의 jtt-dir: 뾰족한 오각형 안에 하행·상행). (tex, 높이 bp)"""
        em = size * self.fs
        bs = 0.84 * em
        bw = bs * 1.16
        G = 0.14 * bs                     # 두 글자 사이를 살짝 띄운다
        bh = bs * (len(t) + 0.36 + 0.6) + G * (len(t) - 1)
        P = 0.4 * em
        top = (bh - P - len(t) * bs - G * (len(t) - 1)) / 2 + (0 if down else P)
        stack = (r'\kern%.3fbp' % G).join(r'\hbox to %.3fbp{\hss\rule[%.3fbp]{0pt}{%.3fbp}%s\hss}' % (
            bw, -0.12 * bs, bs, self.inl.run(ch, Ctx('GB', size * 0.84, None if hollow else 'FFFFFF'), True)) for ch in t)
        return r'\hbox to %.3fbp{\hss\ttdir{%.3f}{%.3f}{%d}{%d}{%.3f}{%.3f}{%s}\hss}' % (
            colw, bw, bh, 1 if down else 0, 1 if hollow else 0, P, top, stack), bh

    # ── 제목(세로) ──
    def title_tex(self, T, drop=None, part=None):
        """세로 제목: 방향 표지·종류·노선·구간, 끝에 몇째 조각인지"""
        fs = self.fs
        size = 1.15
        em = size * fs
        items = []          # vbox 안에 쌓을 것
        hgt = 0.0
        def chars(s, font):
            nonlocal hgt
            c = Ctx(font, size)
            i = 0
            while i < len(s):
                ch = s[i]
                if ch in ' 　':
                    items.append(r'\kern%.3fbp' % (0.3 * em)); hgt += 0.3; i += 1; continue
                if ch in VROT:
                    t, l = self.inl.vform(ch, c, 1.3 * em)
                    items.append(t); hgt += l; i += 1; continue
                if is_latin(ch):
                    j = i
                    while j < len(s) and is_latin(s[j]): j += 1
                    run = s[i:j]
                    items.append(r'\hbox to %.3fbp{\hss\rotatebox{-90}{%s}\hss}' % (1.3 * em, self.inl.run(run, c)))
                    hgt += sum(0.62 if x.isupper() else 0.5 for x in run); i = j; continue
                items.append(r'\hbox to %.3fbp{\hss\rule[%.3fbp]{0pt}{%.3fbp}%s\hss}' % (1.3 * em, -0.12 * em, em, self.inl.run(ch, c, True)))
                hgt += 1; i += 1
        def walk(n, font):
            nonlocal hgt
            for k in n.kids:
                if isinstance(k, str):
                    t = k.replace('\n', '')
                    chars(t, font)
                elif 'jtt-dir' in k.cls:
                    down = 'jtt-dir--down' in k.cls
                    hollow = 'jtt-dir--o' in k.cls
                    t = k.text()
                    bs = 0.84 * em
                    bw = bs * (1 + 0.16)
                    bh = bs * (len(t) + 0.36 + 0.6)
                    P = 0.4 * em                          # 뾰족한 끝의 높이
                    top = (bh - P - len(t) * bs) / 2 + (0 if down else P)   # 글자는 몸통(뾰족한 끝을 뺀 곳)의 가운데에
                    stack = ''.join(r'\hbox to %.3fbp{\hss\rule[%.3fbp]{0pt}{%.3fbp}%s\hss}' % (bw, -0.12 * bs, bs, self.inl.run(ch, Ctx('GB', size * 0.84, None if hollow else 'FFFFFF'), True)) for ch in t)
                    items.append(r'\hbox to %.3fbp{\hss\ttdir{%.3f}{%.3f}{%d}{%d}{%.3f}{%.3f}{%s}\hss}' % (
                        1.3 * em, bw, bh, 1 if down else 0, 1 if hollow else 0, P, top, stack))
                    hgt += bh / em + 0.3
                    items.append(r'\kern%.3fbp' % (0.3 * em))
                elif k.cls & {'jtt-sub', 'jtt-box'}: walk(k, 'M')
                else: walk(k, font)
        walk(T.title, 'GB')
        if part:
            items.append(r'\kern%.3fbp' % (0.3 * em)); hgt += 0.3
            chars('(%s)' % part, 'M')
        return r'\vbox{\offinterlineskip ' + ''.join(items) + '}', hgt * em, (1.3 + 0.3) * em

    # ── 쪽 나누기: 펼침면 (왼쪽 면 = 제목+역명+열차, 오른쪽 면 = 열차+오른쪽 역명+제목) ──
    # ── 열 조각: 면(L=왼쪽 면, R=오른쪽 면)에 따라 역명 묶음이 다르다 ──
    def blocks(self, T):
        if not hasattr(T, 'Lc'):
            T.Lc = [j for j, k in enumerate(T.kind) if k[0] == 'L']
            T.Tc = [j for j, k in enumerate(T.kind) if k[0] == 'T']
            T.Rc = [j for j, k in enumerate(T.kind) if k[0] == 'R']
            T.mirror = not T.Rc
            if T.mirror:     # 오른쪽 역명이 없으면 왼쪽 묶음을 거울처럼
                T.Rc = [j for j in reversed(T.Lc) if T.kind[j][1] in ('st', 'ad')]
        return T.Lc, T.Tc, T.Rc

    def b_right(self, T):
        """한 쪽에 홀로 실리는 조각의 오른쪽 역명 (rightStubSingle: false 면 없앤다)"""
        return self.blocks(T)[2] if self.cfg.get('rightStubSingle', True) else []

    def fixed_w(self, T, side):
        L, _, R = self.blocks(T)
        TW = 0 if self.hang_title else self.title_tex(T)[2]
        fw = self.frame_w + self.frame_pad
        blk = sum(T.colW[j] for j in (L if side == 'L' else R if side == 'R' else L + self.b_right(T)))
        return TW + 2 * fw + blk + (self.vband_for(side) if getattr(T, 'band_left', False) else 0)

    def wide_band_w(self, scale=1.0):
        """두 줄 세로 제목칸의 폭: 글자 두 줄(굵은 노선 + 명조 구간)과 사이, 양옆 조금"""
        return ((1.3 * 1.2 + 1.3 * 0.9 + 0.15) * scale + 0.5) * self.fs

    def vband_for(self, side):
        """세로 제목칸 폭: 펼침면 짝은 왼쪽 면에만 넓게(두 줄), 오른쪽 면에는 없다. 한 쪽짜리는 보통 폭"""
        if side == 'L': return self.wide_band_w(1.0)
        if side == 'R': return 0.0
        return self.vband_w

    def cap(self, T, side, squeeze=False):
        """그 면에 실을 수 있는 열차 수. squeeze: 열 폭을 조금(squeeze 비율까지) 좁혀서"""
        P = self.P0 * (self.squeeze if squeeze else 1.0)
        return max(1, int((self.cw - self.fixed_w(T, side)) / P + 1e-6))

    def make_chunk(self, T, side, trains, avail=None, ncol=None):
        """면(side)에 실을 열차들로 조각을 만든다. avail: 조각이 쓸 폭(없으면 판면 폭).
        모자란 자리는 빈 열로 avail 끝까지, 남는 폭은 역명 칸에. 한두 편 넘치면 열 폭을 고르게 좁힌다"""
        L, Tc, R = self.blocks(T)
        room = (self.cw if avail is None else avail) - self.fixed_w(T, side)
        cap = max(1, int(room / self.P0 + 1e-6))
        n = max(len(trains), ncol or 0)        # ncol: 위아래로 맞붙은 조각과 열 수를 같게 (세로 괘선이 이어지도록)
        if n > cap:
            P = room / n
            cols, extra = list(trains) + [('G', Tc[-1], g) for g in range(n - len(trains))], 0
        else:
            P = self.P0
            cols = list(trains) + [('G', Tc[-1], g) for g in range(cap - len(trains))]
            extra = room - cap * self.P0
        keep = (L + cols) if side == 'L' else (cols + R) if side == 'R' else (L + cols + self.b_right(T))
        return {'side': side, 'cols': keep, 'trains': cols, 'extra': max(0, extra), 'mirror': T.mirror, 'P': P}

    # ── 행 자르기: 착발 두 줄 등 여러 행에 걸친 칸을 가르지 않는 자리에서만 ──
    def cut_ok(self, T):
        if not hasattr(T, 'cuts'):
            bad = set()
            for c in T.cells:
                for r in range(c.r + 1, c.r + c.rs): bad.add(r)
            T.cuts = {r for r in range(T.hEnd + 1, T.fStart) if r not in bad}
        return T.cuts

    def piece_h(self, T, rows, notes, bw=None):
        """bw: 띠의 글줄 폭(bp). 좁은 조각은 띠가 여러 줄이 되어 높아진다"""
        fw, fp = self.frame_w, self.frame_pad
        return 2 * (fw + fp) + self.headband_h(T, bw) + sum(T.rowH[r] for r in rows) + (self.notes_h(T) if notes else 0)

    def band_w(self, outer):
        """조각의 바깥 폭 → 띠 글줄 폭"""
        return outer - 2 * (self.frame_w + self.frame_pad) - 2 * self.band_inset

    def headband_h(self, T, bw=None, part=None):
        if T.head is None or getattr(T, 'band_left', False): return 0
        px = T.head.style.get('min-height') or T.head.style.get('height', '')
        m = re.match(r'([\d.]+)px', px)
        em = float(m.group(1)) / 14.4 if m else 1.5
        base = math.ceil(em * self.fs / self.R - 0.2) * self.R
        if self.cfg.get('bandRows'): base = self.cfg['bandRows'] * self.R     # 인쇄에서 띠 높이를 줄 수로 정한다
        if bw is None: return base
        plan = self.band_plan(T, bw, part or ('열넷째' if self.page_title else None))
        need = (sum(p[3] for p in plan) + 0.3) * self.fs + (len(plan) - 1) * self.band_lead
        return max(base, math.ceil(need / self.R - 1e-6) * self.R)

    def band_plan(self, T, W, part=None):
        """띠를 글줄 폭 W(bp) 안에 짠다 → 줄 목록 [(왼쪽, 가운데, 오른쪽, 높이 em)].
        한 줄에 들면 한 줄. 아니면 위 줄에 왼쪽·오른쪽, 그 아래에 가운데를 「―」 뒤에서 나누어"""
        key = (id(T), round(W, 1), part)
        if key in self._bands: return self._bands[key]
        parts, color = self.band_nodes(T)                  # 띠가 한 덩어리면 가운데에
        ctx = Ctx('DM', 1.0, color)
        fs = self.fs
        def seg(node):
            ls = self.inl.lines(node, ctx)
            ln = ls[0] if ls and ls[0] else []
            return (self.inl.flat(ln), self.inl.line_w(ln) * fs, line_height(ln) if ln else 0.0)
        L, C = seg(parts[0]), seg(parts[1])
        if part and self.page_title:          # 몇째 조각인지는 띠 오른쪽에
            ln = [('tex', self.inl.run('(%s)' % part, Ctx('M', 1.0, color)), 1.0)]
            R = (self.inl.flat(ln), self.inl.line_w(ln) * fs, line_height(ln))
        else:
            R = seg(parts[2])
        gap = 1.0 * fs
        if L[1] + C[1] + R[1] + 2 * gap <= W or not C[0]:
            plan = [(L[0], C[0], R[0], max(L[2], C[2], R[2], 1.25))]
        else:
            plan = []
            if L[0] or R[0]: plan.append((L[0], '', R[0], max(L[2], R[2], 1.25)))
            # 줄이 바뀌면 가운데(구간)는 다른 한쪽이 있는 반대편으로 민다
            al = 'r' if (L[0] and not R[0]) else 'l' if (R[0] and not L[0]) else 'c'
            for node in self.split_center(parts[1], W, ctx):
                t = seg(node)
                plan.append(('', t[0], '', max(t[2], 1.25), al))
        self._bands[key] = plan
        return plan

    def band_nodes(self, T):
        hd = T.head
        parts = [n for n in hd.kids if isinstance(n, Node)]
        if not any(n.cls & {'jtt-hl', 'jtt-hm', 'jtt-hrt'} for n in parts):
            parts = [Node('div', []), hd, Node('div', [])]
        color = None
        col = hd.style.get('color')
        if col and col.startswith('#'): color = col[1:].upper()
        if len(color or '') == 3: color = ''.join(c * 2 for c in color)
        return parts, color

    def vband(self, T, part, H, colw=None, scale=1.0):
        """띠를 세로로: 위에 방향·노선, 가운데에 주요 역, 아래에 몇째. (tex, 필요한 길이 bp)"""
        fs = self.fs
        parts, color = self.band_nodes(T)
        colw = colw or self.vband_w
        def segs(node, ctx, out):
            for k in node.kids:
                if isinstance(k, str):
                    t = k.replace('\n', '')
                    if t: out.append((t, ctx))
                    continue
                if k.tag == 'br': out.append((' ', ctx)); continue
                c2 = ctx
                if 'jtt-b' in k.cls: c2 = c2.but(font='GB', size=c2.size * 1.2)
                elif 'jtt-k' in k.cls: c2 = c2.but(font='GB')
                if 'jtt-lit' in k.cls and c2.font != 'GB': c2 = c2.but(font='M')
                segs(k, c2, out)
            return out
        def stack(sg, cw=None):
            cw = cw or colw
            items, L = [], 0.0
            for text, c in sg:
                em = c.size * fs
                i = 0
                while i < len(text):
                    ch = text[i]
                    if ch in ' \u00a0　':
                        kk = 0.55 if text[i + 1:i + 2] in ('〔', '（') else 0.35
                        items.append(r'\kern%.3fbp' % (kk * em)); L += kk * em; i += 1; continue
                    if ch in VROT:
                        t, l = self.inl.vform(ch, c, cw)
                        items.append(t); L += l * em; i += 1; continue
                    if ch.isdigit():                  # 쪽 번호 등 두 자리까지: 세로 안에 가로로 세워(縦中横) 한 칸에
                        j = i
                        while j < len(text) and text[j].isdigit(): j += 1
                        if j - i <= 2:
                            items.append(r'\hbox to %.3fbp{\hss\rule[%.3fbp]{0pt}{%.3fbp}%s\hss}' % (cw, -0.12 * em, em, self.inl.run(text[i:j], c, True)))
                            L += em; i = j; continue
                    if is_latin(ch):
                        j = i
                        while j < len(text) and is_latin(text[j]): j += 1
                        run = text[i:j]
                        items.append(r'\hbox to %.3fbp{\hss\rotatebox{-90}{%s}\hss}' % (cw, self.inl.run(run, c)))
                        L += sum(0.62 if x.isupper() else 0.5 for x in run) * em; i = j; continue
                    items.append(r'\hbox to %.3fbp{\hss\rule[%.3fbp]{0pt}{%.3fbp}%s\hss}' % (cw, -0.12 * em, em, self.inl.run(ch, c, True)))
                    L += em; i += 1
            return ''.join(items), L
        base = Ctx('DM', scale, color)
        # 이름(노선)과 방향: 띠 왼쪽 부분에서 〔하행〕 앞까지가 이름, 방향은 모듈의 방향 표지(하행 속 빈·상행 속 찬)로
        sg0 = segs(parts[0], base, [])            # 노선 〔하행〕 (방향은 명조 괄호 그대로)
        mdir = None
        route = re.sub(r'\s+', ' ', parts[1].text()).strip().strip('（）()')
        two = colw >= 3.0 * fs * scale             # 넓은 칸: 두 줄 (오른쪽 줄이 먼저)
        cw = colw / 2 if two else colw
        # 두 줄일 때 줄 사이는 글자 크기만큼만 (칸 폭을 반씩 나누면 행간이 너무 벌어진다)
        cwA = 1.3 * 1.2 * scale * fs if two else cw
        cwB = 1.3 * 0.9 * scale * fs if two else cw
        a, la = stack(sg0, cwA)
        if mdir:
            bt, bh = self.dir_badge(mdir.group(1), mdir.group(1) == '하행', mdir.group(1) == '하행', scale * 0.9, cw)
            a += r'\kern%.3fbp' % (0.4 * fs * scale) + bt; la += bh + 0.4 * fs * scale
        rc = Ctx('M', scale * (0.9 if two else 0.85), color)
        b, lb = stack([('（%s）' % route, rc)], cwB) if route else ('', 0.0)
        if part: c, lc = stack([('(%s)' % part, Ctx('M', scale * 0.9, color))], cwA)
        else: c, lc = '', 0.0
        if two:
            need = max(la + lc, lb) + fs * scale
            if lb > H: b = ''
            # 오른쪽 줄(먼저 읽는 줄)에 구간, 왼쪽 줄에 노선·방향·몇째
            # 왼쪽 줄은 노선·방향과 몇째를 한 덩어리로 가운데에
            right = r'\vbox to %.3fbp{\offinterlineskip\vfil %s\vfil}' % (H, b)
            left = r'\vbox to %.3fbp{\offinterlineskip\vfil %s%s%s\vfil}' % (H, a, (r'\kern%.3fbp' % (0.6 * fs * scale)) if c else '', c)
            tex = r'\hbox to %.3fbp{\hss %s\kern%.3fbp %s\hss}' % (colw, left, 0.15 * fs * scale, right)
        else:
            need = la + lb + lc + 2 * fs * scale
            if need > H and la + lc + fs <= H:      # 길이가 모자라면 구간은 뺀다
                b = ''
            k_ = r'\kern%.3fbp' % (0.8 * fs * scale)
            tex = r'\vbox to %.3fbp{\offinterlineskip\vfil %s%s%s%s%s\vfil}' % (H, a, k_ if b else '', b, k_ if c else '', c)
        return tex, need

    def split_center(self, node, W, ctx):
        """띠 가운데(주요 역을 「―」로 이은 것)를 폭 W 안에 드는 줄들로. 글이 한 토막일 때만 나눈다"""
        holders = []
        def find(n, path):
            for i, k in enumerate(n.kids):
                if isinstance(k, str):
                    if k.strip(): holders.append(path + [i])
                else: find(k, path + [i])
        find(node, [])
        if len(holders) != 1: return [node]
        path = holders[0]
        def at(n):
            for i in path[:-1]: n = n.kids[i]
            return n
        text = at(node).kids[path[-1]]
        toks = [t.strip(' \u00a0\n') for t in re.findall(r'[^―]+―?', text)]
        toks = [t for t in toks if t]
        if len(toks) <= 1: return [node]
        def make(t):
            n2 = copy.deepcopy(node)
            at(n2).kids[path[-1]] = t
            return n2
        def width(t):
            ls = self.inl.lines(make(t), ctx)
            return self.inl.line_w(ls[0] if ls else []) * self.fs
        out, cur = [], toks[0]
        for t in toks[1:]:
            cand = cur + ' ' + t
            if width(cand) <= W: cur = cand
            else: out.append(cur); cur = t
        out.append(cur)
        return [make(t) for t in out]

    def notes_h(self, T):
        if T.notes is None: return 0
        n = len([k for k in T.notes.kids if isinstance(k, Node)])
        return (n * 1.35 * 0.8 + 0.5) * self.fs

    # ── 표 조각 하나를 쪽에 ──
    def render_piece(self, T, ch, rows, x0, y0, with_notes, notes_room=True, line=None, part=None, hb=None, pc=None):
        """x0,y0: 조각 왼쪽 위 (쪽 좌표, 위에서 아래로). 그릴 것 목록과 크기를 돌려준다"""
        fs = self.fs
        tex, rects = [], []
        side = ch['side']
        self.cur_mirror = ch.get('mirror', False)
        ttl, ttlH, TW = self.title_tex(T, line, part)
        fw, fp = self.frame_w, self.frame_pad
        # 열 x 위치
        cols = ch['cols']
        widths = [ch['P'] if (isinstance(j, tuple) or T.kind[j][0] == 'T') and 'P' in ch else width_of(T, j) for j in cols]
        # 남는 폭을 역명 칸에
        if ch['extra'] > 0:
            tgt = None
            for idx, j in enumerate(cols):
                if kind_of(T, j)[0] in ('L', 'R') and kind_of(T, j)[1] == 'st':
                    tgt = idx
                    if side != 'R': break
            if tgt is not None: widths[tgt] += ch['extra']
        if self.hang_title: tx = x0           # 제목은 판면 밖(바깥 여백)에
        else: tx = x0 + (TW if side != 'R' else 0)
        fx0 = tx
        VB = (pc.get('vbw') if pc and pc.get('vbw') else self.vband_for(side)) if getattr(T, 'band_left', False) else 0     # 세로 띠 (펼침면 짝은 왼쪽 면에만)
        vsc = (pc.get('vbscale') or 1.0) if pc else 1.0
        xs = [tx + fw + fp + (VB if side != 'R' else 0)]
        for w in widths: xs.append(xs[-1] + w)
        fx1 = xs[-1] + (VB if side == 'R' else 0) + fp + fw
        # 행 y 위치
        hb = self.headband_h(T, xs[-1] - xs[0] - 2 * self.band_inset, part) if hb is None else hb
        ty = y0 + fw + fp
        ys = [ty + hb]
        for r in rows: ys.append(ys[-1] + T.rowH[r])
        if pc and pc.get('stretch'): ys[-1] += pc['stretch']          # 쪽의 남는 자리를 비고 행이 받는다
        nh = self.notes_h(T) if with_notes else 0
        fy1 = ys[-1] + nh + fp + fw
        # 틀: 왼쪽·오른쪽 변은 굵게. 위 변은 위에 붙은 조각에 따라(같은 표면 띠 사이 괘선, 다른 표면 표 사이 괘선)
        top = pc['top'] if pc else 'frame'
        bottom = pc['bottom'] if pc else True
        VB0 = VB
        rects.append(('v', fx0 + fw / 2, y0, fy1, 2)); rects.append(('v', fx1 - fw / 2, y0, fy1, 2))
        if top == 'frame': rects.append(('h', fx0, fx1, y0 + fw / 2, 2))
        elif top == 'table': rects.append(('h', fx0, fx1, y0 + fw / 2, self.table_rule))
        else:
            # 같은 표: 제목칸은 끊지 않는다
            lx = (fx0 + fw + fp + VB0) if (VB0 and side != 'R') else fx0
            rx = (fx1 - fw - fp - VB0) if (VB0 and side == 'R') else fx1
            rects.append(('h', lx, rx, y0 + fw / 2, self.strip_rule))
        if bottom: rects.append(('h', fx0, fx1, fy1 - fw / 2, 2))
        # 제목 (쪽마다 하나만 다는 경우에는 표마다 달지 않는다)
        if self.page_title: pass
        elif side == 'R':
            tex.append(self.put_box(fx1 + 0.3 * fs, y0, TW - 0.3 * fs, ttlH, ttl, 'l', 't'))
        else:
            tex.append(self.put_box(tx - TW if self.hang_title else x0, y0, TW - 0.3 * fs, ttlH, ttl, 'l', 't'))
        # 세로 띠
        if VB:
            # 제목칸: 틀 안쪽 끝 ~ 세로 괘선 사이(틀과 표 사이 여백까지)의 가운데에
            bx = fx0 + fw if side != 'R' else xs[-1]
            VBc = VB + fp
            run = pc and pc.get('vrun')
            if run and run[2] > 1:            # 같은 표의 띠 여럿에 걸친 제목칸: 첫 띠에서 한 번에
                if run[0] == 0:
                    Hh = run[1] - 2 * (fw + fp) - 2 * self.vpad
                    vt, _ = self.vband(T, pc.get('vrun_part') or None, Hh, VB, vsc)
                    tex.append(self.put_box(bx, ty + self.vpad, VBc, Hh, vt, 'c', 't'))
                y_a = y0 if run[0] > 0 else ty
                y_b = fy1 if run[0] < run[2] - 1 else ys[-1]
                rects.append(('v', xs[0] if side != 'R' else xs[-1], y_a, y_b, 1))
            else:
                vt, _ = self.vband(T, part, ys[-1] - ty - 2 * self.vpad, VB, vsc)
                tex.append(self.put_box(bx, ty + self.vpad, VBc, ys[-1] - ty - 2 * self.vpad, vt, 'c', 't'))
                rects.append(('v', xs[0] if side != 'R' else xs[-1], ty, ys[-1], 1))
        # 노선 머리띠
        if hb:
            W = xs[-1] - xs[0] - 2 * self.band_inset
            plan = self.band_plan(T, W, part)
            def row(l, c, r, h, al='c'):
                st = strut(h / 1.25, fs)
                if c and not (l or r):
                    return r'\hbox to %.3fbp{%s%s %s%s}' % (W, st, '' if al == 'l' else r'\hss', c, '' if al == 'r' else r'\hss')
                if not c: return r'\hbox to %.3fbp{%s%s\hskip 1em plus 1fill %s}' % (W, st, l, r)
                # 왼쪽(방향·노선)·가운데(주요 역)·오른쪽(몇째)을 한 줄에. 사이를 늘이고 줄여 가운데를 맞춘다
                return r'\hbox to %.3fbp{%s%s\hskip 1em plus 1fill %s\hskip 1em plus 1fill %s}' % (W, st, l, c, r)
            # 틀 안쪽 끝에서 띠 아래 괘선까지의 가운데에 (틀과 표 사이 여백도 띠의 일부로 보인다)
            space = ty + hb - (y0 + fw)
            if len(plan) == 1:
                tex.append(self.put_box(xs[0] + self.band_inset, y0 + fw, W, space, row(*plan[0]), 'l', 'm'))
            else:
                tot = sum(p[3] for p in plan) * fs + (len(plan) - 1) * self.band_lead
                box = r'\vbox{\offinterlineskip %s}' % (r'\kern%.3fbp ' % self.band_lead).join(row(*p) for p in plan)
                tex.append(self.put_box(xs[0] + self.band_inset, y0 + fw + (space - tot) / 2, W, tot, box, 'l', 't'))
            rects.append(self.hrule(xs[0], xs[-1], ty + hb, 1))
        # 칸
        rowpos = {r: i for i, r in enumerate(rows)}
        colpos = {j: i for i, j in enumerate(cols)}
        if side in ('R', 'B') and self.cur_mirror:
            pass
        seen = set()
        for r in rows:
            for j in cols:
                cell = cell_of(T, r, j)
                if cell is None or id(cell) in seen: continue
                if isinstance(cell, Ghost):
                    seen.add(id(cell))
                    if T.hEnd <= r < T.fStart and r in rowpos:     # 빈 열의 역 행: ‥
                        ci = colpos[j]; ri = rowpos[r]
                        g = self.inl.run('‥', Ctx('DM'))
                        tex.append(self.put_box(xs[ci], ys[ri], xs[ci + 1] - xs[ci], ys[ri + 1] - ys[ri],
                                                r'\hbox to %.3fbp{%s\hss %s\hss}' % (xs[ci + 1] - xs[ci], strut(1.0, fs), g), 'l', 'm'))
                    continue
                seen.add(id(cell))
                rr = [x for x in range(cell.r, cell.r + cell.rs) if x in rowpos]
                cc = [x for x in range(cell.c, cell.c + cell.cs) if x in colpos]
                if not rr or not cc: continue
                ri0, ri1 = rowpos[rr[0]], rowpos[rr[-1]]
                ci0, ci1 = min(colpos[x] for x in cc), max(colpos[x] for x in cc)
                cx, cy = xs[ci0], ys[ri0]
                cw, chh = xs[ci1 + 1] - cx, ys[ri1 + 1] - cy
                self.draw_cell(T, cell, cx, cy, cw, chh, tex)
        # 괘선
        rects += self.grid_rules(T, rows, cols, xs, ys, side)
        # 주기
        if with_notes and T.notes is not None:
            rects.append(self.hrule(xs[0], xs[-1], ys[-1], 1))
            body = []
            for d in [k for k in T.notes.kids if isinstance(k, Node)]:
                ls = self.inl.lines(d, Ctx('DM', 0.8))
                body.append(self.inl.flat(ls[0]))
            W = xs[-1] - xs[0] - fs
            par = r'\vbox{\hsize=%.3fbp\parindent0pt\raggedright\baselineskip=%.3fbp %s}' % (
                W, 1.35 * 0.8 * fs, r'\par '.join(body))
            tex.append(self.put_box(xs[0] + 0.5 * fs, ys[-1] + 0.25 * fs, W, nh - 0.25 * fs, par, 'l', 't'))
        return tex, rects, (fx1 - x0 + (TW if side == 'R' else 0)), fy1 - y0

    def draw_cell(self, T, cell, x, y, w, h, tex):
        fs = self.fs
        cls, st = cell.cls, cell.style
        rc = T.rowcls[cell.r]
        if not cell.lines: return
        # 여백
        pad = 0.15
        if 'jtt-st' in cls or 'jtt-r-st' in cls: pad = 0.3
        if 'jtt-ad' in cls: pad = 0.0
        if 'jtt-rc' in cls: pad = 0.2 if 'jtt-r-st' not in cls else 0.3
        if 'jtt-th' in cls: pad = 0.4
        # 가로 맞춤
        al = 'r'
        if 'jtt-st' in cls or 'jtt-r-st' in cls: al = 'l'
        if cls & {'jtt-ad', 'jtt-rc', 'jtt-c', 'jtt-th'}: al = 'c'
        if 'jtt-r-st' in cls and 'jtt-th' not in cls: al = 'l'
        if 'jtt-t' in cls and rc & {'jtt-hr', 'jtt-f1', 'jtt-fr'}: al = 'c'
        ta = st.get('text-align')
        if ta: al = {'left': 'l', 'right': 'r', 'center': 'c'}.get(ta, al)
        va = {'top': 't', 'bottom': 'b', 'middle': 'm'}.get(st.get('vertical-align', 'middle'), 'm')
        W = w - 2 * pad * fs
        lts = []
        jn = None
        m = re.match(r'(\d+)', st.get('--jtt-jn', ''))
        if 'jtt-jn' in cls and m: jn = int(m.group(1))
        sqc = al == 'c'
        for ln in cell.lines:
            if not ln: continue
            t = None
            if 'jtt-th' in cls and len(ln) == 1 and ln[0][0] == 'just':
                if jn: t = just_th(ln, W, jn, fs)
                else:   # space-evenly
                    chars = ln[0][1]
                    t = r'\hbox to %.3fbp{%s\hfill %s\hfill}' % (W, strut(ln[0][2], fs), r'\hfill '.join(chars))
            if t is None:
                # 열차 번호(네 자리)는 괘선에 닿지 않게 양옆을 조금 더 비운다
                pe = 0.2 if cell.node.find(lambda n: 'jtt-no' in n.cls) else 0.06
                t = line_tex(ln, W, al, fs, self.inl, sqc, pe)
            if t: lts.append(t)
        if not lts: return
        has_v = any(it[0] == 'obj' and len(it) > 5 for ln in cell.lines for it in ln)
        vmargin = 0
        if has_v:
            vmargin = (0.2 if rc & {'jtt-f1', 'jtt-fr'} else 0.1) * fs
        if cell.node.find(lambda n: 'tt-darrow' in n.cls): vmargin = 0.1 * fs  # 이어짐 화살표는 위 괘선 가까이
        box = r'\vbox{\offinterlineskip %s}' % ''.join(lts)
        tex.append(self.put_box(x + pad * fs, y + (vmargin if va == 't' else 0), W, h - (vmargin if va in 't' else 0) - (vmargin if va == 'b' else 0), box, 'l', va))

    def put_box(self, x, y, w, h, content, al, va):
        """쪽 좌표(위→아래) 의 (x,y,w,h) 칸에 content 를 놓는다"""
        Y = self.H - (y + h)
        pos = {'t': 't', 'b': 'b', 'm': ''}[va] + {'l': 'l', 'r': 'r', 'c': ''}[al]
        return r'\put(%.3f,%.3f){\makebox(%.3f,%.3f)[%s]{%s}}' % (x, Y, w, h, pos, content)

    # ── 괘선 ──
    def hrule(self, x0, x1, y, w):
        return ('h', x0, x1, y, w)

    def frame_rects(self, x0, y0, x1, y1, t):
        return [('box', x0, y0, x1, y1, t)]

    def grid_rules(self, T, rows, cols, xs, ys, side):
        nR, nC = len(rows), len(cols)
        mir = side in ('R', 'B') and self.cur_mirror
        lastT = max((k for k, j in enumerate(cols) if kind_of(T, j)[0] == 'T'), default=-1)
        def cell_at(i, k): return cell_of(T, rows[i], cols[k])
        out = []
        # 세로선: 열 사이 k (1..nC-1), 행 i
        for k in range(1, nC):
            seg = None
            for i in range(nR):
                a, b = cell_at(i, k - 1), cell_at(i, k)
                w = 0
                if a is not None and b is not None and a is not b:
                    la, ra, _, _ = self.borders(T, a)
                    lb, rb, _, _ = self.borders(T, b)
                    if mir and k > lastT and kind_of(T, cols[k - 1])[0] == 'T': w = 2
                    elif mir and k > lastT: w = wmax(la, rb)
                    else: w = wmax(ra, lb)
                y0, y1 = ys[i], ys[i + 1]
                if seg and seg[0] == w and abs(seg[2] - y0) < 0.01: seg[2] = y1
                else:
                    if seg and seg[0]: out.append(('v', xs[k], seg[1], seg[2], seg[0]))
                    seg = [w, y0, y1]
            if seg and seg[0]: out.append(('v', xs[k], seg[1], seg[2], seg[0]))
        # 가로선: 행 사이 i (1..nR-1)
        for i in range(1, nR):
            seg = None
            band_start = rows[i - 1] == T.hEnd - 1 and rows[i] != T.hEnd
            for k in range(nC):
                a, b = cell_at(i - 1, k), cell_at(i, k)
                w = 0
                if a is not None and b is not None and a is not b:
                    _, _, _, ba = self.borders(T, a)
                    _, _, tb, _ = self.borders(T, b)
                    w = wmax(ba, tb)
                    if band_start: w = 'd'
                    elif rows[i] != rows[i - 1] + 1 and w == 0: w = 1
                x0, x1 = xs[k], xs[k + 1]
                if seg and seg[0] == w and abs(seg[2] - x0) < 0.01: seg[2] = x1
                else:
                    if seg and seg[0]: out.append(('h', seg[1], seg[2], ys[i], seg[0]))
                    seg = [w, x0, x1]
            if seg and seg[0]: out.append(('h', seg[1], seg[2], ys[i], seg[0]))
        return out

    def pdf_ops(self, rects):
        ops = []
        H = self.H
        def rect(x, y, w, h):          # 위→아래 좌표
            ops.append('%.3f %.3f %.3f %.3f re' % (x, H - y - h, w, h))
        for r in rects:
            if r[0] == 'h':
                _, x0, x1, y, w = r
                if w == 'd':
                    t, g = self.dbl
                    off = (g + t) / 2
                    rect(x0, y - off - t / 2, x1 - x0, t)
                    rect(x0, y + off - t / 2, x1 - x0, t)
                else:
                    t = self.rw[w]
                    rect(x0, y - t / 2, x1 - x0, t)
            elif r[0] == 'v':
                _, x, y0, y1, w = r
                if w == 'd':
                    t, g = self.dbl
                    off = (g + t) / 2
                    rect(x - off - t / 2, y0, t, y1 - y0); rect(x + off - t / 2, y0, t, y1 - y0)
                else:
                    t = self.rw[w]
                    rect(x - t / 2, y0, t, y1 - y0)
            elif r[0] == 'box':
                _, x0, y0, x1, y1, t = r
                rect(x0, y0, x1 - x0, t); rect(x0, y1 - t, x1 - x0, t)
                rect(x0, y0, t, y1 - y0); rect(x1 - t, y0, t, y1 - y0)
        return '0 g ' + ' '.join(ops) + ' f'

    # ── 글꼴 정의: 이름이 아니라 찾아 둔 파일로 (TeX 쪽 이름 찾기에 기대지 않는다) ──
    FAMILIES = [  # 명령, 주 글꼴, 대체 글꼴들, 추가 기능
        ('M', 'mincho', ['minchoKo', 'dia'], ''),
        ('DM', 'dia', ['mincho', 'minchoKo'], ';-liga;-ccmp'),
        ('DG', 'dia', ['gothic', 'gothicKo'], ';-liga;-ccmp'),
        ('DGB', 'dia', ['gothicBold', 'gothicKoBold'], ';-liga;-ccmp;+titl'),
        ('GB', 'gothicBold', ['gothicKoBold', 'dia'], ''),
        ('G', 'gothic', ['gothicKo', 'dia'], ''),
        ('KM', 'minchoKo', ['mincho', 'dia'], ''),
        ('KG', 'gothicKo', ['gothic', 'dia'], ''),
        ('KGB', 'gothicKoBold', ['gothicBold', 'dia'], ''),
        ('FO', 'folio', ['gothicBold', 'gothicKoBold'], ''),      # 쪽 번호 (Univers 등)
    ]
    OPTIONAL = {'FO': 'GB'}
    def fontdefs(self):
        info = self.metrics.info
        # 파일 이름에 빈칸·한자 등이 있으면 fontspec 이 이름을 망가뜨리므로, 빈칸 없는 이름의 링크를 만들어 쓴다
        linkdir = os.path.join(HERE, 'build', 'fontlinks')
        os.makedirs(linkdir, exist_ok=True)
        def safe(path):
            fn = os.path.basename(path)
            if re.fullmatch(r'[A-Za-z0-9._-]+', fn): return path
            import hashlib
            ext = os.path.splitext(fn)[1].lower()
            dst = os.path.join(linkdir, 'f' + hashlib.md5(path.encode()).hexdigest()[:10] + ext)
            if not os.path.exists(dst):
                try: os.symlink(path, dst)
                except OSError:
                    import shutil; shutil.copyfile(path, dst)
            return dst
        for fi in info.values():
            if fi and not hasattr(fi, 'tex_path'): fi.tex_path = safe(fi.path)
        def fb(role):
            fi = info.get(role)
            if not fi: return None
            sub = '(%d)' % fi.idx if fi.path.lower().endswith(('.ttc', '.otc')) else ''
            return '[%s]%s:mode=node;' % (fi.tex_path.replace('\\', '/'), sub)
        lua, tex = [], []
        for cmd, main, fbs, feat in self.FAMILIES:
            fi = info.get(main)
            if not fi and cmd in self.OPTIONAL:          # 없으면 다른 글꼴 묶음으로 대신
                tex.append(r'\let\f%s\f%s' % (cmd, self.OPTIONAL[cmd])); continue
            if not fi: raise SystemExit('font not found: %s = %s' % (main, self.fonts.get(main)))
            lst = [x for x in (fb(r) for r in fbs) if x]
            lua.append('luaotfload.add_fallback("fb%s", {%s})' % (cmd, ', '.join('"%s"' % x for x in lst)))
            d, fn = os.path.split(fi.tex_path)
            tex.append(r'\newfontfamily\f%s{%s}[Path=%s/, FontIndex=%d, RawFeature={fallback=fb%s%s}]' % (cmd, fn, d, fi.idx, cmd, feat))
        return '\\directlua{\n' + '\n'.join(lua) + '\n}\n' + '\n'.join(tex)

    # ── 머리글·쪽 번호 ──
    def page_side_title(self, recto, lines, dirs=None):
        """쪽의 노선 이름: 바깥 여백에 세로로 크게 (쪽마다 하나)"""
        if not lines: return []
        size = self.cfg.get('pageTitleSize', 10) / self.fs
        em = size * self.fs
        c = Ctx('GB', size)
        cd = Ctx('M', size * 0.8)                  # 방향(하행·상행)은 명조로 작게
        items = []
        dirs = dirs or {}
        def dmark(key):
            d = dirs.get(key, set())
            if len(d) != 1 or '' in d: return []
            return [(next(iter(d)), 'DIR')]           # 쪽에 한 방향만: 모듈의 방향 표지(오각형)
        # KTX 표의 노선은 「KTX 경부선·호남선」으로 묶는다. 쪽에 한 방향만 실렸으면 노선 이름 뒤에 그 방향을
        segs_all = []
        ktx = [(k, ln) for k, ln in lines if k == 'KTX']
        if ktx:
            sg = [('KTX ', c)]
            for i, key in enumerate(ktx):
                if i: sg.append(('·', c))
                sg += [(key[1], c)] + dmark(key)
            segs_all.append(sg)
        for key in [x for x in lines if x[0] != 'KTX']:
            segs_all.append([(key[1], c)] + dmark(key))
        dot = lambda: items.append(r'\kern%.3fbp\hbox to %.3fbp{\hss\rule[%.3fbp]{0pt}{%.3fbp}%s\hss}\kern%.3fbp' % (
            0.2 * em, 1.2 * em, -0.12 * em, em, self.inl.run('·', c, True), 0.2 * em))
        for k, sg in enumerate(segs_all):
            if k: dot()
            for ln, cc in sg:
                if cc == 'DIR':
                    t_, _ = self.dir_badge(ln, ln == '하행', ln == '하행', size * 0.8, 1.2 * em)   # 하행은 속이 빈, 상행은 속이 찬
                    items.append(r'\kern%.3fbp' % (0.6 * em)); items.append(t_)
                    continue
                e2 = cc.size * self.fs
                if cc is cd: items.append(r'\kern%.3fbp' % (0.15 * em))
                i = 0
                while i < len(ln):
                    ch = ln[i]
                    if ch == ' ':
                        items.append(r'\kern%.3fbp' % (0.3 * em)); i += 1; continue
                    if ch == '·': dot(); i += 1; continue
                    if ch in VROT:
                        t, l = self.inl.vform(ch, cc, 1.2 * em)
                        items.append(t); i += 1; continue
                    if is_latin(ch):          # 로마자는 눕혀서
                        j = i
                        while j < len(ln) and is_latin(ln[j]) and ln[j] != ' ': j += 1
                        items.append(r'\hbox to %.3fbp{\hss\rotatebox{-90}{%s}\hss}' % (1.2 * em, self.inl.run(ln[i:j], cc)))
                        i = j; continue
                    items.append(r'\hbox to %.3fbp{\hss\rule[%.3fbp]{0pt}{%.3fbp}%s\hss}' % (1.2 * em, -0.12 * e2, e2, self.inl.run(ch, cc, True)))
                    i += 1
        box = r'\vbox{\offinterlineskip ' + ''.join(items) + '}'
        gapm = 1.0 * MM
        if recto: x = self.mi + self.cw + gapm
        else: x = self.mo - gapm - 1.2 * em
        return [self.put_box(x, self.mt, 1.2 * em, 10, box, 'l', 't')]

    def page_legend(self, tables):
        """그 쪽에 실린 표들의 기호 해설(표의 주기)을 모은다. 같은 것·다른 것에 들어 있는 것은 뺀다"""
        items = []
        for T in tables:
            nd = getattr(T, 'legend', None)
            if nd is None: continue
            for d in [k for k in nd.kids if isinstance(k, Node)]:
                t = re.sub(r'\s+', ' ', d.text()).strip()
                if t and all(t != x[0] for x in items): items.append((t, d))
        items = [(t, d) for t, d in items if not any(t != u and t in u for u, _ in items)]
        rank = lambda t: 0 if t.startswith(('차종', '등급')) else 1 if '운행' in t else 2   # 첫 줄에 차종·운행일, 그 밖은 다음 줄
        return [d for t, d in sorted(items, key=lambda x: rank(x[0]))]

    def page_furniture(self, folio, recto, runhead, part, legend=None):
        fs = self.fs
        tex = []
        x0 = self.mi if recto else self.mo
        base_y = self.mt - self.cfg.get('headGap', 3.5) * MM     # 머리글·쪽 번호의 글줄 ~ 판면 위 끝
        Y = self.H - base_y
        rh = self.inl.run(runhead, Ctx('GB', 8.5 / fs)) if runhead else ''
        if part:
            rh += r'\ ' + self.inl.run('(%s)' % part, Ctx('M', 8.5 / fs))
        fo = self.inl.run(str(folio), Ctx('FO', 13 / fs))
        Yr = Y + 0.37 * (13 - 8.5)     # 머리글 글줄을 쪽 번호의 가운데 높이로
        if recto:
            tex.append(r'\put(%.3f,%.3f){\llap{%s}}' % (x0 + self.cw - 12 * MM, Yr, rh))
            tex.append(r'\put(%.3f,%.3f){\llap{%s}}' % (x0 + self.cw, Y, fo))
        else:
            tex.append(r'\put(%.3f,%.3f){\rlap{%s}}' % (x0 + 12 * MM, Yr, rh))
            tex.append(r'\put(%.3f,%.3f){\rlap{%s}}' % (x0, Y, fo))
        # 기호 해설: 쪽 번호 안쪽에 작은 글씨로 (두 줄 남짓). 끝 줄을 쪽 번호의 글줄에 맞춘다
        if legend:
            sz = self.cfg.get('legendSize', 5.0) / fs
            parts = [self.inl.flat(self.inl.lines(d, Ctx('M', sz))[0]) for d in legend]
            fw_ = (self.inl.wc.get(fo, 2.0)) * fs
            gap = 3 * MM
            W = self.cw - fw_ - gap
            # 두 줄이 되면 두 줄로: 항목을 앞뒤 반으로 나눠 줄을 바꾼다
            if len(parts) >= 2:
                h_ = -(-len(parts) // 2)
                rk = [0 if re.match(r'\s*(차종|등급)', d.text()) else 1 if '운행' in d.text() else 2 for d in legend]
                if 2 in rk and rk.count(2) < len(rk): h_ = rk.index(2)     # 그 밖의 해설(병결 등)은 둘째 줄로
                body = r'\hskip 1em plus 0.5em '.join(r'\mbox{%s}' % p for p in parts[:h_]) + r'\\' + \
                       r'\hskip 1em plus 0.5em '.join(r'\mbox{%s}' % p for p in parts[h_:])
            else:
                body = r'\mbox{%s}' % parts[0]
            box = r'\parbox[b]{%.3fbp}{\fontsize{%.3fbp}{%.3fbp}\selectfont%s %s}' % (
                W, sz * fs, sz * fs * 1.3, r'\raggedleft' if recto else r'\raggedright', body)
            if recto: tex.append(r'\put(%.3f,%.3f){%s}' % (x0, Y, box))
            else: tex.append(r'\put(%.3f,%.3f){%s}' % (x0 + fw_ + gap, Y, box))
        return tex

    # ── 표 읽기 ──
    def load_tables(self, item):
        src = item['src'] if os.path.isabs(item['src']) else os.path.join(self.base, item['src'])
        text = open(src, encoding='utf-8').read()
        blocks = invoke_blocks(text)
        idxs = [item['idx']] if 'idx' in item else range(len(blocks))
        out = []
        for i in idxs:
            html = run_module(blocks[i], os.path.join(HERE, 'src', 'Timetable.lua'), os.path.join(HERE, 'build'))
            wrap = parse_html(html).find(lambda n: 'jtt-wrap' in n.cls)
            T = build_table(wrap)
            self.prepare(T)
            T.line = item.get('line') or os.path.splitext(os.path.basename(src))[0]
            if self.notes is not True: T.legend, T.notes = T.notes, None     # 표 밑 주기 대신 (notes: 'header' 면 쪽 머리에)
            out.append(T)
        return out

    # ── 짜기: 쪽을 차례로 위에서부터 채운다 ──
    #  · 표 조각은 언제나 '열차 무리 × 역 구간' 하나를 통째로. 남은 자리를 채우려고 역 중간에서 자르지 않는다
    #    (한 단에는 늘 그 구간의 역이 처음부터 끝까지 다 있다. 같은 표의 다음 무리는 그 밑 단이나 다음 쪽에)
    #  · 한 쪽에 들지 않을 만큼 역이 많은 표만 역 구간으로 나눈다. 고르게, 구획 선(---) 자리에서.
    #    그때는 구간 먼저: 첫 구간의 모든 열차 → 다음 구간의 모든 열차 (실제 시각표처럼)
    #  · 열차 무리: 한 면 폭에 드는 것은 한 면(single), 넓은 것은 이어지는 두 쪽에 나눠 싣는 짝(pair).
    #    짝이 왼쪽 면에서 시작하면 펼침면 두 쪽에(높이가 비슷하면 같은 높이로, 행이 맞는다),
    #    왼쪽 면이 찼고 오른쪽 면이 비었으면 오른쪽 면에서 시작해 넘겨 다음 왼쪽 면으로.
    #    끝에 몇 편만 남으면 열 폭을 조금(squeeze) 좁혀 앞 무리에 싣는다
    #  · 좁은 표(한 면을 다 채우지 않는 것)는 앞의 좁은 표 옆에 나란히 (하행 | 상행)
    #  · 읽는 차례를 지킨다: 앞 쪽의 빈자리로 되돌아가 채우지 않는다
    def is_ktx(self, T):
        t = (T.title.text() if T.title is not None else '') + (T.head.text() if T.head is not None else '')
        return 'KTX' in t

    def redundant_ends(self, T):
        """시발역·종착역 행이 표 안의 시각과 겹치면(모든 열차가 표에 실린 역에서 떠나고 닿으면) 그 행들.
        접어 실을 때만 뺀다 (첫 시각·끝 시각과 끝남 표시 ═ 로 알 수 있다)"""
        if hasattr(T, '_drop'): return T._drop
        names = set()
        for cl in T.cells:
            if T.hEnd <= cl.r < T.fStart and cl.c == 0:
                names.add(re.sub(r'\s', '', cl.node.text()))
        drop = set()
        for label in ('시발역', '종착역'):
            rows = {cl.r for cl in T.cells if cl.c == 0 and re.sub(r'\s', '', cl.node.text()) == label}
            if not rows: continue
            ok = True
            for cl in T.cells:
                if cl.r in rows and cl.c > 0 and T.kind[cl.c][0] == 'T':
                    nm = re.sub(r'[\d\s:.]', '', cl.node.text())
                    if nm and nm not in names: ok = False; break
            if ok: drop |= rows
        T._drop = drop
        return drop

    def split_lr(self, T, k):
        """펼침면 한 벌에 k 편: 왼쪽 면을 먼저 채우고 나머지를 오른쪽 면에 (빈 열은 펼침면 끝에 모인다)"""
        return min(self.cap(T, 'L', True), k)          # 왼쪽 면(첫째)부터 가득 (열 폭을 조금 좁혀서라도)

    def stack_parts(self, T, G):
        """펼침면 G 개에 앞에서부터 채운 열차 무리: [(왼쪽 면 열차, 오른쪽 면 열차)] (빈 열은 끝에만)"""
        _, Tc, _ = self.blocks(T)
        n = len(Tc)
        C = self.cap(T, 'L', True) + self.cap(T, 'R', True)     # 앞 펼침면부터 가득
        out, ti = [], 0
        for g in range(G):
            k = min(C, n - ti)
            kA = self.split_lr(T, k)
            out.append((Tc[ti:ti + kA], Tc[ti + kA:ti + k])); ti += k
        return out

    def stack_jobs(self, Td, Tu):
        """하행을 위 단, 상행을 아래 단에 펼침면 가로로. 들지 않으면 None"""
        fw = self.frame_w
        PH = self.ch
        bw = self.band_w(self.cw)
        rows = {}
        for T in (Td, Tu):
            rows[id(T)] = list(range(T.nrow))
        hd = self.piece_h(Td, rows[id(Td)], False, bw)
        hu = self.piece_h(Tu, rows[id(Tu)], False, bw)
        if hd + hu - fw > PH + 0.01: return None
        C = lambda T, sq: self.cap(T, 'L', sq) + self.cap(T, 'R', sq)
        nd, nu = len(self.blocks(Td)[1]), len(self.blocks(Tu)[1])
        G = max(-(-nd // C(Td, False)), -(-nu // C(Tu, False)))
        if G > 1 and nd <= (G - 1) * C(Td, True) and nu <= (G - 1) * C(Tu, True): G -= 1
        # 앞 펼침면은 가득, 끝에 남는 몇 편은: 양쪽 다 한 쪽에 들면 한 쪽에 하행 위·상행 아래로
        def parts(T, n):
            _, Tc, _ = self.blocks(T)
            cL, cR = self.cap(T, 'L', True), self.cap(T, 'R', True)
            out, ti = [], 0
            for g in range(G - 1):
                k = cL + cR
                out.append((Tc[ti:ti + cL], Tc[ti + cL:ti + k])); ti += k
            rest = Tc[ti:]
            return out, rest
        pd_, rd_ = parts(Td, nd); pu_, ru_ = parts(Tu, nu)
        sBd, sBu = self.cap(Td, 'B', True), self.cap(Tu, 'B', True)
        tail_single = G > 1 and len(rd_) <= sBd and len(ru_) <= sBu and len(rd_) and len(ru_)
        if not tail_single:
            pd_, pu_ = self.stack_parts(Td, G), self.stack_parts(Tu, G)
            rd_ = ru_ = None
        if any(len(a) > self.cap(T, 'L', True) or len(b) > self.cap(T, 'R', True)
               for T, ps in ((Td, pd_), (Tu, pu_)) for a, b in ps): return None
        # 위아래 단은 왼쪽 면에 같은 수의 열을 (한쪽만 좁혀 열이 어긋나지 않게)
        al = []
        for (da, db), (ua, ub) in zip(pd_, pu_):
            kd, ku = len(da) + len(db), len(ua) + len(ub)
            kA = self.split_lr(Td, max(kd, ku))
            dd, uu = da + db, ua + ub
            al.append((dd[:kA], dd[kA:], uu[:kA], uu[kA:]))
        if any(len(a) > self.cap(Td, 'L', True) or len(b) > self.cap(Td, 'R', True) or len(c) > self.cap(Tu, 'L', True)
               or len(d) > self.cap(Tu, 'R', True) for a, b, c, d in al): return None
        pd_ = [(a, b) for a, b, c, d in al]; pu_ = [(c, d) for a, b, c, d in al]
        jobs = []
        for (da, db), (ua, ub) in zip(pd_, pu_):
            jobs.append({'T': Td, 'Tu': Tu, 'kind': 'stack', 'd': (da, db, rows[id(Td)], hd), 'u': (ua, ub, rows[id(Tu)], hu),
                         'h': hd + hu - fw, 'trs': da + db, 'rows': rows[id(Td)], 'notes': False, 'bw': bw})
        if tail_single:
            for T, tr_, sB in ((Td, rd_, sBd), (Tu, ru_, sBu)):
                jobs.append({'T': T, 'kind': 'single', 'trs': tr_, 'rows': rows[id(T)], 'notes': False, 'sB': sB,
                             'side': 'B', 'narrow': self.fixed_w(T, 'B') + len(tr_) * self.P0 < self.cw * 0.62,
                             'nat': self.fixed_w(T, 'B') + len(tr_) * self.P0, 'bw': bw,
                             'h': self.piece_h(T, rows[id(T)], False, bw)})
        return jobs

    def stackn_jobs(self, Td, Tu, N):
        """하행을 위 단, 상행을 아래 단에 N 쪽에 걸쳐 가로로 (왼쪽 면에서 시작: 왼·오·왼…). 앞 쪽부터 채운다"""
        fw, PH = self.frame_w, self.ch
        bw = self.band_w(self.cw)
        for T in (Td, Tu): T.band_left = T.head is not None; T.fold = False
        rd, ru = list(range(Td.nrow)), list(range(Tu.nrow))
        hd, hu = self.piece_h(Td, rd, False, bw), self.piece_h(Tu, ru, False, bw)
        if hd + hu - fw > PH + 0.01: return None
        sides = ['L' if i % 2 == 0 else 'R' for i in range(N)]
        def split(T, sq):
            _, Tc, _ = self.blocks(T)
            out, ti = [], 0
            for sd in sides:
                k = min(self.cap(T, sd, sq), len(Tc) - ti)
                out.append(Tc[ti:ti + k]); ti += k
            return out if ti == len(Tc) else None
        pd_ = split(Td, True)          # 앞 쪽부터 가득
        pu_ = split(Tu, True)
        if not pd_ or not pu_: return None
        return [{'T': Td, 'Tu': Tu, 'kind': 'stackN', 'sides': sides, 'd': (pd_, rd, hd), 'u': (pu_, ru, hu),
                 'h': hd + hu - fw, 'trs': pd_[0], 'rows': rd, 'notes': False, 'bw': bw}]

    def half_w(self):
        return (self.cw + self.frame_w) / 2          # 좌우 대칭으로 나란히 둘 때 한 표의 폭 (가운데 틀을 함께 쓴다)

    def side_jobs(self, Td, Tu):
        """작은 하행·상행 짝을 한 쪽에 좌우로 (같은 폭으로). 들지 않으면 None"""
        half = self.half_w()
        bw = self.band_w(half)
        js = []
        for T in (Td, Tu):
            n = len(self.blocks(T)[1])
            if self.fixed_w(T, 'B') + n * self.P0 * self.squeeze > half + 0.01: return None
            rows = list(range(T.nrow))
            js.append((T, self.blocks(T)[1], rows, self.piece_h(T, rows, False, bw)))
        return [{'T': Td, 'Tu': Tu, 'kind': 'side', 'parts': js, 'h': max(j[3] for j in js), 'trs': js[0][1],
                 'rows': js[0][2], 'notes': False, 'bw': bw}]

    def tail_side_jobs(self, Td, Tu):
        """하행·상행 각각 한 쪽 가득한 단(오른쪽 역명 없이)을 싣고, 남는 몇 편은 둘을 한 쪽에 좌우로: 하 | 하·상 | 상.
        하행은 끝의 몇 편, 상행은 앞의 몇 편이 가운데 쪽에 (가운데 쪽과 상행 쪽이 펼침면이면 상행은 펼침면 하나로 읽힌다).
        한 쪽에 단 하나만 들어가는 높이의 표에서, 펼침면 짝(오른쪽 면이 거의 빈)보다 쪽을 아낀다"""
        if self.cfg.get('rightStubSingle', True): return None
        bl = Td.line in self.cfg.get('bandLeftLines', [])            # 제목을 왼쪽 세로 띠로
        for T in (Td, Tu): T.band_left = bl and T.head is not None; T.fold = False
        PH, fw = self.ch, self.frame_w
        half = self.half_w()
        bwf, bwh = self.band_w(self.cw), self.band_w(half)
        fulls, rems = [], []
        for T in (Td, Tu):
            _, Tc, _ = self.blocks(T)
            capS = self.cap(T, 'B', True)
            n = len(Tc)
            full, r = divmod(n, capS)
            if full < 1 or r == 0: return None
            rows = list(range(T.nrow))
            h = self.piece_h(T, rows, False, bwf)
            if h > PH + 0.01: return None
            off = 0 if T is Td else r                # 하행은 끝, 상행은 앞의 몇 편을 가운데 쪽으로
            js = []
            for g in range(full):
                trs = Tc[off + g * capS:off + (g + 1) * capS]
                # 상행의 가운데 쪽(왼쪽 면) 다음 오른쪽 면이면 펼침면 하나로: 역명은 오른쪽에만
                js.append({'T': T, 'kind': 'single', 'trs': trs, 'rows': rows, 'notes': False, 'sB': capS, 'side': 'B', 'contR': T is Tu,
                           'narrow': False, 'nat': self.fixed_w(T, 'B') + len(trs) * self.P0, 'bw': bwf, 'h': h})
            fulls.append(js)
            rt = Tc[full * capS:] if T is Td else Tc[:r]
            if self.fixed_w(T, 'B') + len(rt) * self.P0 * self.squeeze > half + 0.01: return None
            rems.append((T, rt, rows, self.piece_h(T, rows, False, bwh)))
        side = {'T': Td, 'Tu': Tu, 'kind': 'side', 'parts': rems, 'h': max(r[3] for r in rems), 'trs': rems[0][1],
                'rows': rems[0][2], 'notes': False, 'bw': bwh, 'nosplit': True}
        return fulls[0] + [side] + fulls[1]

    def tail_with_jobs(self, Td, Tu, Sd, Su):
        """tailSide 에 같은 노선의 작은 별표를 곁들여: 하 | 하 끝·하 별표 | 상 | 상 끝·상 별표 (끝 몇 편과 별표를 한 쪽에 좌우로)"""
        if self.cfg.get('rightStubSingle', True): return None
        bl = Td.line in self.cfg.get('bandLeftLines', [])            # 제목을 왼쪽 세로 띠로
        for T in (Td, Tu, Sd, Su): T.band_left = bl and T.head is not None; T.fold = False
        PH = self.ch
        half = self.half_w()
        bwf, bwh = self.band_w(self.cw), self.band_w(half)
        jobs = []
        for T, S in ((Td, Sd), (Tu, Su)):
            _, Tc, _ = self.blocks(T)
            capS = self.cap(T, 'B', True)
            full, r = divmod(len(Tc), capS)
            if full < 1 or r == 0: return None
            rows = list(range(T.nrow))
            h = self.piece_h(T, rows, False, bwf)
            if h > PH + 0.01: return None
            for g in range(full):
                trs = Tc[g * capS:(g + 1) * capS]
                jobs.append({'T': T, 'kind': 'single', 'trs': trs, 'rows': rows, 'notes': False, 'sB': capS, 'side': 'B',
                             'narrow': False, 'nat': self.fixed_w(T, 'B') + len(trs) * self.P0, 'bw': bwf, 'h': h})
            parts = []
            for X, trs in ((T, Tc[full * capS:]), (S, self.blocks(S)[1])):
                if self.fixed_w(X, 'B') + len(trs) * self.P0 * self.squeeze > half + 0.01: return None
                rx = list(range(X.nrow))
                parts.append((X, trs, rx, self.piece_h(X, rx, False, bwh)))
            # 본표의 끝 몇 편: 앞 쪽과 펼침면이면(오른쪽 면) 한 표로 보고 역명은 오른쪽에
            jobs.append({'T': T, 'Tu': S, 'kind': 'side', 'parts': parts, 'h': max(q[3] for q in parts), 'trs': parts[0][1],
                         'rows': parts[0][2], 'notes': False, 'bw': bwh, 'nosplit': True, 'contR': {0}})
        return jobs

    def rule_jobs(self, Td, Tu):
        """굵은 세로줄에서 나누기: 하행·상행 본표는 각각 한 단(한 쪽에 위아래로 들 수 있게), 줄 뒤 덩어리는 둘을 한 쪽에 좌우로.
        → (하행 일감, 상행 일감) 또는 None"""
        PH = self.ch
        half = self.half_w()
        bwf, bwh = self.band_w(self.cw), self.band_w(half)
        main, parts = {}, []
        for T in (Td, Tu): T.band_left = T.head is not None     # 제목은 왼쪽 세로 띠로 (높이를 줄여 다른 표와 한 쪽을 나눠 쓴다)
        for T in (Td, Tu):
            _, Tc, _ = self.blocks(T)
            rs = [Tc.index(c) for c in getattr(T, 'rules', []) if c in Tc]
            if len(rs) != 1: return None
            b = rs[0]
            capS = self.cap(T, 'B', True)
            if not 0 < b <= capS: return None
            rows = list(range(T.nrow))
            h = self.piece_h(T, rows, False, bwf)
            if h > PH + 0.01: return None
            trs = Tc[:b]
            main[id(T)] = {'T': T, 'kind': 'single', 'trs': trs, 'rows': rows, 'notes': False, 'sB': capS, 'side': 'B',
                           'narrow': False, 'nat': self.fixed_w(T, 'B') + len(trs) * self.P0, 'bw': bwf, 'h': h}
            blk = Tc[b:]
            if self.fixed_w(T, 'B') + len(blk) * self.P0 * self.squeeze > half + 0.01: return None
            parts.append((T, blk, rows, self.piece_h(T, rows, False, bwh)))
        side = {'T': Td, 'Tu': Tu, 'kind': 'side', 'parts': parts, 'h': max(q[3] for q in parts), 'trs': parts[0][1],
                'rows': parts[0][2], 'notes': False, 'bw': bwh, 'nosplit': True}
        return [main[id(Td)], side], [main[id(Tu)]]

    def jobs_of(self, T):
        """표 하나를 실을 일감들: [{kind single|pair, trs, rows, h, ...}] (역 구간 먼저, 그 안에서 열차 무리 차례)"""
        if getattr(T, 'custom_jobs', None): return T.custom_jobs
        if getattr(T, 'stack_with', None) is not None: return self.stack_jobs(T, T.stack_with)
        if getattr(T, 'side_with', None) is not None: return self.side_jobs(T, T.side_with)
        if getattr(T, 'stacked', False): return []
        PH = self.ch
        L, Tc, R = self.blocks(T)
        head = list(range(T.hEnd)); foot = list(range(T.fStart, T.nrow)); body = list(range(T.hEnd, T.fStart))
        if getattr(T, 'fold', False) and self.cfg.get('dropEnds', True):
            drop = self.redundant_ends(T)
            head = [r for r in head if r not in drop]; foot = [r for r in foot if r not in drop]
        cuts = self.cut_ok(T)
        TH = 0 if self.page_title else self.title_tex(T, part='열넷째')[1] + 0.5 * self.fs
        BWF = self.band_w(self.cw)
        def piece(b0, b1, with_foot, notes, bw=BWF):
            rows = head + body[b0:b1] + (foot if with_foot else [])
            return rows, max(self.piece_h(T, rows, notes, bw), TH)
        # 역 구간: 한 쪽에 들면 하나. 아니면 k 구간으로 고르게 (구획 선 자리를 먼저)
        secs = [(0, len(body))]
        if piece(0, len(body), True, True)[1] > PH + 0.01:
            for k in range(2, 8):
                total = sum(T.rowH[r] for r in body)
                bounds = [0]
                for j in range(1, k):
                    target = total * j / k
                    best, bd = None, 1e9
                    for e in range(bounds[-1] + 1, len(body)):
                        acc = sum(T.rowH[r] for r in body[:e])
                        if body[e] not in cuts: continue
                        d = abs(acc - target) - (3 * self.R if 'jtt-ln' in T.rowcls[body[e]] else 0)
                        if d < bd: bd, best = d, e
                    if best is None: break
                    bounds.append(best)
                bounds.append(len(body))
                cand = list(zip(bounds, bounds[1:]))
                if all(piece(a, b, i == len(cand) - 1, i == len(cand) - 1)[1] <= PH + 0.01 for i, (a, b) in enumerate(cand)):
                    secs = cand; break
        # 열차 무리
        capL, capR = self.cap(T, 'L'), self.cap(T, 'R')
        sL, sR = self.cap(T, 'L', True), self.cap(T, 'R', True)
        sB = self.cap(T, 'B', True)      # 한 쪽에 홀로 실리는 표는 양쪽 역명을 다 단다
        n = len(Tc)
        fold = getattr(T, 'fold', False)
        if fold:                        # 접어 싣기: 한 쪽 폭의 띠(strip)를 위아래로 쌓는다
            sS = self.cap(T, self.strip_side, True)
            k = -(-n // sS)
            groups = [('single', min(sS, n - g * sS)) for g in range(k)]      # 앞에서부터 채운다 (빈 열은 끝에만)
            sB = sS
        elif n <= sB:
            groups = [('single', n)]
        else:
            C = sL + sR                    # 앞 펼침면부터 가득 (열 폭을 조금 좁혀서라도)
            G = -(-n // C)
            if n <= G * C:
                full, r = divmod(n, C)
                groups = [('pair', sL, sR)] * full
                if r:
                    if full >= 1 and r <= sB: groups.append(('single', r))
                    else:
                        kA = self.split_lr(T, r); groups.append(('pair', kA, r - kA))
            else:
                groups = []
                for g in range(G):
                    k = min(sL + sR, n - g * (sL + sR))     # 앞에서부터 채운다 (빈 열은 끝에만)
                    kA = self.split_lr(T, k); groups.append(('pair', kA, k - kA))
        jobs = []
        for si, (b0, b1) in enumerate(secs):
            last_sec = si == len(secs) - 1
            ti = 0
            for gi, gdef in enumerate(groups):
                used = gdef[1] if gdef[0] == 'single' else gdef[1] + gdef[2]
                trs = Tc[ti:ti + used]; ti += used
                notes = last_sec and gi == len(groups) - 1
                job = {'T': T, 'kind': gdef[0], 'trs': trs, 'notes': notes, 'sB': sB,
                       'side': self.strip_side if fold else 'B'}
                if gdef[0] == 'single':      # 좁은 표는 띠가 여러 줄이 될 수 있다
                    natB = self.fixed_w(T, job['side']) + used * self.P0
                    job['narrow'] = natB < self.cw * 0.62 and not fold
                    job['nat'] = natB
                    job['bw'] = self.band_w(natB) if job['narrow'] else BWF
                else:
                    job['kA'] = gdef[1]; job['bw'] = BWF
                job['rows'], job['h'] = piece(b0, b1, last_sec, notes, job['bw'])
                jobs.append(job)
        return jobs

    # ── 짜기 ──
    #  · 표 조각은 언제나 '열차 무리 × 역 구간' 하나를 통째로 (역 중간에서 남은 자리에 맞춰 자르지 않는다)
    #  · 같은 묶음(노선. ktxFirst 이면 모든 노선의 KTX 가 한 묶음) 안에서는, 지금 쪽에 다음 조각이 들지 않을 때
    #    뒤에 올 작은 표(한 번에 다 실리는 것)를 당겨 와 빈자리를 채운다. 묶음을 넘어서는 당기지 않는다
    #  · 한 쪽의 표들은 사이를 띄우지 않고 틀(굵은 선)을 함께 쓴다
    def layout(self, tables):
        PH = self.ch
        fw = self.frame_w
        gap = -fw if self.cfg.get('joinTables', True) else self.R * self.cfg.get('tierGap', 1.0)
        gapX = -fw if self.cfg.get('joinTables', True) else self.cfg.get('sideGap', 1.5) * MM
        TWh = 0 if self.page_title else (self.title_tex(tables[0])[2] if tables else 0)
        pages = []
        def page(i):
            while len(pages) <= i: pages.append({'pieces': [], 'lines': []})
            return pages[i]
        ys = collections.defaultdict(float)
        cur = {'c': 0}
        def top(p): return ys[p] + gap if ys[p] > 0 else 0.0
        def side_of(p): return 'L' if p % 2 == 0 else 'R'
        def put(T, p, trains, rows, y, notes, h, x=0.0, narrow=False, side=None, bw=None):
            pg = page(p)
            side = side or side_of(p)
            pc = {'T': T, 'side': side, 'trains': trains, 'rows': rows, 'y': y, 'x': x, 'h': h, 'notes': notes,
                  'narrow': narrow, 'nat': self.fixed_w(T, side) + len(trains) * self.P0,
                  'hb': self.headband_h(T, bw if bw is not None else self.band_w(self.cw), '열넷째' if self.page_title else None)}
            pg['pieces'].append(pc)
            key = ('KTX', T.line) if self.is_ktx(T) else ('', T.line)
            if key not in pg['lines']: pg['lines'].append(key)
            tt = T.title.text() if T.title is not None else ''
            pg.setdefault('dirs', collections.defaultdict(set))[key].add('하행' if '하행' in tt else '상행' if '상행' in tt else '')
            placed[id(T)].append(pc)
            return pc
        placed = collections.defaultdict(list)

        def try_place(job, c):
            """지금 쪽 c 에 (짝이면 c 와 c+1 에) 그대로 들면 싣고 True"""
            T, trs, rows, h, notes = job['T'], job['trs'], job['rows'], job['h'], job['notes']
            if job['kind'] == 'side':
                y = top(c)
                # 왼쪽 면에서 두 면의 높이가 같으면: 하행은 왼쪽 면, 상행은 오른쪽 면에 (펼침면 좌우로)
                if c % 2 == 0 and abs(top(c) - top(c + 1)) < 0.01 and not job.get('nosplit'):
                    bwf = self.band_w(self.cw)
                    hs_ = [self.piece_h(T_, rows_, False, bwf) for T_, trs_, rows_, h_ in job['parts']]
                    hf = max(hs_)
                    if y + hf <= PH + 0.01 and hf > 0.5 * PH:      # 작은 표(반 쪽 높이 미만)는 한 쪽에 좌우로
                        for k_, (T_, trs_, rows_, h_) in enumerate(job['parts']):
                            put(T_, c + k_, trs_, rows_, y, False, hf, 0.0, False, 'B', bwf)
                        ys[c] = ys[c + 1] = y + hf
                        return True
                if y + h > PH + 0.01: return False
                half = self.half_w()
                for k_, (T_, trs_, rows_, h_) in enumerate(job['parts']):
                    sd = 'R' if k_ in job.get('contR', ()) and c % 2 == 1 and any(q['T'] is T_ for q in page(c - 1)['pieces']) else 'B'
                    pc_ = put(T_, c, trs_, rows_, y, False, h_, k_ * (half - fw), True, sd, job['bw'])
                    pc_['fixw'] = half
                ys[c] = y + h
                return True
            if job['kind'] == 'stackN':           # 여러 쪽에 걸쳐 위(하행)·아래(상행) (왼쪽 면에서 시작)
                if c % 2 == 1: return False
                N_ = len(job['sides'])
                y = max(top(c + i) for i in range(N_))
                if y + h > PH + 0.01: return False
                pd_, rd, hd = job['d']; pu_, ru, hu = job['u']
                for i, sd in enumerate(job['sides']):
                    n_ = max(len(pd_[i]), len(pu_[i]))
                    if pd_[i]: put(T, c + i, pd_[i], rd, y, False, hd, side=sd)['ncol'] = n_
                    if pu_[i]: put(job['Tu'], c + i, pu_[i], ru, y + hd - fw, False, hu, side=sd)['ncol'] = n_
                    ys[c + i] = y + h
                return True
            if job['kind'] == 'stack':            # 펼침면에서만 (왼쪽 면에서 시작)
                if c % 2 == 1: return False
                y = max(top(c), top(c + 1))
                if y + h > PH + 0.01: return False
                da, db, rd, hd = job['d']; ua, ub, ru, hu = job['u']
                Tu = job['Tu']
                for p_, a_, b_ in ((c, da, ua), (c + 1, db, ub)):
                    n_ = max(len(a_), len(b_))
                    if a_: put(T, p_, a_, rd, y, False, hd)['ncol'] = n_
                    if b_: put(Tu, p_, b_, ru, y + hd - fw, False, hu)['ncol'] = n_
                ys[c] = ys[c + 1] = y + h
                return True
            if job['kind'] == 'single':
                k = len(trs)
                pg = page(c)
                if pg['pieces']:          # 앞의 좁은 표 옆에 나란히
                    prev = pg['pieces'][-1]
                    low = max(q['y'] for q in pg['pieces'])
                    if prev['narrow'] and abs(prev['y'] - low) < 0.01:
                        x = prev['x'] + prev['nat'] + TWh + gapX
                        if x + job['nat'] <= self.cw + 0.01 and prev['y'] + h <= PH + 0.01:
                            put(T, c, trs, rows, prev['y'], notes, h, x, True, job['side'], job['bw'])
                            ys[c] = max(ys[c], prev['y'] + h)
                            return True
                if job['sB'] >= k and top(c) + h <= PH + 0.01:
                    y0 = top(c)
                    sd = 'R' if job.get('contR') and c % 2 == 1 and any(q['T'] is T for q in page(c - 1)['pieces']) else job['side']
                    put(T, c, trs, rows, y0, notes, h, 0.0, job['narrow'], sd, job['bw'])
                    ys[c] = y0 + h
                    return True
                return False
            kA = job['kA']
            ya, yb = top(c), top(c + 1)
            if c % 2 == 0 and abs(ya - yb) < 10 * MM: ya = yb = max(ya, yb)
            if ya + h <= PH + 0.01 and yb + h <= PH + 0.01:
                put(T, c, trs[:kA], rows, ya, False, h)
                put(T, c + 1, trs[kA:], rows, yb, notes, h)
                ys[c] = ya + h; ys[c + 1] = yb + h
                if c % 2 == 1: cur['c'] = c + 1
                return True
            return False

        def remeta(pg):
            pg['lines'], pg['dirs'] = [], collections.defaultdict(set)
            for q in pg['pieces']:
                key = ('KTX', q['T'].line) if self.is_ktx(q['T']) else ('', q['T'].line)
                if key not in pg['lines']: pg['lines'].append(key)
                tt = q['T'].title.text() if q['T'].title is not None else ''
                pg['dirs'][key].add('하행' if '하행' in tt else '상행' if '상행' in tt else '')
        def advance(job, c):
            if job['kind'] == 'stack':
                # 펼침면으로 가야 해서 오른쪽 면이 통째로 빌 때: 앞 쪽 맨 아랫단의 작은 표(통째로 그 쪽에 있는 것)를 옮겨 채운다
                if c % 2 == 1 and ys[c] == 0 and c >= 1 and page(c - 1)['pieces']:
                    prev = page(c - 1)
                    low = max(q['y'] for q in prev['pieces'])
                    mv = [q for q in prev['pieces'] if abs(q['y'] - low) < 0.01]
                    if low > 0 and all(q['side'] == 'B' and all(r in prev['pieces'] for r in placed[id(q['T'])]) for q in mv):
                        for q in mv:
                            prev['pieces'].remove(q); q['y'] = 0.0; page(c)['pieces'].append(q)
                        ys[c - 1] = max(q['y'] + q['h'] for q in prev['pieces'])
                        ys[c] = max(q['h'] for q in mv)
                        remeta(prev); remeta(page(c))
                cur['c'] = c + 1          # 오른쪽 면에서는 다른 작은 표로 채울 수 있게 한 쪽씩
            elif job['kind'] == 'pair' and c % 2 == 0:
                # 왼쪽 면에 자리가 없고 오른쪽 면이 비었으면 오른쪽 면에서 시작해 넘겨 잇는다
                cur['c'] = c + 1 if (ys[c + 1] == 0 and job['h'] <= PH + 0.01) else c + 2
            else:
                cur['c'] = c + 1

        # 묶음
        bunches = []
        if self.cfg.get('ktxFirst', False):
            k = [T for T in tables if self.is_ktx(T)]
            # 뒤로 미룰 표(holdAfter): 그 노선의 표가 모두 실린 뒤에 (그 앞으로 당겨 오지 않는다)
            for h in self.cfg.get('holdAfter', []):
                held = [T for T in k if T.line == h['line'] and h.get('title', '') in T.title.text()]
                if not held: continue
                rest = [T for T in k if T not in held]
                at = max((i for i, T in enumerate(rest) if T.line == h['after']), default=-1)
                # 앞서 같은 노선으로 미룬 표 뒤에
                while at + 1 < len(rest) and getattr(rest[at + 1], 'hold_after', None) == h['after']: at += 1
                for T in held: T.hold_after = h['after']
                k = rest[:at + 1] + held + rest[at + 1:]
            if k: bunches.append(k)
        for T in tables:
            if self.cfg.get('ktxFirst', False) and self.is_ktx(T): continue
            if bunches and bunches[-1] and not self.is_ktx(bunches[-1][0]) and bunches[-1][0].line == T.line:
                bunches[-1].append(T)
            else:
                bunches.append([T])
        # 띠 자리: bandPos top | left | auto (auto: 왼쪽 세로 띠로 해야 한 쪽에 두 단이 들어가는 표만 왼쪽으로)
        mode = self.cfg.get('bandPos', 'top')
        def per_page(h):
            m = 0
            while (m + 1) * h - m * fw <= PH + 0.01: m += 1
            return m
        def band_pos(T):
            if T.head is None or mode == 'top': return
            jt = self.jobs_of(T)
            T.band_left = True
            jl = self.jobs_of(T)
            ht, hl = max(j['h'] for j in jt), max(j['h'] for j in jl)
            fits = all(self.vband(T, '열넷째' if len(jl) > 1 else None, 100)[1] <= j['h'] - 2 * (fw + self.frame_pad) - 2 * self.vpad for j in jl)
            if mode == 'left': T.band_left = fits
            else: T.band_left = fits and len(jl) <= len(jt) and 2 * hl - fw <= PH + 0.01 < 2 * ht - fw
        for T in tables:
            T.band_left = False; T.fold = False; T.stack_with = None; T.stacked = False; T.side_with = None; T.custom_jobs = None; T.pull_first = False
            if self.fold != 'off':
                jt = self.jobs_of(T)
                T.band_left = T.head is not None; T.fold = True
                jf = self.jobs_of(T)
                m = per_page(max(j['h'] for j in jf))
                ok = m >= 2 and len(jf) > 1
                pf = -(-len(jf) // max(m, 1))
                # 펼침면 짝은 두 쪽을 다 쓴다(남는 자리에 다른 표가 들기 어렵다). 한 쪽 조각은 높이만큼
                pt = sum(2 if j['kind'] == 'pair' else j['h'] / PH for j in jt)
                if self.fold == 'on' or (ok and pf <= pt + 0.01):
                    continue
                T.band_left = False; T.fold = False
            band_pos(T)
        # 같은 노선의 같은 종류(KTX끼리, 일반끼리) 표는 하행·상행이 같은 짜임으로: 하나라도 접지 못하면 모두 펼침면으로
        def route(T):        # 띠 가운데의 역 이름들 (하행·상행 짝을 찾는 데)
            if T.head is None: return frozenset()
            parts, _ = self.band_nodes(T)
            return frozenset(re.findall(r'[가-힣]+', parts[1].text()))
        grp = collections.defaultdict(list)
        for T in tables: grp[(T.line, self.is_ktx(T), route(T))].append(T)
        for ts in grp.values():
            if any(T.fold for T in ts) and not all(T.fold for T in ts):
                for T in ts:
                    T.fold = False; T.band_left = False
                    band_pos(T)
            # 작은 짝(둘 다 반쪽 폭에 드는 것)은 한 쪽에 좌우 대칭으로 (하행 왼쪽, 상행 오른쪽)
            if self.cfg.get('sideBySide', True) and len(ts) == 2:
                dn = [T for T in ts if '하행' in T.title.text()]
                up = [T for T in ts if '상행' in T.title.text()]
                if len(dn) == 1 and len(up) == 1:
                    old = [(T.fold, T.band_left) for T in ts]
                    for T in ts: T.fold = False; T.band_left = False
                    if self.side_jobs(dn[0], up[0]):
                        dn[0].side_with, up[0].stacked = up[0], True
                        continue
                    for T, (f, b) in zip(ts, old): T.fold, T.band_left = f, b
            # stackPages: 지정한 표는 하행 위·상행 아래로 N 쪽에 걸쳐
            sp = next((x for x in self.cfg.get('stackPages', []) if len(ts) == 2 and all(T.line == x['line'] and x.get('title', '') in T.title.text() for T in ts)), None)
            if sp:
                dn = [T for T in ts if '하행' in T.title.text()]
                up = [T for T in ts if '상행' in T.title.text()]
                if len(dn) == 1 and len(up) == 1:
                    sj = self.stackn_jobs(dn[0], up[0], sp['pages'])
                    if sj:
                        dn[0].custom_jobs, up[0].stacked = sj, True
                        continue
            # 굵은 세로줄(덧붙인 덩어리)이 있으면 거기서 나눈다: 본표는 하행·상행 한 단씩, 덩어리는 따로 한 쪽에 좌우로
            if self.cfg.get('ruleSplit', True) and len(ts) == 2 and all(getattr(T, 'rules', None) for T in ts):
                dn = [T for T in ts if '하행' in T.title.text()]
                up = [T for T in ts if '상행' in T.title.text()]
                if len(dn) == 1 and len(up) == 1:
                    old = [(T.fold, T.band_left) for T in ts]
                    for T in ts: T.fold = False; T.band_left = False
                    rj = self.rule_jobs(dn[0], up[0])
                    if rj:
                        dn[0].custom_jobs, up[0].custom_jobs = rj
                        for T in ts: T.pull_first = True      # 본표만 먼저 당겨 올 수 있다 (덩어리는 제 차례에)
                        continue
                    for T, (f, b) in zip(ts, old): T.fold, T.band_left = f, b
            # 하행·상행 짝이 펼침면에 위아래로 들면 그렇게 (하행 위, 상행 아래, 가로로 이어 읽는다)
            if self.cfg.get('upDown', True) and len(ts) == 2:
                dn = [T for T in ts if '하행' in T.title.text()]
                up = [T for T in ts if '상행' in T.title.text()]
                # 한 쪽에 홀로 드는 작은 표는 그대로 (위아래로 차례로 쌓인다)
                if len(dn) == 1 and len(up) == 1 and any(
                        len(self.blocks(T)[1]) > self.cap(T, 'B', True) for T in ts):
                    Td, Tu = dn[0], up[0]
                    old = [(T.fold, T.band_left) for T in ts]
                    for T in ts: T.fold = False; T.band_left = T.head is not None
                    sj = self.stack_jobs(Td, Tu)
                    # 끝에 남는 몇 편을 한 쪽에 따로 실어야 하면, 위아래 펼침면 대신 그냥 접어 싣는다 (쪽 수는 같고 덜 어수선하다)
                    if sj and not any(j['kind'] == 'single' for j in sj):
                        Td.stack_with, Tu.stacked = Tu, True
                        continue
                    for T, (f, b) in zip(ts, old): T.fold, T.band_left = f, b
                    # 한 쪽 가득한 단 + 끝에 남는 몇 편은 하행·상행을 한 쪽에 좌우로 (펼침면 짝보다 쪽이 적으면)
                    if self.cfg.get('tailSide', True) and not any(T.fold for T in ts):
                        tj = self.tail_side_jobs(Td, Tu)
                        if tj:
                            pages_t = sum(1 for j in tj if j['kind'] == 'single') + 1
                            pages_p = sum(sum(2 if j['kind'] == 'pair' else 1 for j in self.jobs_of(T)) for T in ts)
                            if pages_t < pages_p:
                                Td.custom_jobs, Tu.stacked = tj, True
                                continue
                        for T, (f, b) in zip(ts, old): T.fold, T.band_left = f, b
            if any(T.band_left for T in ts) and not all(T.band_left for T in ts):
                ok = True
                for T in ts:
                    T.band_left = True
                    jl = self.jobs_of(T)
                    ok = ok and all(self.vband(T, '열넷째' if len(jl) > 1 else None, 100)[1] <= j['h'] - 2 * (fw + self.frame_pad) - 2 * self.vpad for j in jl)
                for T in ts: T.band_left = ok
        # bandLeftLines: 그 노선(KTX) 표는 제목을 왼쪽 세로 띠로
        for T in tables:
            if T.line in self.cfg.get('bandLeftLines', []) and self.is_ktx(T) and T.head is not None and not T.fold: T.band_left = True
        # tailWith: 노선의 KTX 하행·상행에 같은 노선의 작은 별표(수서 발착 병결 등)를 곁들여 한 흐름으로
        for tw in self.cfg.get('tailWith', []):
            ks = [T for T in tables if self.is_ktx(T) and T.line == tw['line']]
            main = [T for T in ks if tw['title'] not in T.title.text()]
            sub = [T for T in ks if tw['title'] in T.title.text()]
            pick = lambda ts, d: [T for T in ts if d in T.title.text()]
            if not (len(pick(main, '하행')) == len(pick(main, '상행')) == len(pick(sub, '하행')) == len(pick(sub, '상행')) == 1): continue
            Td, Tu, Sd, Su = pick(main, '하행')[0], pick(main, '상행')[0], pick(sub, '하행')[0], pick(sub, '상행')[0]
            old = [(T.custom_jobs, T.stacked, T.side_with, T.band_left, T.fold) for T in (Td, Tu, Sd, Su)]
            for T in (Td, Tu, Sd, Su): T.custom_jobs = None; T.stacked = False; T.side_with = None; T.stack_with = None
            tj = self.tail_with_jobs(Td, Tu, Sd, Su)
            if tj:
                Td.custom_jobs = tj; Tu.stacked = Sd.stacked = Su.stacked = True
            else:
                for T, (a, b, c_, d_, e_) in zip((Td, Tu, Sd, Su), old): T.custom_jobs, T.stacked, T.side_with, T.band_left, T.fold = a, b, c_, d_, e_
        rkey = lambda T: (T.line, self.is_ktx(T), route(T))
        for bunch in bunches:
            pend = [collections.deque(self.jobs_of(T)) for T in bunch]
            init = [len(q) for q in pend]
            whole = [n <= 1 for n in init]          # 한 번에 다 실리는 표만 당겨 올 수 있다 (짝에 묶여 일감이 없는 표 포함)
            while any(pend):
                pi = next(i for i, q in enumerate(pend) if q)
                job = pend[pi][0]
                for guard in range(400):
                    c = cur['c']
                    if try_place(job, c):
                        pend[pi].popleft(); break
                    # 당겨 올 것: 하행·상행 짝을 한 덩어리로 (짝이 다 한 쪽 조각이고, 함께 위아래로 들 때만)
                    filled = False
                    qi = pi + 1
                    while qi < len(pend) and not filled:
                        unit = [qi]
                        while unit[-1] + 1 < len(pend) and rkey(bunch[unit[-1] + 1]) == rkey(bunch[qi]): unit.append(unit[-1] + 1)
                        js = [pend[k][0] for k in unit if pend[k]]
                        held = any(getattr(bunch[k], 'hold_after', None) and any(pend[m] for m in range(len(bunch)) if bunch[m].line == bunch[k].hold_after) for k in unit)
                        if js and not held and all((whole[k] or getattr(bunch[k], 'pull_first', False)) and len(pend[k]) == init[k] for k in unit) \
                                and all(j['kind'] in ('single', 'side') for j in js) \
                                and top(c) + sum(j['h'] for j in js) - (len(js) - 1) * fw <= PH + 0.01:
                            for k in unit:
                                if pend[k]: try_place(pend[k][0], c); pend[k].popleft()
                            filled = True
                        qi = unit[-1] + 1
                    if not filled: advance(job, c)
        for T in tables:
            ps = placed[id(T)]
            # 세로 제목칸 표는 오른쪽 면 조각에 칸이 없으니, 칸이 있는 조각(펼침면 하나)마다 센다
            shown = [pc for pc in ps if not (getattr(T, 'band_left', False) and pc['side'] == 'R')]
            for pc in ps: pc['part'] = ''
            # 펼침면에 걸쳐 이어지는 조각(왼쪽 면 → 오른쪽 면, 그 쪽에 그 표의 조각이 하나뿐)은 하나로 센다
            pidx = {id(q): i for i, pg in enumerate(pages) for q in pg['pieces']}
            alone = lambda q: sum(1 for r in pages[pidx[id(q)]]['pieces'] if r['T'] is T) == 1
            groups = []
            for pc in shown:
                if groups:
                    prev = groups[-1][-1]
                    a, b = pidx[id(prev)], pidx[id(pc)]
                    if a % 2 == 0 and b == a + 1 and alone(prev) and alone(pc):
                        groups[-1].append(pc); continue
                groups.append([pc])
            f0 = self.cfg.get('firstFolio', 2)
            for k, g in enumerate(groups):
                lab = (ORD_KO[k] if k < len(ORD_KO) else '%d째' % (k + 1)) if len(groups) > 1 else ''
                # 다음·앞 조각이 바로 이웃한 쪽이 아니면 어디로 이어지는지 (「첫째・17쪽으로」「둘째・9쪽에서」)
                # 바로 다음 장(다음 펼침면)이면 적지 않는다
                if lab and k + 1 < len(groups) and pidx[id(groups[k + 1][0])] - pidx[id(g[-1])] > 2:
                    lab += '・%d쪽으로' % (pidx[id(groups[k + 1][0])] + f0)
                if lab and k > 0 and pidx[id(g[0])] - pidx[id(groups[k - 1][-1])] > 2:
                    lab += '・%d쪽에서' % (pidx[id(groups[k - 1][-1])] + f0)
                for pc in g:
                    pc['part'] = lab
        # 단(같은 높이)마다 맨 오른쪽 조각만 빈 열로 판면 끝까지 채운다
        for pg in pages:
            for pc in pg['pieces']:
                others = sorted([q for q in pg['pieces'] if q is not pc and abs(q['y'] - pc['y']) < 0.01 and q['x'] > pc['x']], key=lambda q: q['x'])
                avail = min(others[0]['x'] - TWh - gapX - pc['x'], pc['nat']) if others else (self.cw - pc['x'])
                if pc.get('fixw'): avail = pc['fixw']
                pc['ch'] = self.make_chunk(pc['T'], pc['side'], pc['trains'], avail, pc.get('ncol'))
                pc['avail'] = avail
        # 세로 제목칸: 빈 열이 넉넉한 쪽에서는 열 두 칸 폭으로 넓히고 글자도 키운다 (쪽 안의 세로 띠는 모두 같이)
        sc = self.cfg.get('wideBandScale', 1.0)          # 노선 이름 크기는 어디서나 같게
        for pg in pages:
            vps = [pc for pc in pg['pieces'] if getattr(pc['T'], 'band_left', False) and pc['side'] == 'B']
            if not vps: continue
            def spare(pc):
                ch = pc['ch']
                return sum(ch['P'] for c in ch['trains'] if isinstance(c, tuple)) + ch['extra']
            # 글자 크기: 세로 길이와 남는 폭에 드는 가장 큰 배율 (쪽 안에서 같게). 칸 폭은 글자 두 줄에 맞춘다
            def fits(s_):
                w_ = self.wide_band_w(s_)
                return all(spare(pc) >= w_ - self.vband_w + 0.01 for pc in vps) and all(
                    self.vband(pc['T'], pc.get('part') or None, 100, w_, s_)[1]
                    <= (pc['vrun'][1] if pc.get('vrun') else pc['h']) - 2 * (fw + self.frame_pad) - 2 * self.vpad for pc in vps)
            s_ok = next((x for x in (sc, 1.3, 1.2, 1.1, 1.0) if x <= sc and fits(x)), None)
            if s_ok is None: continue
            wide_w = self.wide_band_w(s_ok); extra = wide_w - self.vband_w
            for pc in vps:
                pc['ch'] = self.make_chunk(pc['T'], pc['side'], pc['trains'], pc['avail'] - extra, pc.get('ncol'))
                pc['vbw'], pc['vbscale'] = wide_w, s_ok
        # 쪽 아래 남는 자리: 단(같은 높이에서 시작하는 조각들)마다 비고 행을 늘여 채운다 (다른 행 높이는 그대로).
        # 낮은 단부터 같은 높이가 되도록 나눠 준다(두 단이면 반반에 가깝게). 펼침면에 걸친 단은 두 쪽에서 같은 만큼
        if self.cfg.get('stretchRemarks', True):
            smax = self.cfg.get('stretchMax', 999) * self.R
            def tiers(pg):
                ys_ = sorted({round(q['y'], 2) for q in pg['pieces']})
                return [[q for q in pg['pieces'] if round(q['y'], 2) == y_] for y_ in ys_]
            def can(t):
                return all(q['T'].dayrow is not None and q['rows'] and q['rows'][-1] == q['T'].dayrow for q in t)
            alloc = {}
            for p, pg in enumerate(pages):
                if not pg['pieces']: continue
                ts = tiers(pg)
                left = PH - max(q['y'] + q['h'] for q in pg['pieces'])
                hs = [max(q['h'] for q in t) for t in ts]
                give = [0.0] * len(ts)
                ok = [can(t) for t in ts]
                # 남는 자리는 각 단의 높이(내용의 양)에 비례해 나눈다
                cand = [i for i in range(len(ts)) if ok[i]]
                tot_h = sum(hs[i] for i in cand)
                for i in cand:
                    give[i] = min(smax, left * hs[i] / tot_h) if tot_h > 0 else 0.0
                alloc[p] = (ts, give)
            # 펼침면에 걸친 단: 마주 보는 쪽과 같은 만큼(작은 쪽에 맞춘다)
            for p in list(alloc):
                ts, give = alloc[p]
                mate = p + 1 if p % 2 == 0 else p - 1
                if mate not in alloc: continue
                mts, mgive = alloc[mate]
                for i, t in enumerate(ts):
                    for j, mt in enumerate(mts):
                        if any(q['T'] is r['T'] and abs(q['y'] - r['y']) < 0.05 for q in t for r in mt):
                            give[i] = mgive[j] = min(give[i], mgive[j])
            for p, (ts, give) in alloc.items():
                shift = 0.0
                for t, g in zip(ts, give):
                    bottom = max(q['y'] + q['h'] for q in t)
                    for q in t:
                        q['y'] += shift
                        if g > 0.5 * self.R:
                            e = g + (bottom - (q['y'] - shift + q['h']))
                            q['stretch'] = e; q['h'] += e
                    if g > 0.5 * self.R: shift += g
        # 붙은 조각 사이의 괘선: 위 조각과 같은 표면 띠 사이 괘선, 다른 표면 표 사이 괘선. 아래에 붙은 조각이 있으면 아래 변은 그 조각이 긋는다
        for pg in pages:
            ps = pg['pieces']
            for pc in ps:
                pc['top'], pc['bottom'], pc['vrun'] = 'frame', True, None
            for pc in ps:
                above = [q for q in ps if q is not pc and abs(q['y'] + q['h'] - fw - pc['y']) < 0.05]
                if above:
                    pc['top'] = 'strip' if all(q['T'] is pc['T'] for q in above) else 'table'
                    for q in above: q['bottom'] = False
            # 제목칸(세로 띠)은 같은 표의 띠가 이어 쌓인 만큼 한 칸으로
            for pc in sorted(ps, key=lambda q: q['y']):
                if not getattr(pc['T'], 'band_left', False) or pc['vrun'] is not None: continue
                run = [pc]
                while True:
                    nxt = [q for q in ps if q['T'] is pc['T'] and abs(q['x'] - pc['x']) < 0.05
                           and abs(run[-1]['y'] + run[-1]['h'] - fw - q['y']) < 0.05]
                    if not nxt: break
                    run.append(nxt[0])
                for k, q in enumerate(run):
                    q['vrun'] = (k, sum(r['h'] for r in run) - (len(run) - 1) * fw, len(run))
                    q['vrun_part'] = '・'.join(dict.fromkeys(r['part'] for r in run if r.get('part')))    # 한 칸에 걸친 몇째들: (첫째·둘째)
        self.pages = pages

    def emit(self, out_tex):
        first = self.cfg.get('firstFolio', 2)
        body = []
        for pi, pg in enumerate(self.pages):
            folio = first + pi
            recto = folio % 2 == 1
            x0 = self.mi if recto else self.mo
            tex, rects = [], []
            for pc in pg['pieces']:
                t, r, w, h = self.render_piece(pc['T'], pc['ch'], pc['rows'], x0 + pc.get('x', 0), self.mt + pc['y'], pc['notes'],
                                               line=pc['T'].line, part=pc['part'], hb=pc['hb'], pc=pc)
                tex += t; rects += r
            # 머리글은 노선 이름만 (책을 넘기며 찾는 자리). 몇째 조각인지는 표의 세로 제목 끝에
            if self.page_title:
                tex += self.page_side_title(recto, pg['lines'], pg.get('dirs'))
                tex += self.page_furniture(folio, recto, '', '', self.page_legend([pc['T'] for pc in pg['pieces']]))
            else:
                tex += self.page_furniture(folio, recto, '·'.join(ln for _, ln in pg['lines']), '')
            body.append(r'\begin{picture}(%.3f,%.3f)' % (self.W, self.H))
            if rects: body.append(r'\put(0,0){\pdfextension literal{%s}}' % self.pdf_ops(rects))
            body += tex
            body.append(r'\end{picture}\newpage')
        pre = PREAMBLE % {
            'W': self.W, 'H': self.H, 'fontdefs': self.fontdefs(),
            'layout': 'TwoPageLeft' if first % 2 == 0 else 'TwoPageRight',
        }
        with open(out_tex, 'w', encoding='utf-8') as fo:
            fo.write(pre + '\n'.join(body) + '\n\\end{document}\n')

FAMCHAIN = {cmd: [main] + fbs for cmd, main, fbs, _ in Book.FAMILIES}

DEFAULT_FONT_DIRS = ['fonts', '/usr/share/fonts', '/usr/local/share/fonts',
                     '~/Library/Fonts', '/Library/Fonts', '/System/Library/Fonts']
DEFAULT_FONTS = {'mincho': 'Shippori Mincho', 'minchoKo': 'UnBatang',
                 'gothic': 'BIZ UDPGothic', 'gothicKo': 'UnDotum',
                 'gothicBold': 'BIZ UDPGothic Bold', 'gothicKoBold': 'UnDotum Bold', 'dia': 'DiaPro'}

ORD_KO = ['첫째', '둘째', '셋째', '넷째', '다섯째', '여섯째', '일곱째', '여덟째', '아홉째', '열째',
          '열한째', '열두째', '열셋째', '열넷째', '열다섯째', '열여섯째']

PREAMBLE = r'''\documentclass{article}
\usepackage[paperwidth=%(W).3fbp,paperheight=%(H).3fbp,margin=0pt]{geometry}
\usepackage{fontspec}
\usepackage{graphicx}
\usepackage{xfp}
\usepackage[dvipsnames]{xcolor}
\pagestyle{empty}
\setlength{\unitlength}{1bp}
\setlength{\parindent}{0pt}
%(fontdefs)s
\pdfvariable pagesattr{/PageLayout /%(layout)s}
%% 배지: 폭 높이 칠함 가로배율 글자중심높이 내용
\newcommand\ttbadge[6]{\raisebox{\dimexpr #5bp - #2bp/2\relax}{\begin{picture}(#1,#2)%%
  \ifnum#3=1 \put(0,0){\pdfextension literal{0 g 0 0 #1 #2 re f}}%%
  \else \put(0,0){\pdfextension literal{0 g 0.283 w 0.142 0.142 \fpeval{#1-0.283} \fpeval{#2-0.283} re S}}\fi
  \put(0,0){\makebox(#1,#2){\scalebox{#4}[1]{#6}}}\end{picture}}}
%% 방향 표지(오각형): 폭 높이 아래쪽? 속빈? 뾰족한높이 글자위여백 글자
\newcommand\ttdir[7]{\begin{picture}(#1,#2)%%
  \ifnum#3=1
    \ifnum#4=1 \put(0,0){\pdfextension literal{0 g 0.6 w 0.3 \fpeval{#2-0.3} m \fpeval{#1-0.3} \fpeval{#2-0.3} l \fpeval{#1-0.3} \fpeval{#5} l \fpeval{#1/2} 0.4 l 0.3 \fpeval{#5} l h S}}%%
    \else \put(0,0){\pdfextension literal{0 g 0 #2 m #1 #2 l #1 #5 l \fpeval{#1/2} 0 l 0 #5 l h f}}\fi
  \else
    \ifnum#4=1 \put(0,0){\pdfextension literal{0 g 0.6 w 0.3 0.3 m \fpeval{#1-0.3} 0.3 l \fpeval{#1-0.3} \fpeval{#2-#5} l \fpeval{#1/2} \fpeval{#2-0.4} l 0.3 \fpeval{#2-#5} l h S}}%%
    \else \put(0,0){\pdfextension literal{0 g 0 0 m #1 0 l #1 \fpeval{#2-#5} l \fpeval{#1/2} #2 l 0 \fpeval{#2-#5} l h f}}\fi
  \fi
  \put(0,\fpeval{#2-#6}){\makebox(#1,0)[t]{\vbox{\offinterlineskip #7}}}\end{picture}}
\begin{document}
'''

def main():
    cfgp = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'book.json')
    cfg = json.load(open(cfgp, encoding='utf-8'))
    base = os.path.dirname(os.path.abspath(cfgp))
    bk = Book(cfg, base)
    items = list(cfg.get('items', []))
    for ln in cfg.get('lines', []):              # 노선 이름만 적으면 pages/노선.txt 의 모든 표
        items.append({'src': os.path.join('pages', ln + '.txt'), 'line': ln})
    tables = []
    for it in items:
        if it.get('type', 'table') == 'table': tables += bk.load_tables(it)
    bk.layout(tables)
    out = os.path.join(HERE, 'build', cfg.get('name', 'book') + '.tex')
    bk.emit(out)
    env = dict(os.environ)
    if bk.metrics.missing: print('fonts not found:', ', '.join(bk.metrics.missing))
    print('align (em):', bk.metrics.report(), '| ref center %.3f' % bk.metrics.ref)
    r = subprocess.run(['lualatex', '-interaction=nonstopmode', '-halt-on-error', os.path.basename(out)],
                       cwd=os.path.dirname(out), capture_output=True, env=env)
    log = r.stdout.decode('utf-8', 'replace')
    if r.returncode != 0:
        print(log[-3000:]); sys.exit(1)
    miss = set(re.findall(r'Missing character: There is no (.) ', log))
    if miss: print('missing glyphs:', ' '.join(sorted(miss)))
    print('pages:', len(bk.pages), '→', out[:-4] + '.pdf')

if __name__ == '__main__':
    main()
