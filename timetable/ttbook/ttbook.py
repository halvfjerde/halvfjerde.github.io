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
KO_OF = {'M': 'KM', 'DM': 'KM', 'G': 'KG', 'DG': 'KG', 'GB': 'KGB', 'DGB': 'KGB'}
JP_OF = {'M': 'mincho', 'DM': 'mincho', 'G': 'gothic', 'DG': 'gothic', 'GB': 'gothicBold', 'DGB': 'gothicBold'}
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
VROT = {'︵': '(', '︶': ')', '︱': '―', '︹': '〔', '︺': '〕', '(': '(', ')': ')', '（': '(', '）': ')', '―': '―', '—': '―'}

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
            t = ''.join(r'\ ' if ch == ' ' else esc(ch) for ch in chs)
            fam = KO_OF[ctx.font] if k in ('ko', 'kp') else ctx.font
            c2 = ctx
            up = self.shift_for(k, ctx.font)
            if k == 'jp' and self.m:
                sc = self.m.jscale.get(JP_OF[ctx.font], 1.0)
                if sc < 0.999:
                    c2 = ctx.but(size=ctx.size * sc)
                    up += (1 - sc) * self.c          # 작아진 글자의 가운데를 제자리에
            body = '{' + self.font(c2, fam) + t + '}'
            wsum += c2.size * sum(self.adv(ch, fam) for ch in chs)
            if abs(up) > 0.002 and not (vertical and k == 'base'):
                body = r'\raisebox{%.3fbp}{%s}' % (up * ctx.size * self.fs, body)
            out.append(body)
        res = '{' + ''.join(out) + '}'
        self.wc[res] = wsum
        return res

    def adv(self, ch, fam):
        """글꼴 묶음 fam 에서 ch 의 폭 (em). 묶음의 글꼴을 차례로 보아 처음 가진 것의 폭"""
        if ch in ' \u00a0': return 0.3
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
            if 'jtt-j' in cls:
                chars = [self.run(x.text(), c2) for x in k.kids if isinstance(x, Node)]
                lines[-1].append(('just', chars, c2.size)); continue
            if 'jtt-bd' in cls:
                lines[-1].append(self.badge(k, c2)); continue
            if 'jtt-v' in cls and 'jtt-vbox' not in cls:
                lines[-1].append(self.vert(k, c2, lr=True)); continue
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
        def bk(n, top):
            nonlocal h
            g = self.run(n.text(), ctx.but(font='DM'))
            parts.append(r'\hbox to %.3fbp{\hss\rule[%.3fbp]{0pt}{%.3fbp}%s\hss}' % (1.05 * em, -0.14 * em, em, g))
            h += 1
            parts.append(r'\kern%.3fbp' % (0.15 * em)); h += 0.15
        if bks and 'jtt-bk--o' in bks[0].cls: bk(bks[0], True)
        if vb is not None:
            cols = self.text_cols(vb, ctx)
            boxes, hm = [], 0
            for col in cols:
                b, hh = self.vcol(col, ctx)
                boxes.append(b); hm = max(hm, hh)
            boxes = boxes[::-1]
            parts.append(r'\hbox{' + ''.join(r'\hbox to %.3fbp{\hss\vtop{\kern0pt %s}\hss}' % (1.05 * em, b) for b in boxes) + '}')
            h += hm
        cl = [b for b in bks if 'jtt-bk--c' in b.cls]
        if cl:
            parts.append(r'\kern%.3fbp' % (0.15 * em)); h += 0.15
            for b in cl:
                g = self.run(b.text(), ctx.but(font='DM'))
                parts.append(r'\hbox to %.3fbp{\hss\rule[%.3fbp]{0pt}{%.3fbp}%s\hss}' % (1.05 * em, -0.14 * em, em, g)); h += 1
        tex = r'\vtop{\kern0pt\vbox{\offinterlineskip ' + ''.join(parts) + '}}'
        return ('obj', tex, 1.05, h, ctx.size, 'v')

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

def line_tex(line, W, halign, fs, inl, sqcenter=False):
    """줄 하나 → \\hbox to W"""
    if not line: return None
    size = max(it[-1] if it[0] != 'obj' else it[4] for it in line)
    has_v = any(it[0] == 'obj' and len(it) > 5 for it in line)
    st = '' if has_v else strut(size, fs)
    if len(line) == 1 and line[0][0] == 'just':
        chars = line[0][1]
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
        self.band_inset = cfg.get('bandInset', 0.9) * self.fs     # 띠의 왼쪽·오른쪽 글을 틀에서 띄우는 만큼
        self.notes = cfg.get('notes', True)                        # false: 표 밑의 주기(공통 범례)를 싣지 않는다
        self._bands = {}
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
        for cell in T.cells:
            c = base
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

    def fixed_w(self, T, side):
        L, _, R = self.blocks(T)
        TW = 0 if self.hang_title else self.title_tex(T)[2]
        fw = self.frame_w + self.frame_pad
        blk = sum(T.colW[j] for j in (L if side == 'L' else R if side == 'R' else L + R))
        return TW + 2 * fw + blk

    def cap(self, T, side, squeeze=False):
        """그 면에 실을 수 있는 열차 수. squeeze: 열 폭을 조금(squeeze 비율까지) 좁혀서"""
        P = self.P0 * (self.squeeze if squeeze else 1.0)
        return max(1, int((self.cw - self.fixed_w(T, side)) / P + 1e-6))

    def make_chunk(self, T, side, trains, avail=None):
        """면(side)에 실을 열차들로 조각을 만든다. avail: 조각이 쓸 폭(없으면 판면 폭).
        모자란 자리는 빈 열로 avail 끝까지, 남는 폭은 역명 칸에. 한두 편 넘치면 열 폭을 고르게 좁힌다"""
        L, Tc, R = self.blocks(T)
        room = (self.cw if avail is None else avail) - self.fixed_w(T, side)
        cap = max(1, int(room / self.P0 + 1e-6))
        if len(trains) > cap:
            P = room / len(trains)
            cols, extra = list(trains), 0
        else:
            P = self.P0
            cols = list(trains) + [('G', Tc[-1], g) for g in range(cap - len(trains))]
            extra = room - cap * self.P0
        keep = (L + cols) if side == 'L' else (cols + R) if side == 'R' else (L + cols + R)
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
        if T.head is None: return 0
        px = T.head.style.get('min-height') or T.head.style.get('height', '')
        m = re.match(r'([\d.]+)px', px)
        em = float(m.group(1)) / 14.4 if m else 1.5
        base = math.ceil(em * self.fs / self.R - 0.2) * self.R
        if bw is None: return base
        plan = self.band_plan(T, bw, part or ('열넷째' if self.page_title else None))
        need = (sum(p[3] for p in plan) + 0.3) * self.fs
        return max(base, math.ceil(need / self.R - 1e-6) * self.R)

    def band_plan(self, T, W, part=None):
        """띠를 글줄 폭 W(bp) 안에 짠다 → 줄 목록 [(왼쪽, 가운데, 오른쪽, 높이 em)].
        한 줄에 들면 한 줄. 아니면 위 줄에 왼쪽·오른쪽, 그 아래에 가운데를 「―」 뒤에서 나누어"""
        key = (id(T), round(W, 1), part)
        if key in self._bands: return self._bands[key]
        hd = T.head
        parts = [n for n in hd.kids if isinstance(n, Node)]
        if not any(n.cls & {'jtt-hl', 'jtt-hm', 'jtt-hrt'} for n in parts):
            parts = [Node('div', []), hd, Node('div', [])]       # 띠가 한 덩어리면 가운데에
        color = None
        col = hd.style.get('color')
        if col and col.startswith('#'): color = col[1:].upper()
        if len(color or '') == 3: color = ''.join(c * 2 for c in color)
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
            for node in self.split_center(parts[1], W, ctx):
                t = seg(node)
                plan.append(('', t[0], '', max(t[2], 1.25)))
        self._bands[key] = plan
        return plan

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
    def render_piece(self, T, ch, rows, x0, y0, with_notes, notes_room=True, line=None, part=None, hb=None):
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
        xs = [tx + fw + fp]
        for w in widths: xs.append(xs[-1] + w)
        fx1 = xs[-1] + fp + fw
        # 행 y 위치
        hb = self.headband_h(T, xs[-1] - xs[0] - 2 * self.band_inset, part) if hb is None else hb
        ty = y0 + fw + fp
        ys = [ty + hb]
        for r in rows: ys.append(ys[-1] + T.rowH[r])
        nh = self.notes_h(T) if with_notes else 0
        fy1 = ys[-1] + nh + fp + fw
        # 틀
        rects += self.frame_rects(fx0, y0, fx1, fy1, fw)
        # 제목 (쪽마다 하나만 다는 경우에는 표마다 달지 않는다)
        if self.page_title: pass
        elif side == 'R':
            tex.append(self.put_box(fx1 + 0.3 * fs, y0, TW - 0.3 * fs, ttlH, ttl, 'l', 't'))
        else:
            tex.append(self.put_box(tx - TW if self.hang_title else x0, y0, TW - 0.3 * fs, ttlH, ttl, 'l', 't'))
        # 노선 머리띠
        if hb:
            W = xs[-1] - xs[0] - 2 * self.band_inset
            plan = self.band_plan(T, W, part)
            def row(l, c, r, h):
                st = strut(h / 1.25, fs)
                if c and not (l or r): return r'\hbox to %.3fbp{%s\hss %s\hss}' % (W, st, c)
                if not c: return r'\hbox to %.3fbp{%s%s\hskip 1em plus 1fill %s}' % (W, st, l, r)
                # 왼쪽(방향·노선)·가운데(주요 역)·오른쪽(몇째)을 한 줄에. 사이를 늘이고 줄여 가운데를 맞춘다
                return r'\hbox to %.3fbp{%s%s\hskip 1em plus 1fill %s\hskip 1em plus 1fill %s}' % (W, st, l, c, r)
            # 틀 안쪽 끝에서 띠 아래 괘선까지의 가운데에 (틀과 표 사이 여백도 띠의 일부로 보인다)
            space = ty + hb - (y0 + fw)
            if len(plan) == 1:
                tex.append(self.put_box(xs[0] + self.band_inset, y0 + fw, W, space, row(*plan[0]), 'l', 'm'))
            else:
                tot = sum(p[3] for p in plan) * fs
                box = r'\vbox{\offinterlineskip %s}' % ''.join(row(*p) for p in plan)
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
            if t is None: t = line_tex(ln, W, al, fs, self.inl, sqc)
            if t: lts.append(t)
        if not lts: return
        has_v = any(it[0] == 'obj' and len(it) > 5 for ln in cell.lines for it in ln)
        vmargin = 0
        if has_v:
            vmargin = (0.2 if rc & {'jtt-f1', 'jtt-fr'} else 0.1) * fs
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
    ]
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
            if not fi: raise SystemExit('font not found: %s = %s' % (main, self.fonts.get(main)))
            lst = [x for x in (fb(r) for r in fbs) if x]
            lua.append('luaotfload.add_fallback("fb%s", {%s})' % (cmd, ', '.join('"%s"' % x for x in lst)))
            d, fn = os.path.split(fi.tex_path)
            tex.append(r'\newfontfamily\f%s{%s}[Path=%s/, FontIndex=%d, RawFeature={fallback=fb%s%s}]' % (cmd, fn, d, fi.idx, cmd, feat))
        return '\\directlua{\n' + '\n'.join(lua) + '\n}\n' + '\n'.join(tex)

    # ── 머리글·쪽 번호 ──
    def page_side_title(self, recto, lines):
        """쪽의 노선 이름: 바깥 여백에 세로로 크게 (쪽마다 하나)"""
        if not lines: return []
        size = self.cfg.get('pageTitleSize', 11) / self.fs
        em = size * self.fs
        c = Ctx('GB', size)
        items = []
        for k, ln in enumerate(lines):
            if k: items.append(r'\kern%.3fbp\hbox to %.3fbp{\hss\rule[%.3fbp]{0pt}{%.3fbp}%s\hss}\kern%.3fbp' % (
                0.2 * em, 1.2 * em, -0.12 * em, em, self.inl.run('·', c, True), 0.2 * em))
            for ch in ln:
                items.append(r'\hbox to %.3fbp{\hss\rule[%.3fbp]{0pt}{%.3fbp}%s\hss}' % (1.2 * em, -0.12 * em, em, self.inl.run(ch, c, True)))
        box = r'\vbox{\offinterlineskip ' + ''.join(items) + '}'
        gapm = 1.0 * MM
        if recto: x = self.mi + self.cw + gapm
        else: x = self.mo - gapm - 1.2 * em
        return [self.put_box(x, self.mt, 1.2 * em, 10, box, 'l', 't')]

    def page_furniture(self, folio, recto, runhead, part):
        fs = self.fs
        tex = []
        x0 = self.mi if recto else self.mo
        base_y = self.mt - self.cfg.get('headGap', 3.5) * MM     # 머리글·쪽 번호의 글줄 ~ 판면 위 끝
        Y = self.H - base_y
        rh = self.inl.run(runhead, Ctx('GB', 8.5 / fs)) if runhead else ''
        if part:
            rh += r'\ ' + self.inl.run('(%s)' % part, Ctx('M', 8.5 / fs))
        fo = self.inl.run(str(folio), Ctx('GB', 13 / fs))
        Yr = Y + 0.37 * (13 - 8.5)     # 머리글 글줄을 쪽 번호의 가운데 높이로
        if recto:
            tex.append(r'\put(%.3f,%.3f){\llap{%s}}' % (x0 + self.cw - 12 * MM, Yr, rh))
            tex.append(r'\put(%.3f,%.3f){\llap{%s}}' % (x0 + self.cw, Y, fo))
        else:
            tex.append(r'\put(%.3f,%.3f){\rlap{%s}}' % (x0 + 12 * MM, Yr, rh))
            tex.append(r'\put(%.3f,%.3f){\rlap{%s}}' % (x0, Y, fo))
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
            if not self.notes: T.notes = None
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
    def layout(self, tables):
        PH = self.ch
        gap = self.R * self.cfg.get('tierGap', 1.0)
        gapX = self.cfg.get('sideGap', 1.5) * MM
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
            if T.line not in pg['lines']: pg['lines'].append(T.line)
            return pc
        for T in tables:
            L, Tc, R = self.blocks(T)
            head = list(range(T.hEnd)); foot = list(range(T.fStart, T.nrow)); body = list(range(T.hEnd, T.fStart))
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
                        acc, best, bd = 0, None, 1e9
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
            if n <= sB:
                groups = [('single', n)]
            else:
                C = capL + capR
                G = -(-n // C)
                if G > 1 and n <= (G - 1) * (sL + sR): G -= 1
                if n <= G * C:
                    full, r = divmod(n, C)
                    groups = [('pair', capL, capR)] * full
                    if r:
                        if full >= 1 and r <= sB: groups.append(('single', r))
                        else:
                            kA = -(-r // 2); groups.append(('pair', kA, r - kA))
                else:
                    base, ex = divmod(n, G)
                    groups = []
                    for g in range(G):
                        k = base + (1 if g < ex else 0)
                        kA = -(-k // 2); groups.append(('pair', kA, k - kA))
            pieces = []
            for si, (b0, b1) in enumerate(secs):
                last_sec = si == len(secs) - 1
                ti = 0
                for gi, gdef in enumerate(groups):
                    used = gdef[1] if gdef[0] == 'single' else gdef[1] + gdef[2]
                    trs = Tc[ti:ti + used]; ti += used
                    notes = last_sec and gi == len(groups) - 1
                    rows, h = piece(b0, b1, last_sec, notes)
                    if gdef[0] == 'single':      # 좁은 표는 띠가 여러 줄이 될 수 있다
                        natB = self.fixed_w(T, 'B') + used * self.P0
                        narrowB = natB < self.cw * 0.62
                        bwS = self.band_w(natB) if narrowB else self.band_w(self.cw)
                        rows, h = piece(b0, b1, last_sec, notes, bwS)
                    for guard in range(200):
                        c = cur['c']
                        if gdef[0] == 'single':
                            k = used
                            # 앞의 좁은 표 옆에 나란히
                            pg = page(c)
                            if pg['pieces']:
                                prev = pg['pieces'][-1]
                                low = max(q['y'] for q in pg['pieces'])
                                if prev['narrow'] and abs(prev['y'] - low) < 0.01:
                                    x = prev['x'] + prev['nat'] + TWh + gapX
                                    nat = self.fixed_w(T, 'B') + k * self.P0
                                    if x + nat <= self.cw + 0.01 and prev['y'] + h <= PH + 0.01:
                                        pieces.append(put(T, c, trs, rows, prev['y'], notes, h, x, True, 'B', bwS))
                                        ys[c] = max(ys[c], prev['y'] + h)
                                        break
                            if sB >= k and top(c) + h <= PH + 0.01:
                                y0 = top(c)
                                narrow = self.fixed_w(T, 'B') + k * self.P0 < self.cw * 0.62
                                pieces.append(put(T, c, trs, rows, y0, notes, h, 0.0, narrow, 'B', bwS))
                                ys[c] = y0 + h
                                break
                            cur['c'] = c + 1
                        else:
                            kA = gdef[1]
                            if c % 2 == 0:
                                ya, yb = top(c), top(c + 1)
                                if abs(ya - yb) < 10 * MM: ya = yb = max(ya, yb)
                                if ya + h <= PH + 0.01 and yb + h <= PH + 0.01:
                                    pieces.append(put(T, c, trs[:kA], rows, ya, False, h))
                                    pieces.append(put(T, c + 1, trs[kA:], rows, yb, notes, h))
                                    ys[c] = ya + h; ys[c + 1] = yb + h
                                    break
                                # 왼쪽 면에 자리가 없고 오른쪽 면이 비었으면 오른쪽 면에서 시작해 넘겨 잇는다
                                cur['c'] = c + 1 if (ys[c + 1] == 0 and h <= PH + 0.01) else c + 2
                            else:
                                y1, y2 = top(c), top(c + 1)
                                if y1 + h <= PH + 0.01 and y2 + h <= PH + 0.01:
                                    pieces.append(put(T, c, trs[:kA], rows, y1, False, h))
                                    pieces.append(put(T, c + 1, trs[kA:], rows, y2, notes, h))
                                    ys[c] = y1 + h; ys[c + 1] = y2 + h
                                    cur['c'] = c + 1
                                    break
                                cur['c'] = c + 1
            for k, pc in enumerate(pieces):
                pc['part'] = (ORD_KO[k] if k < len(ORD_KO) else '%d째' % (k + 1)) if len(pieces) > 1 else ''
        # 단(같은 높이)마다 맨 오른쪽 조각만 빈 열로 판면 끝까지 채운다
        for pg in pages:
            for pc in pg['pieces']:
                others = sorted([q for q in pg['pieces'] if q is not pc and abs(q['y'] - pc['y']) < 0.01 and q['x'] > pc['x']], key=lambda q: q['x'])
                avail = min(others[0]['x'] - TWh - gapX - pc['x'], pc['nat']) if others else (self.cw - pc['x'])
                pc['ch'] = self.make_chunk(pc['T'], pc['side'], pc['trains'], avail)
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
                                               line=pc['T'].line, part=pc['part'], hb=pc['hb'])
                tex += t; rects += r
            # 머리글은 노선 이름만 (책을 넘기며 찾는 자리). 몇째 조각인지는 표의 세로 제목 끝에
            if self.page_title:
                tex += self.page_side_title(recto, pg['lines'])
                tex += self.page_furniture(folio, recto, '', '')
            else:
                tex += self.page_furniture(folio, recto, '·'.join(pg['lines']), '')
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
