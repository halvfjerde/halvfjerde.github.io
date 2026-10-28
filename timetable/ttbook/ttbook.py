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
        self.cls = ref.cls - {'jtt-t1', 'jtt-c1'}
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
        c.hscale = getattr(self, 'hscale', 1.0)
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
        hs_ = getattr(ctx, 'hscale', 1.0)
        if hs_ < 0.999 and not vertical:
            res = r'{\scalebox{%.3f}[1]{%s}}' % (hs_, res); wsum *= hs_
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
            elif it[0] == 'sq': w += it[3]
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
            if 'jtt-no' in cls and len(re.sub(r'\D', '', k.text())) >= 4: c2 = c2.but(size=c2.size * 0.92, hscale=0.95)   # 네 자리 열차번호는 조금 작게·장평 조금 좁게 (괘선에 붙지 않게)
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
                wn = max((self.line_w(l) for l in inner), default=0.0)       # 실제 폭(em): 넘칠 때만 좁힌다
                lines[-1].append(('sq', tex, r, wn, c2.size)); continue      # 끝 자리는 글자 크기 (높이 계산이 it[-1] 을 쓴다)
            if 'jtt-td' in cls:
                lines[-1].append(('obj', r'\hbox to %.3fbp{\hss %s\hss}' % (0.36 * c2.size * self.fs, self.run(k.text(), c2.but(font='M'))),
                                  0.36 * c2.size, 1.25 * c2.size, c2.size)); continue
            if 'tt-small' in cls: c2 = c2.but(size=c2.size * 0.75)
            if 'tt-bold' in cls: c2 = c2.but(font='GB')
            if 'tt-uarrow' in cls:          # 들어옴 화살표(➡ 를 위로)
                em_ = c2.size * self.fs
                lines[-1].append(('obj', r'\vbox{\hbox to %.3fbp{\hss\rotatebox{90}{%s}\hss}\kern%.3fbp}' % (
                    1.0 * em_, self.run('➡', c2.but(font='DG')), 0.1 * em_), 1.0 * c2.size, 1.2 * c2.size, c2.size))
                continue
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
        latin = bool(re.fullmatch(r'[A-Za-z]+', inner_node.text().strip()))
        if latin: c2 = c2.but(font='GB' if filled else 'G')       # KTX 등 로마자 등급: 고딕으로, 한글 두 자 폭에
        inner = self.flat(self.lines(inner_node, c2)[0])
        w, sx = 1.3, 1.0
        if latin: w, sx = 2.2, 0.92
        elif 'jtt-bd--w2' in k.cls: w = 2.2
        elif 'jtt-bd--w3' in k.cls: w, sx = 2.4, 0.78
        elif 'jtt-bd--w4' in k.cls: w, sx = 2.4, 0.6
        h = 1.3
        if 'jtt-bd--n' in k.cls: w = max(1.3, len(inner_node.text()) * 0.55 + 0.4)
        wb, hb = w * sm * self.fs, h * sm * self.fs
        tex = r'\ttbadge{%.3f}{%.3f}{%d}{%.3f}{%.3f}{%s}' % (wb, hb, 1 if filled else 0, sx, self.c * ctx.size * self.fs, inner)
        return ('obj', tex, w * sm, h * sm, ctx.size)

    # 세로쓰기 (jtt-v: 왼쪽→오른쪽 열, jtt-vb: 오른쪽→왼쪽)
    def vcol(self, line_items, ctx):
        """한 열의 글자들을 쌓은 \\vbox 와 높이(em). 가로로 쓴 숫자가 있으면 그 폭을 self._vcolw 에"""
        rows, h = [], 0.0
        wcol = 1.0
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
                if ch.isdigit():                 # 숫자(열차번호 등): 명조로, 세로쓰기 안에서도 가로로 (열 폭은 숫자만큼 넓어진다)
                    j = i
                    while j < len(txt) and txt[j].isdigit(): j += 1
                    run = txt[i:j]
                    g_ = self.run(run, c.but(font='M'), True)
                    wcol = max(wcol, self.wc.get(g_, 0.55 * len(run)) * c.size)
                    rows.append(r'\hbox to %.3fbp{\hss\rule[%.3fbp]{0pt}{%.3fbp}%s\hss}' % (em, -0.12 * em, em, g_))
                    h += 1; i = j; continue
                if is_latin(ch):
                    j = i
                    while j < len(txt) and is_latin(txt[j]): j += 1
                    run = txt[i:j]
                    wl = sum(0.55 if x.isupper() else 0.5 for x in run)
                    rows.append(r'\hbox to %.3fbp{\hss\rotatebox{-90}{%s}\hss}' % (em, self.run(run, c)))
                    h += wl; i = j; continue
                rows.append(r'\hbox to %.3fbp{\hss\rule[%.3fbp]{0pt}{%.3fbp}%s\hss}' % (em, -0.12 * em, em, self.run(ch, c, True)))
                h += 1; i += 1
        self._vcolw = wcol
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
            boxes.append((b, max(pitch, self._vcolw))); hmax = max(hmax, h)
        if not lr: boxes = boxes[::-1]
        em = ctx.size * self.fs
        # 가로로 쓴 숫자가 든 여러 줄: 줄 사이를 띄운다 (옆줄 숫자와 붙어 한 수로 읽히지 않게)
        gap = 0.5 if len(boxes) > 1 and any(w_ > pitch + 0.01 for _, w_ in boxes) else 0.0
        tex = r'\hbox{' + (r'\kern%.3fbp ' % (gap * em)).join(r'\hbox to %.3fbp{\hss\vtop{\kern0pt %s}\hss}' % (w_ * em, b) for b, w_ in boxes) + '}'
        return ('obj', tex, sum(w_ for _, w_ in boxes) + gap * (len(boxes) - 1), hmax, ctx.size, 'v')

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
            hs_, ws_ = [], []
            for col in cols:
                b, hh = self.vcol(col, ctx)
                boxes.append(b); hs_.append(hh); hm = max(hm, hh); ws_.append(max(1.05, self._vcolw))   # 가로로 쓴 두 자리 숫자는 그만큼 넓게
            boxes, hs_, ws_ = boxes[::-1], hs_[::-1], ws_[::-1]
            gap = 0.3 if len(boxes) > 1 and any(w_ > 1.06 for w_ in ws_) else 0.0      # 옆줄 숫자와 붙어 한 수로 읽히지 않게
            # 짧은 줄은 괄호 사이 가운데에
            parts.append(r'\hbox{' + (r'\kern%.3fbp ' % (gap * em)).join(r'\hbox to %.3fbp{\hss\vtop{\kern%.3fbp %s}\hss}' % (w_ * em, (hm - hh) / 2 * em, b)
                                             for b, hh, w_ in zip(boxes, hs_, ws_)) + '}')
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
            wn = it[3] * fs
            sc = min(1.0, (W - 2 * pad) / wn) if wn > 0 else 1.0       # 칸에 넘칠 때만 가로로 좁힌다 (두 글자는 그대로)
            body.append(r'\scalebox{%.3f}[1]{%s}' % (sc, it[1]) if sc < 0.999 else it[1])
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
        self.refs = {}                                            # \\TTREF{k} → 쪽 번호로 채울 주

    # ── 칸의 괘선(위키 CSS 와 같은 셈) ──
    def borders(self, T, cell):
        cls, st = cell.cls, cell.style
        rc = T.rowcls[cell.r]
        left = 1
        if cls & {'jtt-c1', 'jtt-t1', 'jtt-st', 'jtt-ad', 'jtt-rc', 'jtt-cx'}: left = 0
        if 'jtt-rc1' in cls: left = 2
        if getattr(T, 'both', False) and cell.c > 0 and T.kind[cell.c][0] == 'L' and T.kind[cell.c - 1][0] == 'T': left = 2   # 상하병기: 가운데 역명의 왼쪽
        if getattr(T, 'both', False) and 'jtt-c1' in cls and T.kind[cell.c][0] == 'T': left = 1     # 상하병기: 바깥 빈 열과 첫 열차 사이
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
            if getattr(cell, 'refin', False): h += 0.1          # 밑에 쪽 번호 표지가 붙은 주: 표지 밑 여백으로 갈음
            elif rc & {'jtt-f1', 'jtt-fr'}: h += 0.4
            else: h += 0.2
        return h

    def aim_rows(self, T):
        """조준선을 긋는 행: 착발을 나누지 않은(한 행) 굵은 역명(주요역)의 행"""
        if getattr(T, '_aim', None) is not None: return T._aim
        out = set()
        for cl in T.cells:
            if 'jtt-st' in cl.cls and 'jtt-th' not in cl.cls and cl.rs == 1 and T.kind[cl.c][0] == 'L' and T.hEnd <= cl.r < T.fStart \
                    and cl.node.find(lambda n: n.cls & {'jtt-b', 'jtt-k', 'tt-bold'}) is not None:
                out.add(cl.r)
        T._aim = out
        return out

    ARW = 0.5           # 진행 방향 화살표 곁 여백 (em): 양옆 칸(착발·첫 열차, 마지막 열차·오른쪽 역명)에 반씩

    def arrow_ads(self, T):
        """화살표를 둘 칸 {열: 'l'|'r'} (열차 열과 맞닿은 쪽): 왼쪽 묶음의 착발 칸, 오른쪽 역명 칸"""
        out = {}
        for j, k in enumerate(T.kind):
            if k not in (('L', 'ad'), ('R', 'st')): continue
            if j + 1 < len(T.kind) and T.kind[j + 1][0] == 'T': out[j] = 'r'
            elif j > 0 and T.kind[j - 1][0] == 'T': out[j] = 'l'
        return out

    def arrow_room(self, T):
        """착발 칸을 화살표만큼 넓힌다. 역명 칸에 남는 폭이 있으면 그만큼 덜어 (표의 폭을 그대로)"""
        em = self.fs
        ads = self.arrow_ads(T)
        if not ads: return
        stc = [j for j, k in enumerate(T.kind) if k == ('L', 'st')]
        names = [len(c.node.text().strip()) for c in T.cells if c.c in stc and c.cs == 1 and 'jtt-th' not in c.cls and c.node.text().strip()]
        need = (max(names + [3]) + 0.6) * em
        for j in ads:
            if T.kind[j] == ('R', 'st'):        # 오른쪽 역명: 제 칸의 남는 폭 안에서 (모자라면 그만큼만 넓힌다)
                nm_ = [len(c.node.text().strip()) for c in T.cells if c.c == j and c.cs == 1 and 'jtt-th' not in c.cls and c.node.text().strip()]
                need_r = (max(nm_ + [2]) + 0.6) * em
                T.colW[j] = max(T.colW[j], need_r + self.ARW * em)
                continue
            T.colW[j] += self.ARW * em          # 반은 그 칸의 글자 곁, 반은 맞닿은 열차 열로 (짤 때 옮긴다)
            if stc:
                take = min(self.ARW * em, max(0.0, T.colW[stc[0]] - need))
                T.colW[stc[0]] -= take

    def arrow_rects(self, x, y0, y1, dr, shaft=None):
        """진행 방향 화살표 (그림대로): 꼬리는 위가 V 로 파이고 아래가 V 로 모이는 오각형 깃, 촉은 뒤가 파인 날개 촉.
        축은 깃의 파인 곳부터 촉 끝까지 (깃·촉 속으로 지나간다). 깃·촉은 속 빈 가는 선"""
        em = self.fs
        W = 0.24 * em                             # 깃·촉 반폭 (좌우로 좁게)
        Ht = max(1.2 * em, 1.8 * self.R - 0.4 * em)    # 깃 높이 (행 1.8개 남짓)
        hl = 1.0 * em                             # 촉 길이
        lw = self.rw[1]
        yt, yb = y0 + 0.08 * em, y1 - 0.06 * em
        if dr == 'u': yt, yb = y1 - 0.08 * em, y0 + 0.06 * em      # 위로: 꼬리가 아래
        s = 1 if yb > yt else -1
        notch = yt + s * 0.32 * Ht
        side = yt + s * 0.72 * Ht
        tail = [(x - W, yt), (x, notch), (x + W, yt), (x + W, side), (x, yt + s * Ht), (x - W, side)]
        back = yb - s * hl
        head = [(x - W, back), (x + W, back), (x, yb)]          # 촉: 역삼각형
        return [('line', [(x, notch), (x, yb)], shaft or lw),      # 축은 촉 끝까지 (촉 속으로 지나간다)
                ('line', tail + [tail[0]], lw),
                ('line', head + [head[0]], lw)]

    def aim_rects(self, x, y, w, h):
        """조준선: 칸 가운데 높이에 긴 점 셋"""
        t = self.rw[1]; dl = 0.18 * w
        ym = y + h / 2 - t / 2
        return [('box', x + 0.11 * w + 0.30 * w * k, ym, x + 0.11 * w + 0.30 * w * k + dl, ym + t, t) for k in range(3)]

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
        dayrows = {cl.r for cl in T.cells if (cl.c == 0 or (getattr(T, 'both', False) and T.kind[cl.c][0] == 'L'))
                   and re.sub(r'\s', '', cl.node.text()) in ('운행일', '운행일주의', '비고')}
        T.dayrow = max(dayrows) if dayrows else None
        for cl in T.cells:             # 비고 행: 내용은 위에 붙이고(쪽의 남는 자리만큼 늘어난다), 이름 칸은 가운데
            if cl.r in dayrows:
                cl.style = dict(cl.style)
                cl.style['vertical-align'] = 'middle' if T.kind[cl.c][0] in ('L', 'R') else 'top'
        for cl in T.cells:             # 비고의 「↑ / …선 / 경유」(가로): 맨 위 ↑ 는 굵은 위 화살표로
            if cl.r in dayrows and T.kind[cl.c][0] == 'T' and not cl.node.find(lambda n: 'jtt-v' in n.cls):
                mu = re.fullmatch(r'↑(.+선)경유', re.sub(r'\s', '', cl.node.text()))
                if mu:
                    nd = Node('td', []); nd.kids += [Node('span', [('class', 'tt-uarrow')]), Node('br', []), mu.group(1), Node('br', []), '경유']
                    cl.node = nd
                    cl.style = dict(cl.style); cl.style['vertical-align'] = 'top'
        if self.cfg.get('daysCompact', True):
            for cl in T.cells:
                if cl.r in dayrows and T.kind[cl.c][0] == 'T' and cl.node.find(lambda n: 'jtt-v' in n.cls):
                    t = re.sub(r'\s', '', cl.node.text())
                    if '연결' in t or '분리' in t: continue          # 병결 비고(개조식)는 적은 그대로 세로쓰기
                    # 요일 뭉치만 작은 가로 글씨로(세 자까지 한 줄, 넷~여섯 자는 두 자씩 세 줄까지).
                    # 나머지(「운행」, 「…선 경유」 등)는 관습대로 보통 크기 세로쓰기
                    m2 = re.fullmatch(r'↑(.+?선)경유(.+선)경유', t)
                    if m2:          # 들어온 선(↑)과 나간 선(↓)을 함께: 위 화살표·세로 두 줄, 아래 화살표·세로 두 줄
                        nd = Node('td', [])
                        for cls_, ln_ in (('tt-uarrow', m2.group(1)), ('tt-darrow', m2.group(2))):
                            vt = Node('span', [('class', 'jtt-v tt-rl')]); vt.kids += [ln_, Node('br', []), '경유']
                            nd.kids += [Node('span', [('class', cls_)]), Node('br', []), vt, Node('br', [])]
                        nd.kids.pop()
                        cl.node = nd
                        cl.style = dict(cl.style); cl.style['vertical-align'] = 'top'
                        continue
                    mv = re.match(r'(↑?)(.+선)경유$', t)
                    if mv:          # 「…선 경유」: 굵은 화살표 밑에 두 줄 세로쓰기(…선 | 경유). ↑: 표의 첫 역 앞 다른 선에서 들어옴(위 화살표)
                        ar = Node('span', [('class', 'tt-uarrow' if mv.group(1) else 'tt-darrow')])
                        mv = re.match(r'↑?(.+선)경유$', t)
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
                    lab_ = next((re.sub(r'\s', '', c_.node.text()) for c_ in T.cells if c_.r == cl.r and c_.c == 0), '')
                    if lab_ == '운행일' and not rest:   # 운행일 행: 요일만 작은 가로 글씨로 (세 자까지 한 줄, 넘으면 두 자씩)
                        sm = Node('span', [('class', 'tt-small')])
                        per_ = 3 if len(days) <= 3 else 2
                        for i in range(0, len(days), per_):
                            if i: sm.kids.append(Node('br', []))
                            sm.kids.append(days[i:i + per_])
                        nd = Node('td', []); nd.kids.append(sm)
                        cl.node = nd
                        cl.style = dict(cl.style); cl.style['vertical-align'] = 'top'
                        continue
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
        refs_ = []
        for cell in T.cells:
            c = base
            if getattr(cell, 'small', None): c = c.but(size=cell.small)
            for cl, f in FONT_OF_CLASS.items():
                if cl in cell.cls: c = c.but(font=f)
            if ('jtt-ad' in cell.cls or 'jtt-mk' in cell.cls) and 'jtt-th' not in cell.cls: c = c.but(size=0.8)
            if 'jtt-r-ad' in cell.cls and 'jtt-th' not in cell.cls: c = c.but(size=0.8)
            if 'jtt-no' in cell.cls and len(re.sub(r'\D', '', cell.node.text() or '')) >= 4:
                c = c.but(size=c.size * 0.92, hscale=0.95)       # 네 자리 열차번호(칸 자체가 jtt-no): 조금 작게·장평 조금 좁게, 괘선에서 띄운다
            # 칸의 글자 색(fc=)·굵기(fw=b): 재래선 표에 합친 KTX 열차 등
            col = (cell.style or {}).get('color', '')
            if col.startswith('#'):
                col = col[1:].upper()
                c = c.but(color=''.join(x * 2 for x in col) if len(col) == 3 else col)
            m_fs = re.match(r'\s*([\d.]+)(em|%)', (cell.style or {}).get('font-size', ''))     # fs= (1.44em 등): 글자 크기
            if m_fs: c = c.but(size=c.size * float(m_fs.group(1)) / (100.0 if m_fs.group(2) == '%' else 1.0))
            if 'jtt-text' in (cell.style or {}).get('font-family', ''): c = c.but(font='M')     # font=text: 본문 명조로 (DiaPro 기호 대신)
            if ('jtt-fb' in cell.cls or '700' in (cell.style or {}).get('font-weight', '')) and c.font == 'DM' \
                    and re.fullmatch(r'[\d\s,]*\d[\d\s,]*', cell.node.text() or ''): c = c.but(font='DGB')   # 굵게는 시각에만
            cell.lines = self.inl.lines(cell.node, c)
            cell.lines = [l for l in cell.lines] if any(cell.lines) else []
            cell.need = self.cell_need(T, cell, cell.lines)
            ref = self.ref_of(T, cell) if self.cfg.get('pageRefs', True) else None
            if ref: refs_.append((cell, ref, c))
        # 「…선 경유」「…로 연결」 등: 다음 줄에 그 열차가 실린 쪽 번호를 네모 표지로 (쪽 번호는 짠 뒤에 채운다).
        # 세로 주 바로 밑(없으면 위) 칸이 ║ 이면 그 칸에 (행이 높아지지 않게), 아니면 주 칸 끝에 한 줄 더
        for cell, ref, c in refs_:
            sm = c.size * 0.76
            n_ = len(ref['nums']) if ref['kind'] == 'train' else 1
            w_ = n_ * 1.5 * sm + (n_ - 1) * 0.2 * sm
            mk = r'\TTREF{%d}' % len(self.refs)
            self.refs[mk] = dict(ref, T=T, col=cell.c, size=c.size, color=c.color)
            item = [('obj', mk, w_, 1.3 * sm, c.size)]
            gap_ = [('obj', r'\rule{0pt}{%.3fbp}' % (0.25 * sm * fs), 0.0, 0.25 * sm, c.size, 'v')]      # 위 글과 살짝 띄운다
            host = None
            if cell.r < T.fStart:
                for rr in (cell.r + cell.rs, cell.r - 1):
                    nb = T.occ.get((rr, cell.c))
                    if T.hEnd <= rr < T.fStart and nb is not None and not isinstance(nb, Ghost) and nb.rs == 1 \
                            and nb.node.text().strip() == '║' and not getattr(nb, 'refhost', False):
                        host = nb; break
            if host is not None:      # 그 ║ 칸을 주 칸에 합쳐(한 병합 칸 안에) 주 밑에 표지
                self.refs[mk]['host'] = self.inl.flat(host.lines[0]) if host.lines else ''
                host.refhost = True
                if host.r < cell.r: cell.r = host.r
                cell.rs += 1
                T.cells.remove(host)
                for rr_ in range(cell.r, cell.r + cell.rs): T.occ[(rr_, cell.c)] = cell
                cell.lines = cell.lines + [gap_, item]
                cell.refin = True
                cell.need = self.cell_need(T, cell, cell.lines)
            else:                     # 주 칸 끝에 한 줄 더: 세로쓰기의 띄어쓰기는 빼고(표지가 사이를 띄운다) 높이를 아낀다
                def nospace(n):      # 「익산 분리」의 띄어쓰기는 남긴다
                    n.kids = [re.sub(r' (?!분리|연결)', '', k) if isinstance(k, str) else (nospace(k) or k) for k in n.kids]
                nd = copy.deepcopy(cell.node); nospace(nd); cell.node = nd
                ls_ = [l for l in self.inl.lines(nd, c)]
                # 끝 역에서 나가는 주석 열(「…선 경유」 + ⬏): 표지는 화살표 앞에
                cell.lines = (ls_[:-1] + [gap_, item] + ls_[-1:]) if re.sub(r'\s', '', cell.node.text()).endswith('⬏') and len(ls_) > 1 else ls_ + [gap_, item]
                cell.refin = True
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
        self.arrow_room(T)

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
            T.mirror = not T.Rc and not getattr(T, 'both', False)
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
        if getattr(T, 'both', False):          # 상하행 한 표: 하행 | 역명 | 상행. 남는 폭은 바깥쪽 빈 열(‥)로 (왼쪽·오른쪽 반씩)
            P = self.P0 if len(trains) <= cap else room / len(trains)
            nG = max(0, cap - len(trains)) if avail is not None else 0
            dn = [j for j in trains if j < min(L)]; upc = [j for j in trains if j > max(L)]
            gl = [('G', (dn or upc)[0], 1000 + g) for g in range(nG // 2)]
            gr = [('G', (upc or dn)[-1], 2000 + g) for g in range(nG - nG // 2)]
            keep = gl + dn + list(L) + upc + gr
            return {'side': side, 'cols': keep, 'trains': gl + dn + upc + gr, 'extra': max(0, room - (len(trains) + nG) * P), 'mirror': False, 'P': P}
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
        def seg(node, c_=None):
            ls = self.inl.lines(node, c_ or ctx)
            ln = ls[0] if ls and ls[0] else []
            return (self.inl.flat(ln), self.inl.line_w(ln) * fs, line_height(ln) if ln else 0.0)
        L, C = seg(parts[0]), seg(parts[1])
        if part and self.page_title:          # 몇째 조각인지는 띠 오른쪽에
            ln = [('tex', self.inl.run('(%s)' % part, Ctx('M', 1.0, color)), 1.0)]
            R = (self.inl.flat(ln), self.inl.line_w(ln) * fs, line_height(ln))
        else:
            R = seg(parts[2], Ctx('M', 1.0, color))      # 오른쪽 주(운행일 등): 숫자까지 명조로
        cnode = parts[1]
        if L[0] and not C[0] and not R[0]: L, C, cnode = ('', 0.0, 0.0), L, parts[0]      # 이름만 있는 띠(관광열차·고속버스): 가운데에
        gap = 1.0 * fs
        if not L[0] and not R[0] and C[0] and C[1] + 2 * gap > W and (W - 2 * gap) / C[1] >= 0.5:
            C = seg(cnode, ctx.but(hscale=(W - 2 * gap) / C[1]))      # 이름만 있는 좁은 띠(나란히 선 고속버스 노선표): 두 줄로 나누지 않고 가로로 좁혀 한 줄에
        if L[1] + C[1] + R[1] + 2 * gap <= W + 0.01 or not C[0]:
            plan = [(L[0], C[0], R[0], max(L[2], C[2], R[2], 1.25))]
        else:
            plan = []
            Ls = [L]
            if L[0] and L[1] + (R[1] + gap if R[0] else 0) > W + 0.01:      # 노선·방향도 넘치면 마지막 띄어쓰기에서 줄을 바꾼다 (좁은 표)
                nd = copy.deepcopy(parts[0])
                def cut(n):
                    for i in range(len(n.kids) - 1, -1, -1):
                        k = n.kids[i]
                        if isinstance(k, str):
                            j = k.rstrip().rfind(' ')
                            if j > 0: n.kids[i:i + 1] = [k[:j], Node('br', []), k[j + 1:]]; return True
                        elif cut(k): return True
                    return False
                if cut(nd):
                    Ls = [(self.inl.flat(ln), self.inl.line_w(ln) * fs, line_height(ln) if ln else 0.0) for ln in self.inl.lines(nd, ctx) if ln]
            if L[0] or R[0]: plan.append((Ls[0][0], '', R[0], max(Ls[0][2], R[2], 1.25)))
            for x_ in Ls[1:]: plan.append((x_[0], '', '', max(x_[2], 1.25)))
            # 줄이 바뀌면 가운데(구간)는 다른 한쪽이 있는 반대편으로 민다
            al = 'r' if (L[0] and not R[0]) else 'l' if (R[0] and not L[0]) else 'c'
            cl = [seg(node) for node in self.split_center(cnode, W, ctx)]
            if any(t[1] > W + 0.01 for t in cl) and (L[0] or R[0]): cl = []     # 아주 좁은 조각(이어지는 끝 몇 편): 구간은 빼고 노선·방향만
            for t in cl:
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
        # 화살표 곁 여백: 착발(오른쪽 역명) 칸에 넣어 둔 몫의 반을 맞닿은 열차 열로 (화살표 양옆이 같게)
        ads0 = self.arrow_ads(T)
        self.cur_tpad = {}               # 넓힌 열차 열: 글은 본디 폭에 (화살표 쪽을 비운다)
        for ci, j in enumerate(cols):
            if isinstance(j, tuple) or j not in ads0: continue
            k2 = ci + (1 if ads0[j] == 'r' else -1)
            if 0 <= k2 < len(cols) and kind_of(T, cols[k2])[0] == 'T':
                widths[ci] -= self.ARW / 2 * self.fs; widths[k2] += self.ARW / 2 * self.fs
                if not isinstance(cols[k2], tuple): self.cur_tpad[cols[k2]] = 'l' if ads0[j] == 'r' else 'r'
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
        # 진행 방향 화살표: 착발 칸의 열차 쪽 (상하병기는 왼쪽 ↓·오른쪽 ↑)
        ads_ = self.arrow_ads(T)
        arr_ = []
        for ci, j in enumerate(cols):
            if isinstance(j, tuple) or j not in ads_: continue
            sd = ads_[j]
            k2 = ci + (1 if sd == 'r' else -1)
            if not (0 <= k2 < len(cols)) or kind_of(T, cols[k2])[0] != 'T': continue
            arr_.append((ci, j, sd, ('u' if sd == 'r' else 'd') if (getattr(T, 'both', False) and kind_of(T, j)[0] == 'L') else 'd'))
        self.cur_arrow = {j: {sd} for ci, j, sd, _ in arr_}
        self.arrow_bounds = {(ci + 1 if sd == 'r' else ci) for ci, j, sd, _ in arr_}     # 이 경계의 세로 괘선은 화살표가 대신한다
        seen = set()
        aims_ = []
        for r in rows:
            for j in cols:
                cell = cell_of(T, r, j)
                if cell is None or id(cell) in seen: continue
                if isinstance(cell, Ghost):
                    seen.add(id(cell))
                    if T.hEnd <= r < T.fStart and r in rowpos and r in self.aim_rows(T):     # 주요역 행: 조준선
                        ci = colpos[j]; ri = rowpos[r]
                        aims_.append((xs[ci], ys[ri], xs[ci + 1] - xs[ci], ys[ri + 1] - ys[ri]))
                        continue
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
                if cell.rs == 1 and cell.r in self.aim_rows(T) and kind_of(T, j)[0] == 'T' and cell.node.text().strip() in ('', '‥'):
                    aims_.append((cx, cy, cw, chh)); continue          # 주요역 행의 빈칸·‥: 조준선
                self.draw_cell(T, cell, cx, cy, cw, chh, tex)
        for a_ in aims_: rects += self.aim_rects(*a_)
        srows = [i for i, r in enumerate(rows) if T.hEnd <= r < T.fStart]
        if len(srows) >= 2:
            for ci, j, sd, dr in arr_:
                k_ = ci + 1 if sd == 'r' else ci
                rects += self.arrow_rects(xs[k_], ys[srows[0]], ys[srows[-1] + 1], dr, self.rw[2])
        self.cur_arrow = {}
        # 괘선
        rects += self.grid_rules(T, rows, cols, xs, ys, side)
        self.arrow_bounds = set(); self.cur_tpad = {}
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
        sd_ = getattr(self, 'cur_arrow', {}).get(cell.c)
        tp_ = getattr(self, 'cur_tpad', {}).get(cell.c)
        if tp_ and cell.cs == 1:                     # 화살표 곁 열차 열: 넓힌 만큼을 비우고 본디 폭에 맞춘다
            if tp_ == 'l': x += self.ARW / 2 * fs
            w -= self.ARW / 2 * fs
        if sd_ and ('jtt-ad' in cls or 'jtt-rc' in cls) and 'jtt-th' not in cls and T.hEnd <= cell.r < T.fStart:   # 화살표 곁을 비운다
            if 'l' in sd_: x += self.ARW / 2 * fs
            w -= self.ARW / 2 * fs

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
        # 가로 명조 열차번호·세로쓰기 주: 글자 양옆 여백(글리프의 곁)이 이미 있으니 칸 폭을 거의 다 쓴다 (넘칠 때만 좁힌다)
        isno = 'jtt-no' in cls or cell.node.find(lambda n: 'jtt-no' in n.cls) is not None
        isv = any(it[0] == 'obj' and len(it) > 5 for ln in cell.lines for it in ln)
        tight = False
        if isv: pad = 0.03
        elif isno: pad = 0.14           # 네 자리 열차번호도 괘선에 붙지 않게 양옆을 조금 비운다
        elif 'jtt-th' not in cls and 'jtt-st' not in cls and any(
                ln and not any(it[0] == 'just' for it in ln) and self.inl.line_w(ln) * fs > w - 2 * (pad + 0.06) * fs for ln in cell.lines):
            pad, tight = 0.05, True      # 칸에 넘쳐 가로로 좁히는 글(동대구·금토일 등): 양옆 여백을 줄여 덜 좁힌다
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
                pe = 0.0 if (isno or isv or tight) else 0.06
                t = line_tex(ln, W, al, fs, self.inl, sqc, pe)
            if t: lts.append(t)
        if not lts: return
        has_v = any(it[0] == 'obj' and len(it) > 5 for ln in cell.lines for it in ln)
        vmargin = 0
        if has_v:
            vmargin = (0.2 if rc & {'jtt-f1', 'jtt-fr'} else 0.1) * fs
        if cell.node.find(lambda n: 'tt-darrow' in n.cls or 'tt-uarrow' in n.cls): vmargin = 0.1 * fs  # 이어짐 화살표는 위 괘선 가까이
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
                if k in getattr(self, 'arrow_bounds', ()) and T.hEnd <= rows[i] < T.fStart: w = 0
                y0, y1 = ys[i], ys[i + 1]
                if seg and seg[0] == w and abs(seg[2] - y0) < 0.01: seg[2] = y1
                else:
                    if seg and seg[0]: out.append(('v', xs[k], seg[1], seg[2], seg[0]))
                    seg = [w, y0, y1]
            if seg and seg[0]: out.append(('v', xs[k], seg[1], seg[2], seg[0]))
        # 경유 등 세로 주석과 그 앞뒤로 이어지는 ║ 들: 한 덩어리로 보고 사이의 구획선은 긋지 않는다 (표의 맨 위·아래 괘선은 그대로)
        nrun = self.note_runs(T)
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
                    if (id(a), id(b)) in nrun: w = 0
                    if band_start: w = 'd'
                    elif rows[i] != rows[i - 1] + 1 and w == 0: w = 1
                x0, x1 = xs[k], xs[k + 1]
                if seg and seg[0] == w and abs(seg[2] - x0) < 0.01: seg[2] = x1
                else:
                    if seg and seg[0]: out.append(('h', seg[1], seg[2], ys[i], seg[0]))
                    seg = [w, x0, x1]
            if seg and seg[0]: out.append(('h', seg[1], seg[2], ys[i], seg[0]))
        return out

    def narrow_st(self, T):
        """역명 칸을 가장 긴 역 이름·머리 이름(열차번호 등)에 맞춰 좁힌다"""
        em = self.fs
        for j, (k, role) in enumerate(T.kind):
            if role != 'st' or k not in ('L', 'R'): continue
            names = [len(c.node.text().strip()) for c in T.cells if c.c == j and c.cs == 1 and 'jtt-th' not in c.cls and c.node.text().strip()]
            labs = [(len(c.node.text().strip()), sum(T.colW[c.c + i] for i in range(1, c.cs))) for c in T.cells
                    if c.c == j and 'jtt-th' in c.cls and c.node.text().strip()]
            need = max([x + 0.6 for x in names] + [x + 0.6 - w / em for x, w in labs] + [3.0]) * em
            T.colW[j] = min(T.colW[j], need)

    def ref_of(self, T, cell):
        """열차 칸의 주가 다른 표를 가리키면 {kind: via|train, ...}: 「…선 경유」(그 노선 표의 같은 열차), 「…로 연결·분리」「…/발/654」(그 번호의 열차)"""
        if T.kind[cell.c][0] != 'T' or cell.r < T.hEnd: return None
        t = re.sub(r'\s', '', cell.node.text())
        m = re.fullmatch(r'[↑↱]?(.+?선)(?:경유|[가-힣]+(?:분리|연결))(?:.+선경유)?⬏?', t)
        if m:
            # 나가는 주는 그 열차들 뒤(오른쪽)에: 보통은 끝에 ⬏. 상하병기의 상행 쪽(가운데 역명 오른쪽)은 위아래가 뒤집혀 ↱ 이 나가는 주
            up_ = getattr(T, 'both', False) and any(k_[1] == 'st' and j_ < cell.c for j_, k_ in enumerate(T.kind))
            return {'kind': 'via', 'name': m.group(1), 'out': t.startswith('↱') if up_ else t.endswith('⬏')}
        if re.search(r'연결|분리', t) or re.fullmatch(r'\D+(발|착)\d+', t):
            nos = []
            def walk(n):
                for k in n.kids:
                    if isinstance(k, str): continue
                    if 'jtt-no' in k.cls: nos.append(re.sub(r'\D', '', k.text()))
                    else: walk(k)
            walk(cell.node)
            nums = [x for x in nos if x] or re.findall(r'\d{2,5}', t)       # N{668}/N{672} 은 열차번호 꼴마다
            if nums: return {'kind': 'train', 'nums': nums}
        return None

    def colno(self, T):
        """열차 열 → 열차 번호"""
        if getattr(T, '_colno', None) is None:
            T._colno = {}
            for c in T.cells:
                if c.r < T.hEnd and T.kind[c.c][0] == 'T' and c.node.find(lambda n: 'jtt-no' in n.cls) is not None:
                    d = re.sub(r'\D', '', c.node.text())
                    if d: T._colno[c.c] = d
        return T._colno

    def page_badge(self, n, size, color, tsize=None):
        """쪽 번호 네모 표지 (무궁화 등급 표지처럼 속 빈 네모). tsize: 곁의 글자 크기 (네모의 가운데를 그 글자의 가운데에)"""
        sm = size * 0.76
        inner = self.inl.run(str(n), Ctx('DG', sm, color))
        w = max(1.3, len(str(n)) * 0.55 + 0.4)
        return r'\ttbadge{%.3f}{%.3f}{0}{1.000}{%.3f}{%s}' % (w * sm * self.fs, 1.3 * sm * self.fs, self.inl.c * (tsize or size) * self.fs, inner)

    def resolve_refs(self, body):
        """짠 뒤: 쪽마다 실린 열차로 찾아 \\TTREF{k} 를 쪽 번호 네모 표지로"""
        first = self.cfg.get('firstFolio', 2)
        where = collections.defaultdict(list)          # 열차 번호 → [(쪽, 표)]
        for p, pg in enumerate(self.pages):
            for pc in pg['pieces']:
                cn = self.colno(pc['T'])
                for j in pc['trains']:
                    if not isinstance(j, tuple) and j in cn: where[cn[j]].append((p, pc['T']))
        badge = self.page_badge
        par = collections.defaultdict(list)            # 「381/분리」 주에 적힌 열차 번호 → 그 주(어버이 열차)가 실린 쪽
        for r in self.refs.values():
            if r['kind'] != 'train': continue
            pno = self.colno(r['T']).get(r['col'])
            for n in r['nums']:
                par[n] += [p for p, X in where.get(pno, []) if X is r['T']]
        out = {}
        for mk, r in self.refs.items():
            T = r['T']
            if r['kind'] == 'via':
                cn_ = self.colno(T)
                if r.get('out'): no = cn_.get(r['col']) or next((cn_[j] for j in sorted(cn_, reverse=True) if j < r['col']), None)   # 나가는 주: 바로 왼쪽 열차
                else: no = cn_.get(r['col']) or next((cn_[j] for j in sorted(cn_) if j > r['col']), None)   # 들어오는 주: 바로 오른쪽 열차
                nm = r['name']
                ok = (lambda X: self.is_ktx(X) and nm.replace('고속선', '고속철도') in X.title.text()) if nm.endswith('고속선') else (lambda X: X.line == nm)
                ps = sorted(p for p, X in where.get(no, []) if ok(X) and X is not T)
                # 그 노선 표에 없으면: 다른 표에 실린 같은 열차(홍성 순환 열차 등), 그것도 없으면 이 열차로 나뉘고 합치는 어버이 열차(병결)의 쪽
                if not ps: ps = sorted(p for p, X in where.get(no, []) if X is not T)
                if not ps: ps = sorted(par.get(no, []))
                fol = [ps[0] + first] if ps else []
            else:
                fol = []
                for n in r['nums']:
                    ps = sorted(p for p, X in where.get(n, []) if X is not T)
                    if ps: fol.append(ps[0] + first)
                fol = list(dict.fromkeys(fol))          # 두 열차가 같은 쪽에 실렸으면 한 번만
            out[mk] = (r'\kern%.3fbp ' % (0.2 * 0.76 * r['size'] * self.fs)).join(badge(f, r['size'], r['color']) for f in fol)
            if not fol and r.get('host'): out[mk] = r['host']          # 가리킬 쪽이 없으면 본디의 ║ 그대로
        return [re.sub(r'\\TTREF\{\d+\}', lambda m: out.get(m.group(0), ''), b) for b in body]

    def note_runs(self, T):
        """경유 등 세로 주와 바로 앞뒤 한 칸(║) 사이의 구획선은 긋지 않는다 → {(위 칸 id, 아래 칸 id)}"""
        if getattr(T, '_nrun', None) is not None: return T._nrun
        out = set()
        isv = lambda c: c.rs > 1 and any(it[0] == 'obj' and len(it) > 5 for ln in (c.lines or []) for it in ln)
        for c in T.cells:
            if T.kind[c.c][0] != 'T' or not (T.hEnd <= c.r < T.fStart) or not isv(c): continue
            up = T.occ.get((c.r - 1, c.c)) if c.r - 1 >= T.hEnd else None
            dn = T.occ.get((c.r + c.rs, c.c)) if c.r + c.rs < T.fStart else None
            if up is not None and not isinstance(up, Ghost) and up.node.text().strip() == '║': out.add((id(up), id(c)))
            if dn is not None and not isinstance(dn, Ghost) and dn.node.text().strip() == '║': out.add((id(c), id(dn)))
        T._nrun = out
        return out

    def pdf_ops(self, rects):
        ops, extra, dots = [], [], {}
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
            elif r[0] == 'dot':                                # 둥근 점: 길이 0 인 둥근 끝 선
                dots.setdefault(r[3], []).append('%.2f %.2f m %.2f %.2f l' % (r[1] - 0.01, H - r[2], r[1] + 0.01, H - r[2]))      # 길이 0 이면 그리지 않는 보기 프로그램이 있어 아주 짧게
            elif r[0] in ('line', 'fill', 'closed'):          # 꺾은선(굵기) / 칠한 다각형 / 속 빈 다각형(굵기)
                pts = ' '.join('%.3f %.3f %s' % (x, H - y, 'm' if i == 0 else 'l') for i, (x, y) in enumerate(r[1]))
                if r[0] == 'line': extra.append('q %.3f w 0 J 0 j 0 G %s S Q' % (r[2], pts))
                elif r[0] == 'closed': extra.append('q %.3f w 0 J 0 j 0 G 1 g %s h b Q' % (r[2], pts))
                else: extra.append('q 0 g %s h f Q' % pts)
        for d, ps in dots.items(): extra.append('q %.3f w 1 J 0 G %s S Q' % (d, ' '.join(ps)))
        return '0 g ' + ' '.join(ops) + ' f ' + ' '.join(extra)

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
    # ── 앞 펼침면: 노선도와 색인 ──
    def line_pages(self, first):
        """노선 표지별 실린 쪽 [(이름, 첫 쪽, 끝 쪽, 열쇠)] (처음 나오는 차례)"""
        out = collections.OrderedDict()
        for pi, pg in enumerate(self.pages):
            for pc in pg['pieces']:
                k = self.line_key(pc['T'])
                nm = ('KTX ' + k[1]) if k[0] == 'KTX' else k[1]
                if nm not in out: out[nm] = [pi + first, pi + first, pc['T']]
                out[nm][1] = pi + first
        return out

    def map_key_page(self, key, first):
        """map.json 의 노선 열쇠 → 그 노선 표가 처음 실린 쪽"""
        ktx = key.startswith('KTX:')
        nm = key[4:] if ktx else key
        for pi, pg in enumerate(self.pages):
            for pc in pg['pieces']:
                T = pc['T']
                if ktx and self.is_ktx(T) and (nm in T.title.text() or T.line == nm): return pi + first
                if not ktx and not self.is_ktx(T) and T.line == nm: return pi + first
        return None

    def front_page(self, k, x0, first):
        fs = self.fs
        tex, ops = [], []
        H = self.H
        y0 = self.mt
        W, Hh = self.cw, self.ch
        fm = self.cfg.get('frontMap')                   # 없으면 노선도 없이 색인(앞쪽)·범례(뒤쪽)
        if k == 0 and fm:
            mp = json.load(open(os.path.join(self.base, fm), encoding='utf-8'))
            st = mp['st']
            lats = [v[0] for v in st.values()]; lons = [v[1] for v in st.values()]
            asp = 1.0 / math.cos(math.radians(36.3))
            top_ = 22.0
            sc = min((W - 70) / (max(lons) - min(lons)), (Hh - top_ - 20) / ((max(lats) - min(lats)) * asp))
            ox = x0 + (W - (max(lons) - min(lons)) * sc) / 2
            oy = y0 + top_ + (Hh - top_ - (max(lats) - min(lats)) * asp * sc) / 2
            def P(n):
                la, lo = st[n]
                return ox + (lo - min(lons)) * sc, oy + (max(lats) - la) * asp * sc
            tex.append(self.put_box(x0, y0, W, 14, self.inl.run('노선도', Ctx('GB', 14 / fs)), 'l', 't'))
            tex.append(self.put_box(x0, y0 + 2, W, 12, self.inl.run('굵은 파란 줄은 고속철도·KTX 노선, 네모 안 숫자는 그 표의 첫 쪽', Ctx('M', 0.85)), 'r', 'b'))
            def stroke(pts, w, rgb, dash=None):
                c_ = ' '.join('%.3f' % v for v in rgb)
                d_ = ('[%s] 0 d ' % ' '.join('%.2f' % v for v in dash)) if dash else '[] 0 d '
                path = ' '.join(('%.3f %.3f %s' % (x, H - y, 'm' if i == 0 else 'l')) for i, (x, y) in enumerate(pts))
                ops.append('q %.2f w 1 J 1 j %s RG %s%s S Q' % (w, c_, d_, path))
            blue = (0.04, 0.37, 0.88)
            for ln in mp['lines']:
                if ln.get('hsr'): stroke([P(n) for n in ln['path']], 1.8, blue)
            for ln in mp['lines']:
                if not ln.get('hsr'): stroke([P(n) for n in ln['path']], 1.1, (0.1, 0.1, 0.1), [2.0, 1.2] if ln.get('dash') else None)
            # 역: 흰 동그라미, 이름은 바깥쪽에
            kq = 0.5523
            for n in mp['names']:
                x, y = P(n); r = 1.7
                circ = '%.3f %.3f m ' % (x + r, H - y)
                for a, b_ in ((0, 1), (1, 0), (0, -1), (-1, 0)):
                    pass
                Y = H - y
                circ = ('%.3f %.3f m %.3f %.3f %.3f %.3f %.3f %.3f c %.3f %.3f %.3f %.3f %.3f %.3f c %.3f %.3f %.3f %.3f %.3f %.3f c %.3f %.3f %.3f %.3f %.3f %.3f c' %
                        (x + r, Y, x + r, Y + kq * r, x + kq * r, Y + r, x, Y + r, x - kq * r, Y + r, x - r, Y + kq * r, x - r, Y,
                         x - r, Y - kq * r, x - kq * r, Y - r, x, Y - r, x + kq * r, Y - r, x + r, Y - kq * r, x + r, Y))
                ops.append('q 0.6 w 1 g 0 G %s b Q' % circ)
                sd = mp.get('nameSide', {}).get(n) or ('l' if st[n][1] > 128.95 else 'r')
                dy = -4 if 'u' in sd else 4 if 'd' in sd else 0
                lab = self.inl.run(n, Ctx('M', 0.95))
                if sd.startswith('l'): tex.append(self.put_box(x - 52.5, y - 4 + dy, 50, 8, lab, 'r', 'm'))
                else: tex.append(self.put_box(x + 2.8, y - 4 + dy, 50, 8, lab, 'l', 'm'))
            # 노선 이름표: 이름 + 첫 쪽
            for ln in mp['lines']:
                if 'label' not in ln: continue
                at, dr = ln['label']
                x, y = P(at)
                nm = ln['key'][4:] if ln['key'].startswith('KTX:') else ln['key']
                pg_ = self.map_key_page(ln['key'], first)
                c_ = Ctx('GB', 1.05, '0A5FE0' if ln.get('hsr') else None)
                body_ = self.inl.run(nm, c_) + ((r'\kern%.3fbp ' % (0.25 * fs)) + self.page_badge(pg_, 1.05, '0A5FE0' if ln.get('hsr') else None) if pg_ else '')
                bw = 80
                if dr == 'r': tex.append(self.put_box(x + 10, y - 5, bw, 10, body_, 'l', 'm'))
                elif dr == 'l': tex.append(self.put_box(x - 10 - bw, y - 5, bw, 10, body_, 'r', 'm'))
                elif dr == 't': tex.append(self.put_box(x - bw / 2, y - 16, bw, 10, body_, 'c', 'm'))
                else: tex.append(self.put_box(x - bw / 2, y + 6, bw, 10, body_, 'c', 'm'))
        else:
            # 앞 펼침: 왼쪽 면 범례, 오른쪽 면 목차. 먹 한 색(KTX 만 표와 같은 파랑), 행 높이(R)의 눈금에, 갈래 머리 밑에 중간 굵기 선
            recto = (first + k) % 2 == 1
            tex += self.page_side_title(recto, [('', '범례' if k == 0 else '목차')])
            R = self.R
            wd = lambda t: self.inl.wc.get(t, 1.0) * fs
            rects = []
            gut = 2 * fs                                   # 단 사이
            colw = (W - gut) / 2
            hh, ih = 2 * R, 1.5 * R                        # 갈래 머리 행, 항목 행
            def leader(a_, b_, yl):
                if b_ - a_ > fs: ops.append('q 0.3 w 0 G [0.6 1.6] 0 d %.3f %.3f m %.3f %.3f l S Q' % (a_, H - yl, b_, H - yl))
            def head(xx, yy, name, pg=None):
                nt = self.inl.run(name, Ctx('GB', 1.1))
                tex.append(self.put_box(xx, yy, colw, hh, nt, 'l', 'm'))
                if pg:
                    pt = self.inl.run(pg, Ctx('M', 1.1))
                    tex.append(self.put_box(xx, yy, colw, hh, pt, 'r', 'm'))
                    leader(xx + wd(nt) + 0.5 * fs, xx + colw - wd(pt) - 0.5 * fs, yy + hh / 2 + 0.45 * fs)
                rects.append(('h', xx, xx + colw, yy + hh, 2))
                return yy + hh
            rng_ = lambda a, b: ('%d' % a) if a == b else ('%d∼%d' % (a, b))
            if k == 0:
                lg = self.cfg.get('legend', [])
                groups, flat = [], []
                for head_, body_ in lg:              # 한 줄에 여럿(　로 가름)이면 하나씩: 표지와 이름
                    if head_ or not groups: groups.append([head_, []])
                    for it in [x.strip() for x in body_.split('　') if x.strip()]:
                        m_ = re.match(r'^(B?S\{[^}]*\})\s+(.*)$', it)
                        if m_: groups[-1][1].append((len(flat), m_.group(2).replace('`', ''))); flat.append(m_.group(1))
                        else: groups[-1][1].append((None, it))
                html = run_module('title "x"\n\n[stations]\n가\n\n[notes]\n' + '\n'.join(flat or ['.']), os.path.join(HERE, 'src', 'Timetable.lua'), os.path.join(HERE, 'build'))
                nd = parse_html(html).find(lambda n: 'jtt-notes' in n.cls)
                rows_ = [k_ for k_ in nd.kids if isinstance(k_, Node)] if nd is not None else []
                bw_ = 4.2 * fs                             # 표지 칸 폭: 이름이 한 줄로 서게
                ys_ = [y0, y0]
                half = (len(groups) + 1) // 2
                for g_, (head_, items) in enumerate(groups):
                    c_i = 0 if g_ < half else 1
                    xx = x0 + c_i * (colw + gut)
                    yy = head(xx, ys_[c_i] + (R if ys_[c_i] > y0 else 0), head_)
                    yy += 0.5 * R
                    for n_, name in items:
                        if n_ is None:
                            tex.append(self.put_box(xx, yy, colw, ih, self.inl.run(name, Ctx('M', 1.0)), 'l', 'm'))
                        else:
                            ln_ = self.inl.lines(rows_[n_], Ctx('M', 1.0)) if n_ < len(rows_) else []
                            if ln_: tex.append(self.put_box(xx, yy, bw_, ih, self.inl.flat(ln_[0]), 'l', 'm'))
                            tex.append(self.put_box(xx + bw_, yy, colw - bw_, ih, self.inl.run(name, Ctx('M', 1.0)), 'l', 'm'))
                        yy += ih
                    ys_[c_i] = yy
            else:
                lp = self.line_pages(first)
                bk_ = [i for i, pg in enumerate(self.pages) if 'back' in pg and self.back[pg['back']]['cols']]
                hsr = [(nm, a, b, T) for nm, (a, b, T) in lp.items() if nm.endswith('고속철도') or nm.startswith('KTX ')]
                tour = [(nm, a, b, T) for nm, (a, b, T) in lp.items() if nm == '관광열차']
                gen_ = [(nm, a, b, T) for nm, (a, b, T) in lp.items() if (nm, a, b, T) not in hsr + tour]
                span = lambda xs: rng_(min(x[1] for x in xs), max(x[2] for x in xs))
                cols_ = [[('범례', rng_(first, first), []), ('노선별 시각표', span(gen_), gen_)],
                         [('고속철도', span(hsr), hsr)] + ([('관광열차', span(tour), [])] if tour else [])
                         + ([('역명 색인', rng_(bk_[0] + first, bk_[-1] + first), [])] if bk_ else [])]
                for c_i, secs in enumerate(cols_):
                    xx = x0 + c_i * (colw + gut); yy = y0
                    for s_i, (nm, pg, items) in enumerate(secs):
                        if s_i: yy += R
                        yy = head(xx, yy, nm, pg)
                        if items: yy += 0.5 * R
                        for inm, ia, ib, T in items:
                            kt = T is not None and self.is_ktx(T)
                            it = self.inl.run(inm, Ctx('M', 1.0, '0A5FE0' if kt else None)); ip = self.inl.run(rng_(ia, ib), Ctx('M', 1.0))
                            tex.append(self.put_box(xx, yy, colw, ih, it, 'l', 'm'))
                            tex.append(self.put_box(xx, yy, colw, ih, ip, 'r', 'm'))
                            leader(xx + wd(it) + 0.5 * fs, xx + colw - wd(ip) - 0.5 * fs, yy + ih / 2 + 0.4 * fs)
                            yy += ih
            if rects: ops.append(self.pdf_ops(rects))
        return tex, ' '.join(ops)

    def page_side_title(self, recto, lines, dirs=None, nos=None):
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
        nos = nos or {}
        def nmark(key):
            return [('(%d)' % nos[key], cd)] if key in nos else []
        # KTX 표의 노선은 「KTX 경부선·호남선」으로 묶는다. 쪽에 한 방향만 실렸으면 노선 이름 뒤에 그 방향을
        segs_all = []
        ktx = [(k, ln) for k, ln in lines if k == 'KTX']
        if ktx:
            sg = [('KTX ', c)]
            for i, key in enumerate(ktx):
                if i: sg.append(('·', c))
                sg += [(key[1], c)] + nmark(key) + dmark(key)
            segs_all.append(sg)
        for key in [x for x in lines if x[0] != 'KTX']:
            segs_all.append([(key[1], c)] + nmark(key) + dmark(key))
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
                    if ch.isdigit():          # 숫자(부번): 가로로 세워서
                        j = i
                        while j < len(ln) and ln[j].isdigit(): j += 1
                        items.append(r'\hbox to %.3fbp{\hss\rule[%.3fbp]{0pt}{%.3fbp}%s\hss}' % (1.2 * em, -0.12 * e2, e2, self.inl.run(ln[i:j], cc, True)))
                        i = j; continue
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
        rank = lambda t: 0 if t.startswith(('차종', '등급')) else 1 if '운행' in t else 3 if t.startswith('→') else 2   # 첫 줄에 차종·운행일, 같은 구간·환승은 맨 뒤
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
            # 「…는 ○○ 표에」: 그 표가 실린 쪽 번호를 네모 표지로 덧붙인다
            def line_page(b):
                ps = [p for p, X in getattr(self, '_tpages', []) if X.line == b and not self.is_ktx(X)]
                return min(ps) + self.cfg.get('firstFolio', 2) if ps else None
            def with_badges(text):
                # 「환승 김천 경북선, …」「갑∼을 간은 호남선·전라선 표도 참조」: 노선 이름마다 그 노선 표의 첫 쪽 번호
                out, pos = [], 0
                for m_ in re.finditer(r'[가-힣]+선', text):
                    nm = m_.group(0)
                    pg_ = line_page(nm)
                    if pg_ is None: continue
                    out.append(self.inl.run(text[pos:m_.end()], Ctx('M', sz)))
                    out.append(r'\kern%.3fbp ' % (0.2 * sz * fs) + self.page_badge(pg_, sz / 0.76 * 0.9, None, sz))
                    pos = m_.end()
                out.append(self.inl.run(text[pos:], Ctx('M', sz)) if text[pos:] else '')
                return ''.join(out)
            for i_, d in enumerate(legend):
                t_ = re.sub(r'\s+', ' ', d.text()).strip()
                if t_.startswith('→') and ':' in t_:         # 「갑∼을: 노선」 같은 구간·환승: 역은 굵은 고딕, 노선마다 쪽 번호
                    a_, b_ = t_[1:].split(':', 1)
                    parts[i_] = self.inl.run(a_ + ':', Ctx('GB', sz)) + r'\kern%.3fbp ' % (0.25 * sz * fs) + with_badges(b_.strip()); continue
                if t_.startswith('환승 ') or t_.endswith('표도 참조'):
                    parts[i_] = with_badges(t_); continue
                m = re.search(r'.*는 (.+?) 표에\s*$', re.sub(r'\s+', ' ', d.text()))
                if not m: continue
                ps = [p for p, X in getattr(self, '_tpages', []) if m.group(1) in X.title.text()]
                if ps: parts[i_] += r'\kern%.3fbp ' % (0.3 * sz * fs) + self.page_badge(min(ps) + self.cfg.get('firstFolio', 2), sz / 0.76 * 0.9, None, sz)
            fw_ = (self.inl.wc.get(fo, 2.0)) * fs
            gap = 3 * MM
            W = self.cw - fw_ - gap
            # 세 줄까지: 넘치면 같은 구간·환승 안내를 뒤에서부터 뺀다
            def est(d):
                t = re.sub(r'\s+', ' ', d.text()).strip().lstrip('→')
                return (len(t) * 1.0 + 2.0 * len(re.findall(r'[가-힣]+선', t)) + 1.2) * sz * fs
            def nlines(ws):
                n, cur_ = 1, 0.0
                for w_ in ws:
                    if cur_ and cur_ + w_ > W: n += 1; cur_ = 0.0
                    cur_ += w_
                return n
            while len(legend) > 1 and nlines([est(d) for d in legend]) > 3 and re.sub(r'\s+', '', legend[-1].text()).startswith('→'):
                legend = legend[:-1]; parts = parts[:-1]
            # 줄 나누기: 그 밖의 해설(순환·병결 등)을 먼저 한 줄에, 같은 구간·환승 안내(→)는 남은 줄(셋까지)에 폭을 고르게 나눠
            isx = [re.sub(r'\s+', '', d.text()).startswith('→') for d in legend]
            oth = [p for p, x in zip(parts, isx) if not x]
            xs_ = [(p, est(d)) for p, d, x in zip(parts, legend, isx) if x]
            lines_ = []
            if oth: lines_.append(oth)
            if xs_:
                # 같은 구간(갑∼을)은 앞 줄들에 폭을 고르게, 환승(역)은 끝 줄에. 세 줄을 기본으로
                sec = [(p, w) for (p, w), d in zip(xs_, [d for d, x in zip(legend, isx) if x]) if '∼' in d.text()]
                jun = [(p, w) for (p, w), d in zip(xs_, [d for d, x in zip(legend, isx) if x]) if '∼' not in d.text()]
                room = 3 - len(lines_)
                k_ = max(1, min(room - (1 if jun else 0), len(sec)))
                if sec:
                    tgt = sum(w for _, w in sec) / k_
                    cur_, acc, made = [], 0.0, 0
                    for p, w in sec:
                        if cur_ and made < k_ - 1 and acc + w / 2 > tgt:
                            lines_.append(cur_); cur_, acc = [], 0.0; made += 1
                        cur_.append(p); acc += w
                    if cur_: lines_.append(cur_)
                if jun: lines_.append([p for p, _ in jun])
            body = r'\\'.join(r'\hskip 1.2em plus 0.5em '.join(r'\mbox{%s}' % p for p in ln) for ln in lines_)
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
            T.both = 'jtt-both' in wrap.cls          # 상하행을 한 표에 (가운데 역명, 왼쪽 하행·오른쪽 상행)
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
    def line_key(self, T):
        """쪽 바깥 노선 표지의 열쇠: 고속철도 표는 그 이름(경부고속철도), KTX 는 ('KTX', 노선), 그 밖은 ('', 노선)"""
        t = T.title.text() if T.title is not None else ''
        m = re.search(r'([가-힣]+고속철도)', t)
        if m: return ('', m.group(1))
        if not self.is_ktx(T):                      # 노선 안의 다른 이름 표(평택선 등)는 그 이름
            m = re.search(r'(?:(?:하행|상행)\s*|^\s*)([가-힣·・]+선)(?![가-힣])', t)
            if m and m.group(1) != T.line: return ('', m.group(1))
        return ('KTX', T.line) if self.is_ktx(T) else ('', T.line)

    def is_ktx(self, T):
        t = (T.title.text() if T.title is not None else '') + (T.head.text() if T.head is not None else '')
        return 'KTX' in t or '고속철도' in t

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
        return [{'T': Td, 'Tu': Tu, 'kind': 'stackN', 'sides': sides, 'anyStart': True, 'd': (pd_, rd, hd), 'u': (pu_, ru, hu),
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
        # 하행 끝 몇 편은 제 폭만큼(빈 열 없이), 상행은 남은 폭을 앞에서부터 가득 채운다 (나눈 첫째에 빈 열이 남지 않게)
        # 한 쪽에 좌우로 놓는 하행 끝·상행 앞의 행(줄)이 맞지 않으면 하지 않는다 (하행·상행 각각 펼침면으로)
        if [round(x, 2) for x in Td.rowH] != [round(x, 2) for x in Tu.rowH]: return None
        lnrows = lambda T: [r for r in range(T.nrow) if 'jtt-ln' in T.rowcls[r]]      # 구획선 자리
        if lnrows(Td) != lnrows(Tu): return None
        _, Tcd, _ = self.blocks(Td); _, Tcu, _ = self.blocks(Tu)
        capd, capu = self.cap(Td, 'B', True), self.cap(Tu, 'B', True)
        fd, rd = divmod(len(Tcd), capd)
        if fd < 1 or rd == 0: return None
        avail = self.cw + fw - self.fixed_w(Td, 'B') - self.fixed_w(Tu, 'B')     # 두 조각의 열차 열이 나눠 쓸 폭
        best = None
        for sq in (1.0, self.squeeze):               # 열 폭을 좁혀야 쪽이 주는 때만 좁힌다
            k_ = min(len(Tcu), int(avail / (self.P0 * sq) + 1e-6) - rd)
            if k_ < 1 or k_ >= len(Tcu): continue
            pg_ = -(-(len(Tcu) - k_) // capu)
            if best is None or pg_ < best[1]: best = (k_, pg_)
        if best is None: return None
        ku = best[0]
        P = min(self.P0, avail / (rd + ku))
        wd = self.fixed_w(Td, 'B') + rd * P
        wu = self.cw + fw - wd
        rows_d, rows_u = list(range(Td.nrow)), list(range(Tu.nrow))
        def fullp(T, trs_all, capS, rows):
            h = self.piece_h(T, rows, False, bwf)
            return [{'T': T, 'kind': 'single', 'trs': trs_all[i:i + capS], 'rows': rows, 'notes': False, 'sB': capS, 'side': 'B', 'contR': True,
                     'narrow': False, 'nat': self.fixed_w(T, 'B') + len(trs_all[i:i + capS]) * self.P0, 'bw': bwf, 'h': h}
                    for i in range(0, len(trs_all), capS)]
        fulls = [fullp(Td, Tcd[:fd * capd], capd, rows_d), fullp(Tu, Tcu[ku:], capu, rows_u)]
        if any(j['h'] > PH + 0.01 for js in fulls for j in js): return None
        rems = [(Td, Tcd[fd * capd:], rows_d, self.piece_h(Td, rows_d, False, self.band_w(wd))),
                (Tu, Tcu[:ku], rows_u, self.piece_h(Tu, rows_u, False, self.band_w(wu)))]
        if abs(self.headband_h(Td, self.band_w(wd), '열넷째' if self.page_title else None)
               - self.headband_h(Tu, self.band_w(wu), '열넷째' if self.page_title else None)) > 0.01: return None   # 띠 줄 수가 달라 행이 어긋난다
        side = {'T': Td, 'Tu': Tu, 'kind': 'side', 'parts': rems, 'h': max(r[3] for r in rems), 'trs': rems[0][1],
                'rows': rems[0][2], 'notes': False, 'bw': bwh, 'nosplit': True, 'widths': [wd, wu]}
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
                    job['narrow'] = natB < self.cw * 0.62 and not fold      # 좁은 표는 나란히 (고속버스 노선표도)
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
        FP = int(self.cfg.get('frontPages', 0))          # 앞에 비워 두는 쪽 (노선도·색인)
        for i_ in range(FP): page(i_)['front'] = i_
        cur = {'c': FP}
        def top(p): return ys[p] + gap if ys[p] > 0 else 0.0
        def side_of(p): return 'L' if p % 2 == 0 else 'R'
        def put(T, p, trains, rows, y, notes, h, x=0.0, narrow=False, side=None, bw=None):
            pg = page(p)
            side = side or side_of(p)
            pc = {'T': T, 'side': side, 'trains': trains, 'rows': rows, 'y': y, 'x': x, 'h': h, 'notes': notes,
                  'narrow': narrow, 'nat': self.fixed_w(T, side) + len(trains) * self.P0,
                  'hb': self.headband_h(T, bw if bw is not None else self.band_w(self.cw), '열넷째' if self.page_title else None)}
            pg['pieces'].append(pc)
            key = self.line_key(T)
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
                ws_ = job.get('widths') or [half] * len(job['parts'])
                for k_, (T_, trs_, rows_, h_) in enumerate(job['parts']):
                    sd = 'R' if k_ in job.get('contR', ()) and c % 2 == 1 and any(q['T'] is T_ for q in page(c - 1)['pieces']) else 'B'
                    pc_ = put(T_, c, trs_, rows_, y, False, h_, sum(ws_[:k_]) - k_ * fw, True, sd, self.band_w(ws_[k_]) if job.get('widths') else job['bw'])
                    pc_['fixw'] = ws_[k_]
                    if job.get('rowgroup'): pc_['rg'] = True
                ys[c] = y + h
                return True
            if job['kind'] == 'facing':           # 한 쪽짜리 하행·상행: 펼침면 왼쪽에 하행, 오른쪽에 상행
                if c % 2 == 1: return False
                y = max(top(c), top(c + 1))
                (Td_, trd, rd_, hd_), (Tu_, tru, ru_, hu_) = job['parts']
                if y + max(hd_, hu_) > PH + 0.01: return False
                put(Td_, c, trd, rd_, y, False, hd_, 0.0, False, 'B', job['bw'])
                put(Tu_, c + 1, tru, ru_, y, False, hu_, 0.0, False, 'B', job['bw'])
                ys[c] = y + hd_; ys[c + 1] = y + hu_
                for k_, bl_ in enumerate(job.get('below', [])):     # belowFacing: 밑에 다른 노선의 하행(왼쪽)·상행(오른쪽)
                    Y, Yc, ry, hy = bl_
                    put(Y, c + k_, Yc, ry, ys[c + k_] - fw, False, hy, 0.0, False, 'B', job['bw'])
                    ys[c + k_] += hy - fw
                cur['c'] = c + 2
                return True
            if job['kind'] == 'stackN':           # 여러 쪽에 걸쳐 위(하행)·아래(상행) (오른쪽 면에서 시작하면 오·왼·오…)
                N_ = len(job['sides'])
                if c % 2 == 1 and not job.get('anyStart'): return False
                # 오른쪽 면에서 시작하면: 첫 쪽은 홀로 (양쪽 역명·제목 띠), 그다음부터 펼침면 왼·오
                if c % 2 == 1: job = dict(job, sides=['B' if i == 0 else 'L' if i % 2 == 1 else 'R' for i in range(N_)])
                y = max(top(c + i) for i in range(N_))
                if y + h > PH + 0.01: return False
                pd_, rd, hd = job['d']; pu_, ru, hu = job['u']
                if c % 2 == 1:                        # 쪽마다 열차 수를 그 면의 자리에 맞춰 다시 나눈다
                    def resplit(T_, parts_):
                        all_ = [x for p_ in parts_ for x in p_]; out_, ti_ = [], 0
                        for sd_ in job['sides']:
                            k_ = min(self.cap(T_, sd_, True), len(all_) - ti_); out_.append(all_[ti_:ti_ + k_]); ti_ += k_
                        return out_ if ti_ == len(all_) else None
                    pd2, pu2 = resplit(T, pd_), resplit(job['Tu'], pu_)
                    if not pd2 or not pu2: return False
                    pd_, pu_ = pd2, pu2
                for i, sd in enumerate(job['sides']):
                    n_ = max(len(pd_[i]), len(pu_[i]))
                    if pd_[i]: put(T, c + i, pd_[i], rd, y, False, hd, side=sd)['ncol'] = n_
                    if pu_[i]: put(job['Tu'], c + i, pu_[i], ru, y + hd - fw, False, hu, side=sd)['ncol'] = n_
                    ys[c + i] = y + h
                return True
            if job['kind'] == 'stack' and c % 2 == 1 and job.get('anyStart') and job.get('beside'):
                # 오른쪽 면에서 시작: 첫 쪽은 홀로(양쪽 역명), 넘긴 왼쪽 면에 나머지와 그 옆에 다음 노선
                y = max(top(c), top(c + 1))
                if y + h > PH + 0.01: return False
                da, db, rd, hd = job['d']; ua, ub, ru, hu = job['u']
                Tu = job['Tu']
                Ad, Au = da + db, ua + ub
                kB = min(self.cap(T, 'B', True), self.cap(Tu, 'B', True))
                rd_, ru_ = Ad[kB:], Au[kB:]
                if not rd_ and not ru_: return False
                _, ys0, _ = job['beside']
                found = None
                for yb_ in (1, 0):
                    for b_ in range(job.get('blank', 0), -1, -1):
                        nL = max(len(rd_), len(ru_)) + b_
                        wL = max(self.fixed_w(T, 'L'), self.fixed_w(Tu, 'L')) + nL * self.P0
                        wY = self.cw + fw - wL
                        ys2 = []
                        for Y, Yc, ry, _h in ys0:
                            if self.fixed_w(Y, 'B') + (len(Yc) + yb_) * self.P0 > wY + 0.01: break
                            ys2.append((Y, Yc, ry, self.piece_h(Y, ry, False, self.band_w(wY))))
                        if len(ys2) == len(ys0) and y + sum(q[3] for q in ys2) - (len(ys2) - 1) * fw <= PH + 0.01:
                            found = (wL, ys2, nL); break
                    if found: break
                if not found: return False
                wL, ys2, nL = found
                n0 = max(len(Ad[:kB]), len(Au[:kB]))
                put(T, c, Ad[:kB], rd, y, False, hd, side='B')['ncol'] = n0
                put(Tu, c, Au[:kB], ru, y + hd - fw, False, hu, side='B')['ncol'] = n0
                for T_, tr_, r_, y_, h_ in ((T, rd_, rd, y, hd), (Tu, ru_, ru, y + hd - fw, hu)):
                    if tr_:
                        pc_ = put(T_, c + 1, tr_, r_, y_, False, h_, side='L'); pc_['fixw'], pc_['ncol'] = wL, nL
                ys[c] = ys[c + 1] = y + h
                yy = y
                for Y, Yc, ry, hy in ys2:
                    put(Y, c + 1, Yc, ry, yy, False, hy, wL - fw, False, 'B', self.band_w(self.cw + fw - wL))
                    yy += hy - fw
                ys[c + 1] = max(ys[c + 1], yy + fw)
                cur['c'] = c + 2
                return True
            if job['kind'] == 'stack':            # 펼침면에서만 (왼쪽 면에서 시작)
                if c % 2 == 1: return False
                y = max(top(c), top(c + 1))
                if y + h > PH + 0.01: return False
                da, db, rd, hd = job['d']; ua, ub, ru, hu = job['u']
                Tu = job['Tu']
                bes = job.get('beside')
                for p_, a_, b_ in ((c, da, ua), (c + 1, db, ub)):
                    n_ = max(len(a_), len(b_))
                    if a_:
                        pc_ = put(T, p_, a_, rd, y, False, hd); pc_['ncol'] = n_
                        if bes and p_ == c + 1: pc_['fixw'], pc_['ncol'] = bes[0], bes[2]
                    if b_:
                        pc_ = put(Tu, p_, b_, ru, y + hd - fw, False, hu); pc_['ncol'] = n_
                        if bes and p_ == c + 1: pc_['fixw'], pc_['ncol'] = bes[0], bes[2]
                ys[c] = ys[c + 1] = y + h
                if bes:                               # 오른쪽 면의 끝 몇 편 옆에 다음 노선을 위아래로
                    wR, ys_ = bes[:2]; yy = y
                    for Y, Yc, ry, hy in ys_:
                        put(Y, c + 1, Yc, ry, yy, False, hy, wR - fw, False, 'B', self.band_w(self.cw + fw - wR))
                        yy += hy - fw
                    ys[c + 1] = max(ys[c + 1], yy + fw)
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
            bes = job.get('beside')
            if bes and c % 2 == 1: return False
            ya, yb = top(c), top(c + 1)
            if c % 2 == 0 and abs(ya - yb) < 10 * MM: ya = yb = max(ya, yb)
            if ya + h <= PH + 0.01 and yb + h <= PH + 0.01:
                put(T, c, trs[:kA], rows, ya, False, h)
                pr_ = put(T, c + 1, trs[kA:], rows, yb, notes, h)
                ys[c] = ya + h; ys[c + 1] = yb + h
                if bes:                               # 오른쪽 면의 끝 몇 편 옆에 다음 노선
                    wR, ys_ = bes[:2]; pr_['fixw'], pr_['ncol'] = wR, bes[2]; yy = yb
                    for q in ys_:
                        if q[0] == 'row':             # 좌우로 한 줄
                            xx = wR - fw
                            for Y, Yc, ry, hy, wy in q[1]:
                                put(Y, c + 1, Yc, ry, yy, False, q[2], xx, False, 'B', self.band_w(wy))
                                xx += wy - fw
                            yy += q[2] - fw; continue
                        Y, Yc, ry, hy = q
                        put(Y, c + 1, Yc, ry, yy, False, hy, wR - fw, False, 'B', self.band_w(self.cw + fw - wR))
                        yy += hy - fw
                if c % 2 == 1: cur['c'] = c + 1
                return True
            return False

        def remeta(pg):
            pg['lines'], pg['dirs'] = [], collections.defaultdict(set)
            for q in pg['pieces']:
                key = self.line_key(q['T'])
                if key not in pg['lines']: pg['lines'].append(key)
                tt = q['T'].title.text() if q['T'].title is not None else ''
                pg['dirs'][key].add('하행' if '하행' in tt else '상행' if '상행' in tt else '')
        def advance(job, c):
            if (job['kind'] in ('stack', 'facing') and not (job.get('anyStart') and job.get('beside'))) or (job['kind'] == 'pair' and job.get('beside') and c % 2 == 1):
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
                if c % 2 == 1 and ys[c] == 0 and not page(c)['pieces']: fill_blank(c)
                cur['c'] = c + 1          # 오른쪽 면에서는 다른 작은 표로 채울 수 있게 한 쪽씩
            elif job['kind'] == 'pair' and c % 2 == 0:
                # 왼쪽 면에 자리가 없고 오른쪽 면이 비었으면 오른쪽 면에서 시작해 넘겨 잇는다
                cur['c'] = c + 1 if (ys[c + 1] == 0 and job['h'] <= PH + 0.01) else c + 2
            else:
                cur['c'] = c + 1

        def fill_blank(c):
            """펼침면을 왼쪽 면에서 시작하느라 통째로 비게 되는 오른쪽 면: 뒤 묶음의 작은 표 한 벌(하행·상행 함께, 한 번에 다 실리는 것)을 앞당겨 채운다"""
            for bunch2 in bunches[cur.get('bi', 0) + 1:]:
                if bunch2 and bunch2[0].line in self.cfg.get('otherModes', []): continue     # 고속버스 노선표는 철도 쪽 빈 면에 끌어오지 않는다
                i = 0
                while i < len(bunch2):
                    unit = [bunch2[i]]
                    while i + len(unit) < len(bunch2) and rkey(bunch2[i + len(unit)]) == rkey(bunch2[i]): unit.append(bunch2[i + len(unit)])
                    i += len(unit)
                    if any(id(T2) in prefilled or placed[id(T2)] for T2 in unit): continue
                    js = [j for T2 in unit for j in self.jobs_of(T2)]
                    if not js or len(js) > 2 or any(j['kind'] not in ('side', 'single') for j in js): continue
                    if sum(j['h'] for j in js) - (len(js) - 1) * fw > PH + 0.01: continue
                    for j in js: try_place(j, c)
                    for T2 in unit: prefilled.add(id(T2))
                    return True
            return False
        prefilled = set()

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
        # hsrLast: 고속철도만 있는 표(경부고속철도·호남고속철도)는 책 끝으로 (노선마다 한 묶음)
        ktx_only = {T.line for T in tables} - {T.line for T in tables if not self.is_ktx(T)}     # KTX밖에 없는 노선 (강릉선·중부내륙선)
        hsr = lambda T: self.cfg.get('hsrLast', False) and self.is_ktx(T) and ('고속철도' in T.title.text() or T.line in ktx_only)
        for T in tables:
            if self.cfg.get('ktxFirst', False) and self.is_ktx(T): continue
            if hsr(T): continue
            if bunches and bunches[-1] and not self.is_ktx(bunches[-1][0]) and bunches[-1][0].line == T.line:
                bunches[-1].append(T)
            else:
                bunches.append([T])
        last = self.cfg.get('lastLines', [])           # 책 맨 끝에 둘 노선 (관광열차)
        if last:
            tail_ = [b for b in bunches if b and b[0].line in last]
            bunches = [b for b in bunches if not (b and b[0].line in last)]
        bo = self.cfg.get('backOrder', [])          # 책 끝 묶음의 차례 (쪽 짝을 맞추려고 바꿀 때)
        for ln in sorted(dict.fromkeys(T.line for T in tables if hsr(T)), key=lambda x: bo.index(x) if x in bo else len(bo)):
            bunches.append([T for T in tables if hsr(T) and T.line == ln])
        if last: bunches += tail_
        oth_ = [b for b in bunches if b and b[0].line in self.cfg.get('otherModes', [])]       # 철도 밖(고속버스)은 맨 끝에
        bunches = [b for b in bunches if not (b and b[0].line in self.cfg.get('otherModes', []))] + oth_
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
        # 한 쪽에 몇 편이 넘치는 표: 역명 칸을 글자만큼으로 좁혀 한 쪽에 들면 그렇게 (역 이름이 짧은 노선)
        for T in tables:
            T.band_left = False; T.fold = False
            if self.is_ktx(T): continue
            n_ = len(self.blocks(T)[1])
            if n_ <= self.cap(T, 'B', True): continue
            old_ = list(T.colW)
            self.narrow_st(T)
            if n_ > self.cap(T, 'B', True): T.colW = old_
        for T in tables:
            T.band_left = False; T.fold = False; T.stack_with = None; T.stacked = False; T.side_with = None; T.custom_jobs = None; T.pull_first = False
            if T.line in self.cfg.get('foldLines', []):      # 펼침면으로 넘기지 않는다: 한 쪽 폭에 안 들면 띠로 접어 아래로, 들면 좁은 표끼리 나란히 (고속버스 노선표)
                if len(self.blocks(T)[1]) > self.cap(T, 'B', True):
                    T.band_left = T.head is not None; T.fold = True
                    continue
                band_pos(T); continue
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
            # 재래선의 한 쪽짜리 하행·상행(둘 다 반 쪽보다 높아 한 쪽에 함께 들지 않는 것): 펼침면 왼쪽·오른쪽에 마주 보게
            if self.cfg.get('facing', True) and len(ts) == 2 and not any(self.is_ktx(T) for T in ts):
                dn = [T for T in ts if '하행' in T.title.text()]
                up = [T for T in ts if '상행' in T.title.text()]
                if len(dn) == 1 and len(up) == 1:
                    jd, ju = self.jobs_of(dn[0]), self.jobs_of(up[0])
                    if len(jd) == 1 and len(ju) == 1 and jd[0]['kind'] == ju[0]['kind'] == 'single' \
                            and jd[0]['h'] + ju[0]['h'] - fw > PH + 0.01:
                        dn[0].custom_jobs = [{'T': dn[0], 'kind': 'facing', 'parts': [(dn[0], jd[0]['trs'], jd[0]['rows'], jd[0]['h']),
                                              (up[0], ju[0]['trs'], ju[0]['rows'], ju[0]['h'])], 'h': max(jd[0]['h'], ju[0]['h']),
                                              'trs': jd[0]['trs'], 'rows': jd[0]['rows'], 'notes': False, 'bw': jd[0]['bw']}]
                        up[0].stacked = True
                        continue
            # stackPages: 지정한 표는 하행 위·상행 아래로 N 쪽에 걸쳐
            sp = next((x for x in self.cfg.get('stackPages', []) if len(ts) == 2 and all(T.line == x['line'] and x.get('title', '') in T.title.text()
                                                                                       and not (x.get('not') and x['not'] in T.title.text()) for T in ts)), None)
            if sp:
                dn = [T for T in ts if '하행' in T.title.text()]
                up = [T for T in ts if '상행' in T.title.text()]
                if len(dn) == 1 and len(up) == 1:
                    sj = None
                    for N_ in ([sp['pages']] if sp['pages'] != 'auto' else range(2, 12)):    # auto: 드는 가장 적은 쪽 수
                        sj = self.stackn_jobs(dn[0], up[0], N_)
                        if sj: break
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
                    top_ = any(T.line == x['line'] and x.get('title', '') in T.title.text() for x in self.cfg.get('bandTop', []) for T in ts)
                    sj = None
                    if top_:                          # bandTop: 위 띠로 (위아래 단이 들면)
                        for T in ts: T.fold = False; T.band_left = False
                        sj = self.stack_jobs(Td, Tu)
                    if not sj:
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
        # rowGroups: 작은 표 여럿(제목에 이 말이 든 표들의 하행·상행)을 한 단에 같은 폭으로 나란히 (관광열차 등)
        for rg in self.cfg.get('rowGroups', []):
            row = [T for t_ in rg['titles'] for T in tables if T.line == rg['line'] and t_ in T.title.text()]     # 표 차례대로(하행·상행)
            if len(row) < 2: continue
            k_ = len(row)
            # 폭: 제 폭에 비례해 판면 폭을 나눈다 (남는 폭은 역명 칸에)
            nat_ = [self.fixed_w(T, 'B') + len(self.blocks(T)[1]) * self.P0 for T in row]
            tot_ = self.cw + (k_ - 1) * fw
            if sum(nat_) > tot_ + 0.01: continue
            ws_ = [x * tot_ / sum(nat_) for x in nat_]       # 남는 폭은 표마다 빈 열(‥)로
            parts_ = []
            for T, w1 in zip(row, ws_):
                T.fold = False; T.band_left = False
                rr = list(range(T.nrow))
                parts_.append((T, self.blocks(T)[1], rr, self.piece_h(T, rr, False, self.band_w(w1))))
            for T in row: T.custom_jobs = None; T.stack_with = None; T.side_with = None; T.stacked = True
            row[0].stacked = False
            row[0].custom_jobs = [{'T': row[0], 'kind': 'side', 'parts': parts_, 'widths': ws_, 'h': max(q[3] for q in parts_),
                                   'trs': parts_[0][1], 'rows': parts_[0][2], 'notes': False, 'bw': self.band_w(ws_[0]), 'nosplit': True, 'rowgroup': True}]
        # besideRight: 펼침면 짝(하행 위·상행 아래)의 오른쪽 면 끝 몇 편 옆에 다음 노선의 하행·상행을 나란히 (그 노선의 한 쪽을 아낀다)
        for br in self.cfg.get('besideRight', []):
            kx = br.get('ktx', False)            # KTX 표끼리 (KTX밖에 없는 노선)
            nots = br.get('not', [])           # 이 말이 제목에 든 표는 빼고 (순환 표 등)
            pick = lambda ln, d: [T for T in tables if T.line == ln and self.is_ktx(T) == kx and d in T.title.text()
                                  and not any(x in T.title.text() for x in nots)]
            blank = br.get('blank', 0)          # 끝 몇 편 뒤에 남길 빈 열 (표가 거기서 끝남을 보이게)
            if br.get('kind') == 'pair':
                # 방향마다 펼침면 하나: 왼쪽 면 가득 + 오른쪽 면에 끝 몇 편(rest), 그 옆에 다른 노선의 하행·상행을 위아래로
                def sides(ln):                 # 그 노선의 하행·상행 두 표, 또는 상하행을 한 표에 적은 것 하나
                    a_, b_ = pick(ln, '하행'), pick(ln, '상행')
                    if len(a_) == 1 and len(b_) == 1: return [a_[0], b_[0]]
                    bb = [T for T in tables if T.line == ln and getattr(T, 'both', False) and self.is_ktx(T) == kx
                          and not any(x in T.title.text() for x in nots)]
                    return bb if len(bb) == 1 else None
                if not all(len(pick(br['line'], d)) == 1 for d in ('하행', '상행')) or not sides(br['down']) or not sides(br['up']): continue
                Td, Tu = pick(br['line'], '하행')[0], pick(br['line'], '상행')[0]
                bwf = self.band_w(self.cw)
                js_, ys_all = [], []
                for T, ln, rest in ((Td, br['down'], br.get('rest', [None, None])[0]), (Tu, br['up'], br.get('rest', [None, None])[1])):
                    T.fold = False; T.band_left = False
                    _, Tc, _ = self.blocks(T)
                    kL = len(Tc) - rest if rest else min(len(Tc) - 1, self.cap(T, 'L'))
                    rows = list(range(T.nrow)); h = self.piece_h(T, rows, False, bwf)
                    if kL < 1 or kL > self.cap(T, 'L', True) or h > PH + 0.01: break
                    nR = len(Tc) - kL + blank
                    wR = self.fixed_w(T, 'R') + nR * self.P0
                    wY = self.cw + fw - wR
                    ys_ = []
                    sd_ = sides(ln)
                    for Y in sd_:
                        Y.fold = False; Y.band_left = False
                        _, Yc, _ = self.blocks(Y)
                        if self.fixed_w(Y, 'B') + len(Yc) * self.P0 > wY + 0.01: break
                        ry = list(range(Y.nrow))
                        ys_.append((Y, Yc, ry, self.piece_h(Y, ry, False, self.band_w(wY))))
                    if len(ys_) != len(sd_): break
                    # upRow/downRow: 그 밑에 같은 노선의 다른 표(순환 등) 하행·상행을 좌우로 한 줄
                    kw = br.get('upRow' if T is Tu else 'downRow')
                    if kw:
                        rr = [[X for X in tables if X.line == ln and kw in X.title.text() and d in X.title.text()] for d in ('하행', '상행')]
                        if not all(len(x) == 1 for x in rr):
                            rb = [X for X in tables if X.line == ln and kw in X.title.text() and getattr(X, 'both', False)]   # 상하행을 한 표에
                            if len(rb) != 1: break
                            rr = [rb]
                        parts_ = []
                        # 좌우로 나란한 두 표는 역명 칸 폭을 같게 (넓은 쪽에)
                        for j_ in range(max(len(x[0].colW) for x in rr)):
                            ws_ = [x[0].colW[j_] for x in rr if j_ < len(x[0].colW) and x[0].kind[j_][1] == 'st' and x[0].kind[j_][0] in ('L', 'R')]
                            if len(ws_) == len(rr):
                                for x in rr: x[0].colW[j_] = max(ws_)
                        for (X,) in rr:
                            X.fold = False; X.band_left = False
                            _, Xc, _ = self.blocks(X)
                            wx = self.fixed_w(X, 'B') + len(Xc) * self.P0
                            rx = list(range(X.nrow))
                            parts_.append((X, Xc, rx, self.piece_h(X, rx, False, self.band_w(wx)), wx))
                        if sum(q[4] for q in parts_) - fw > wY + 0.01: break
                        ys_.append(('row', parts_, max(q[3] for q in parts_)))
                    hsum = sum(q[2] if q[0] == 'row' else q[3] for q in ys_) - (len(ys_) - 1) * fw
                    if hsum > PH + 0.01: break
                    js_.append({'T': T, 'kind': 'pair', 'trs': Tc, 'kA': kL, 'rows': rows, 'h': h, 'notes': False, 'bw': bwf,
                                'beside': (wR, ys_, nR)})
                    ys_all += [x[0] for q in ys_ for x in (q[1] if q[0] == 'row' else [q])]
                if len(js_) != 2: continue
                for T in [Td, Tu] + ys_all: T.custom_jobs = None; T.stack_with = None; T.side_with = None; T.stacked = False
                Td.custom_jobs, Tu.custom_jobs = [js_[0]], [js_[1]]
                for Y in ys_all: Y.stacked = True
                continue
            if not all(len(pick(ln, d)) == 1 for ln in (br['line'], br['with']) for d in ('하행', '상행')): continue
            Td, Tu, Yd, Yu = pick(br['line'], '하행')[0], pick(br['line'], '상행')[0], pick(br['with'], '하행')[0], pick(br['with'], '상행')[0]
            for T in (Td, Tu, Yd, Yu): T.fold = False; T.band_left = False
            sj = self.stack_jobs(Td, Tu)
            if not sj or len(sj) != 1 or sj[0]['kind'] != 'stack': continue
            da, db, rd, hd = sj[0]['d']; ua, ub, ru, hu = sj[0]['u']
            ys_ = []
            # 빈 열은 들 만큼 (모자라면 줄인다). 옆 표에도 빈 열이 하나는 남게(끝을 보이게) 먼저 해 보고, 안 되면 그것 없이
            for yb_ in (1, 0):
                for b_ in range(blank, -1, -1):
                    nR = max(len(db), len(ub)) + b_
                    wR = max(self.fixed_w(Td, 'R'), self.fixed_w(Tu, 'R')) + nR * self.P0
                    wY = self.cw + fw - wR
                    ys_ = []
                    for Y in (Yd, Yu):
                        _, Yc, _ = self.blocks(Y)
                        if self.fixed_w(Y, 'B') + (len(Yc) + yb_) * self.P0 > wY + 0.01: break
                        ry = list(range(Y.nrow))
                        ys_.append((Y, Yc, ry, self.piece_h(Y, ry, False, self.band_w(wY))))
                    if len(ys_) == 2: break
                if len(ys_) == 2: break
            if len(ys_) != 2 or ys_[0][3] + ys_[1][3] - fw > PH + 0.01: continue
            for T in (Td, Tu, Yd, Yu): T.custom_jobs = None; T.stack_with = None; T.side_with = None; T.stacked = False
            Td.custom_jobs = [dict(sj[0], beside=(wR, ys_, nR), anyStart=br.get('anyStart', False), blank=blank)]
            Tu.stacked = Yd.stacked = Yu.stacked = True
        # belowFacing: 마주 보는 하행·상행(facing) 밑에 다른 노선의 하행·상행을 (왼쪽 면 밑에 하행, 오른쪽 면 밑에 상행)
        for bf in self.cfg.get('belowFacing', []):
            pick = lambda ln, d: [T for T in tables if T.line == ln and not self.is_ktx(T) and d in T.title.text()]
            if not all(len(pick(ln, d)) == 1 for ln in (bf['line'], bf['with']) for d in ('하행', '상행')): continue
            Td, Yd, Yu = pick(bf['line'], '하행')[0], pick(bf['with'], '하행')[0], pick(bf['with'], '상행')[0]
            fj = (Td.custom_jobs or [None])[0]
            if not fj or fj['kind'] != 'facing': continue
            bwf = self.band_w(self.cw)
            bl_, ok = [], True
            for (T_, trs_, rows_, h_), Y in zip(fj['parts'], (Yd, Yu)):
                Y.fold = False; Y.band_left = False
                _, Yc, _ = self.blocks(Y)
                ry = list(range(Y.nrow)); hy = self.piece_h(Y, ry, False, bwf)
                if len(Yc) > self.cap(Y, 'B', True) or h_ + hy - fw > PH + 0.01: ok = False; break
                bl_.append((Y, Yc, ry, hy))
            if not ok: continue
            for Y in (Yd, Yu): Y.custom_jobs = None; Y.stack_with = None; Y.side_with = None; Y.stacked = True
            Td.custom_jobs = [dict(fj, below=bl_)]
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
        OTH_ = self.cfg.get('otherModes', [])
        for bi, bunch in enumerate(bunches):
            cur['bi'] = bi
            if bunch and bunch[0].line in OTH_ and not (bi and bunches[bi - 1] and bunches[bi - 1][0].line in OTH_):
                c = cur['c']                            # 고속버스 노선표는 새 쪽에서
                while page(c)['pieces']: c += 1
                cur['c'] = c
            pend = [collections.deque([] if id(T) in prefilled else self.jobs_of(T)) for T in bunch]
            init = [len(q) for q in pend]
            whole = [n <= 1 for n in init]          # 한 번에 다 실리는 표만 당겨 올 수 있다 (짝에 묶여 일감이 없는 표 포함)
            def gkey(T):                                # 고속버스 노선표: 같은 노선의 하행·상행 띠들(이름의 두 끝이 같은 것)은 한 쪽에 잇달아
                tt = (T.title.text() if T.title is not None else '').replace('︱', '―').replace('︵', '（').replace('︶', '）')     # 세로쓰기 글자를 되돌려
                tt = re.sub(r'（[^）]*）', '', tt)
                return frozenset(x.strip() for x in re.split('[―・]', tt)) if '―' in tt else None     # 하행·상행 이름은 끝 정류장들이 같다 (차례만 거꾸로)
            while any(pend):
                pi = next(i for i, q in enumerate(pend) if q)
                job = pend[pi][0]
                if bunch[pi].line in OTH_ and len(pend[pi]) == init[pi] and (pi == 0 or gkey(bunch[pi - 1]) != gkey(bunch[pi])) and gkey(bunch[pi]):
                    grp = [k for k in range(pi, len(bunch)) if gkey(bunch[k]) == gkey(bunch[pi])]
                    k2 = pi
                    while k2 < len(bunch) and gkey(bunch[k2]) == gkey(bunch[pi]): k2 += 1
                    js_ = [j for k in range(pi, k2) for j in pend[k]]
                    if k2 - pi > 1 and all(j['kind'] == 'single' for j in js_):
                        tot = sum(j['h'] for j in js_) - (len(js_) - 1) * fw
                        if top(cur['c']) > 0 and top(cur['c']) + tot > PH + 0.01 and tot <= PH + 0.01: cur['c'] += 1     # 다음 쪽에서 한꺼번에
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
            alloc, ok_ = {}, {}
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
                alloc[p] = (ts, give); ok_[p] = ok
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
                for ti_, (t, g) in enumerate(zip(ts, give)):
                    bottom = max(q['y'] + q['h'] for q in t)
                    gg = g if g > 0.5 * self.R else 0.0
                    for q in t:
                        q['y'] += shift
                        if ok_[p][ti_]:          # 한 단의 표는 아래 끝을 맞춘다 (남는 자리가 없어도)
                            e = gg + (bottom - (q['y'] - shift + q['h']))
                            if e > 0.01: q['stretch'] = e; q['h'] += e
                    shift += gg
            # 옆에 위아래로 쌓인 표들이 있는 쪽(과 마주 보는 쪽): 세로로 이어진 조각들마다 쪽 맨 아래까지, 남는 자리는 높이에 비례해 나눈다
            def xover(a, b):
                wa, wb = a.get('avail', a['nat']), b.get('avail', b['nat'])
                return a['x'] < b['x'] + wb - 1 and b['x'] < a['x'] + wa - 1
            def stacked_beside(ps):
                return any(xover(a, b) and abs(a['y'] - b['y']) > 0.5 for a in ps for b in ps if a is not b) and \
                    any(not xover(a, b) for a in ps for b in ps if a is not b)
            sp_ = {p for p, pg in enumerate(pages) if stacked_beside(pg['pieces']) and not all(q.get('rg') for q in pg['pieces'])}
            sp_ |= {p + 1 if p % 2 == 0 else p - 1 for p in sp_}
            sp_ = {p for p in sp_ if p < len(pages) and not (pages[p]['pieces'] and all(q.get('rg') for q in pages[p]['pieces']))}
            for p in sp_:
                if p >= len(pages): continue
                ps = pages[p]['pieces']
                for q in ps:
                    q['h'] -= q.get('stretch', 0); q['stretch'] = 0
                done = set()
                for q in sorted(ps, key=lambda q: q['y']):
                    if id(q) in done: continue
                    chain = [q]
                    while True:
                        nx = [r for r in ps if id(r) not in done and r not in chain and r['y'] > chain[-1]['y'] + 0.5 and xover(chain[-1], r)]
                        if not nx: break
                        chain.append(min(nx, key=lambda r: r['y']))
                    for r in chain: done.add(id(r))
                    sib = {id(r): [q2 for q2 in ps if id(q2) not in done and abs(q2['y'] - r['y']) < 0.5 and not xover(q2, r)
                                   and any(xover(q2, r2) for r2 in chain if r2 is not r)] for r in chain}     # 좌우로 한 줄인 짝
                    for v in sib.values():
                        for q2 in v: done.add(id(q2))
                    for r in chain:                       # 좌우로 한 줄인 짝이 더 높으면 그 높이로 (짧은 쪽을 늘린다, 높은 쪽을 자르지 않게)
                        hx = max([r['h']] + [q2['h'] for q2 in sib[id(r)]])
                        if hx > r['h'] + 0.01: r['pre'] = hx - r['h']; r['h'] = hx
                    y_ = chain[0]['y']
                    tot = sum(r['h'] for r in chain) - (len(chain) - 1) * fw
                    slack = PH - (y_ + tot)
                    cs_ = [r for r in chain if can([r])]
                    hsum = sum(r['h'] for r in cs_)
                    for r in chain:
                        e = slack * r['h'] / hsum if (r in cs_ and hsum > 0 and slack > 0) else 0.0
                        r['y'] = y_; r['h'] += e; r['stretch'] = e + r.pop('pre', 0.0)
                        for q2 in sib[id(r)]: q2['y'] = y_; q2['stretch'] = r['h'] - q2['h']; q2['h'] = r['h']
                        y_ += r['h'] - fw
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
        # 철도 밖의 노선(고속버스 노선표)은 항공 뒤로: 철도 → 항공 → 고속버스(노선표 → 터미널별)
        OTHER = self.cfg.get('otherModes', [])
        is_o = lambda pg: pg['pieces'] and all(pc['T'].line in OTHER for pc in pg['pieces'])
        self.pages = [pg for pg in pages if not is_o(pg)]
        self.plan_air()
        self.pages += [pg for pg in pages if is_o(pg)]
        self.plan_bus()
        self.plan_back()

    # ── 항공 (JTB 국내선 꼴): 공항 쌍마다 한 덩이 — 머리(번호·쌍·운임), 왼쪽 가는 편·오른쪽 오는 편, 밑에 ※ 주. 두 단으로 흘려 짠다 ──
    def plan_air(self):
        """항공: 설정 air 가 파일 하나면 한 장, [[파일, 장 이름], …] 이면 장마다 따로 (정기편 다이아 / 그 달의 임시편·연결편). 덩이 번호는 장을 넘어 잇는다"""
        self.air, self.air_secs = [], []
        f = self.cfg.get('air')
        if not f: return
        secs = [[f, '항공']] if isinstance(f, str) else f
        no0 = 0
        wk = [tuple(x) for x in self.cfg.get('airWeekday', [])]        # 요일 칸을 다는 공항 쌍: 한 쪽 폭을 다 써서 (편이 많은 쌍)
        for si, sc in enumerate(secs):
            data = json.load(open(os.path.join(self.base, sc[0]), encoding='utf-8'))
            for P in data['pairs']: P['no'] = no0 + P['no']
            no0 = max([no0] + [P['no'] for P in data['pairs']])
            self.air_secs.append({'title': sc[1]} | ({'sub': sc[2]} if len(sc) > 2 else {}))
            isw = lambda P: (P['a'], P['b']) in wk or (P['b'], P['a']) in wk
            dw = [P for P in data['pairs'] if isw(P)]
            if dw: self.plan_air_one({'pairs': dw}, si, sc[1], wide=True)
            self.plan_air_one({'pairs': [P for P in data['pairs'] if not isw(P)]}, si, sc[1])

    @staticmethod
    def air_marks(lab):
        """운항일 주의 갈래 → 기호: ◇ 요일에만, ▲ 빠지는 날, ● 기한(부터·까지·그날만), ※ 시각이 다른 날"""
        if not lab: return ''
        base = re.sub(r'\([^)]*\)', '', lab).strip()
        out = ''
        b2 = base.replace('매일', '')
        if re.search(r'(?<![0-9])[월화수목금토일](?![0-9])', re.sub(r'\d+월', '', b2)): out += '◇'
        if '제외' in base or '빼고' in base: out += '▲'
        rest = re.sub(r'[^,]*(제외|빼고)', '', base)
        if re.search(r'까지|부터|\d+일', rest): out += '●'
        if '(' in lab: out += '※'
        return out

    def plan_air_one(self, data, si, title, wide=False):
        R, fs = self.R, self.fs
        NC = 1 if wide else 2; gut = 0.0                    # 단 사이도 띄우지 않고 맞붙인다. 요일 칸 쌍은 한 단(쪽 폭)
        cf_ = self.cfg.get('airCodes')                      # 편명 앞 두 자(IATA) → 세 자 항공사 부호(ICAO): 「KAL 1122」
        codes = json.load(open(os.path.join(self.base, cf_), encoding='utf-8')) if cf_ else {}
        self._fno = lambda no: (codes.get(no[:2], ''), no)      # (세 자 항공사 이름, 편명 그대로)
        colw = (self.cw - (NC - 1) * gut) / NC
        TH, SH = 2 * R, R                                   # 머리 행, 칸 이름 행
        pad = 0.5 * fs
        nmk = max([len(self.air_marks(r_[3])) for P in data['pairs'] for L in (P['out'], P['in']) for r_ in L] + [1])
        self._air_mk = (len({ch for P in data['pairs'] for L in (P['out'], P['in']) for r_ in L for ch in self.air_marks(r_[3])}) and 4, 0.55 * fs)   # 기호 자리: ◇ ▲ ● ※ 넷의 정해진 칸
        WM = 1.5 * fs                                       # 주 앞 기호 자리 (기호는 오른쪽에 붙여 매달고, 편명은 늘 같은 자리에서)
        nw = colw / 2 - 2 * pad - WM                        # 주의 글줄 폭: 가는 편의 주는 왼쪽 반, 오는 편의 주는 오른쪽 반
        wd = lambda t: self.inl.wc.get(self.inl.run(t, Ctx('M', 0.85)), len(t)) * fs
        def wrap(text):                                     # 주: 「・」·띄어쓰기에서 (괄호 속은 날 뒤에서만)
            toks = []
            for t_ in re.findall(r'(?:\([^)]*\)|[^・ ])+[・ ]?', text):
                if wd(t_.rstrip()) > nw: toks += re.findall(r'[^・ ]+[・ ]?', t_)     # 한 줄에 안 드는 괄호는 그 속에서도 끊는다
                else: toks.append(t_)
            out, cur = [], ''
            for t_ in toks:
                if cur and wd((cur + t_).rstrip()) > nw: out.append(cur.rstrip()); cur = t_
                else: cur += t_
            out.append(cur.rstrip())
            return out
        seq = []                                            # (덩이, 줄들): r=편 줄, n=주 줄
        for P in data['pairs']:
            items = [('r', k) for k in range(max(len(P['out']), len(P['in'])))]
            def side_notes(L):
                g = collections.OrderedDict()
                for r_ in L:
                    no, lab = r_[0], (r_[5] if wide else r_[3])
                    if lab: g.setdefault(re.sub(r'^\((.*)\)$', r'\1', lab) if lab.count('(') == 1 and lab.startswith('(') else lab, [[], self.air_marks(lab)])[0].append(no)
                return [(mk if k_ == 0 else '') + '\t' + ln for lab, (nos, mk) in g.items() for k_, ln in enumerate(wrap('%s %s' % ('・'.join(nos), lab)))]
            nl, nr = side_notes(P['out']), side_notes(P['in'])
            items += [('n', nl[k] if k < len(nl) else '', nr[k] if k < len(nr) else '') for k in range(max(len(nl), len(nr)))]
            seq.append((P, items))
        def flow(start, cap):
            """seq 를 start=(덩이, 줄)부터 높이 cap 인 단들로 흘린다 → [(단, 그 단의 시작)]"""
            out, col, y = [], [], 0.0
            s0 = start
            pi, i = start
            while pi < len(seq):
                P, items = seq[pi]
                head = TH + (SH if items[i][0] == 'r' else 0)
                room = int((cap - y - head - pad) / R + 1e-6)
                left = len(items) - i
                if room < min(3, left):
                    if not col: return None                 # 한 덩이 머리도 못 들어간다
                    out.append((col, s0)); col, y, s0 = [], 0.0, (pi, i); continue
                k = min(room, left)
                if left - k in (1, 2) and k > 3: k = left - 3
                col.append({'P': P, 'y': y, 'items': items[i:i + k], 'first': i == 0})
                y += head + k * R + pad
                i += k
                if i >= len(items): pi, i = pi + 1, 0
                else: out.append((col, s0)); col, y, s0 = [], 0.0, (pi, i)
            if col: out.append((col, s0))
            return out
        cols = flow((0, 0), self.ch)
        pages = [[c for c, _ in cols[k:k + NC]] for k in range(0, len(cols), NC)]
        # 마지막 쪽: 단의 높이를 고르게 (왼쪽·오른쪽 반반)
        last0 = cols[(len(pages) - 1) * NC][1]
        lo, hi = 4 * R, self.ch
        for _ in range(30):
            mid = (lo + hi) / 2
            f_ = flow(last0, mid)
            if f_ is not None and len(f_) <= NC: hi = mid
            else: lo = mid
        pages[-1] = [c for c, _ in flow(last0, hi)]
        nos_ = [self._fno(r[0])[1] for P in data['pairs'] for L in (P['out'], P['in']) for r in L]
        nw_ = max([self.inl.wc.get(self.inl.run(x, Ctx('M', 1.0)), len(x)) * fs for x in nos_] + [3 * fs])
        g_ = {'title': title, 'nw': nw_, 'geom': (colw, gut, TH, SH, pad), 'NC': NC, 'wide': wide}
        for p in pages:
            self.pages.append({'pieces': [], 'lines': [], 'air': len(self.air), 'airSec': si}); self.air.append((si, p, g_))

    def air_page(self, k, x0, recto):
        fs, H, R = self.fs, self.H, self.R
        si, cols_, sec = self.air[k]
        colw, gut, TH, SH, pad = sec['geom']
        air_nw = sec['nw']
        wide = sec['wide']
        WDN, DWd = '월화수목금토일', 0.95 * fs                 # 요일 칸
        nmk, PM = self._air_mk
        WMn = 1.5 * fs                                      # 주 앞 기호 자리 (plan 의 WM 과 같게)
        def mark_(m):                                       # 주의 기호: 오른쪽에 붙여 매단다 (여럿이면 작게). ▲ 는 글꼴에서 커서 줄인다
            z = {1: 0.8, 2: 0.66}.get(len(m), 0.48)
            return ''.join(self.inl.run(ch, Ctx('M', z * (0.72 if ch == '▲' else 1.0))) for ch in m)
        SLOT = '◇▲●※'
        def marks_at(x_, y_, m):                            # 기호마다 정해진 자리(◇ ▲ ● ※ 차례), 같은 크기로. ▲ 는 글꼴에서 커서 줄여 다른 기호와 맞춘다
            for ch in m:
                tex.append(self.put_box(x_ + SLOT.index(ch) * PM, y_, PM, R, self.inl.run(ch, Ctx('M', 0.6 * (0.82 if ch == '▲' else 1.0))), 'c', 'm'))
        tex, rects, ops = [], [], []
        y0 = self.mt
        hw = colw / 2
        cT, cA, cM, cC = 2.3 * fs, 1.1 * fs, self._air_mk[0] * self._air_mk[1] + 0.2 * fs, (0.0 if self.cfg.get('airlines') else 2.2 * fs)   # 시각 칸, 화살표 칸, 기호(◇▲●※) 칸, 항공사 부호 칸 (항공사 색인이 있으면 편명만)
        room_ = hw - 2 * pad - 2 * cT - cA - cM - cC        # 편 번호에 쓸 폭: 가장 긴 것이 넘치면 가로로 좁힌다
        hsN = min(0.82, (room_ - 0.3 * fs) / air_nw)
        cN = cM + cC + min(room_, air_nw * hsN + 0.3 * fs)
        hmf = lambda t: str(int(t[:2])) + t[2:]
        rgb0 = '0 0 0'
        HS = 0.82                                           # 로마자·숫자(편명·항공사)는 장평을 줄인다
        def seg(text, size):                                # {…}: 다른 시각은 표 글꼴. 주 속 편명도 장평을 줄여
            out_ = []
            for k_, p_ in enumerate(re.split(r'[{}]', text)):
                if not p_: continue
                if k_ % 2: out_.append(self.inl.run(p_, Ctx('DM', size))); continue
                for q_ in re.split(r'([A-Z0-9]*[A-Z][A-Z0-9]*\d+[A-Z]?)', p_):
                    if q_: out_.append(self.inl.run(q_, Ctx('M', size).but(hscale=HS) if re.fullmatch(r'[A-Z0-9]+', q_) else Ctx('M', size)))
            return ''.join(out_)
        yB = y0 + self.ch
        ends = []
        for ci in range(sec['NC']):
            col = cols_[ci] if ci < len(cols_) else []
            xx = x0 + ci * (colw + gut)
            yEnd = y0
            for pc in col:
                P = pc['P']; Y = y0 + pc['y']
                # 머리: 검은 바탕 흰 번호, 공항 쌍, 오른쪽에 일반석 운임
                bt = self.inl.run(str(P['no']), Ctx('GB', 1.0, 'FFFFFF'))
                bw = max(1.8 * fs, self.inl.wc.get(bt, 1) * fs + 0.8 * fs)
                ops.append('q %s rg %.3f %.3f %.3f %.3f re f Q' % (rgb0, xx, H - Y - TH + 0.35 * R, bw, TH - 0.7 * R))
                tex.append(self.put_box(xx, Y, bw, TH, bt, 'c', 'm'))
                tex.append(self.put_box(xx + bw + 0.6 * fs, Y, colw, TH, self.inl.run('%s ― %s' % (P['a'], P['b']), Ctx('GB', 1.15)), 'l', 'm'))
                if P.get('fare'):
                    a_, b_ = P['fare']
                    ft = ('{:,}'.format(a_) if a_ == b_ else '{:,}∼{:,}'.format(a_, b_)) + '원'
                    tex.append(self.put_box(xx, Y, colw - pad, TH, self.inl.run(ft, Ctx('M', 0.85)), 'r', 'm'))
                yy = Y + TH
                rects.append(('h', xx, xx + colw, yy, 2))
                rows = [it for it in pc['items'] if it[0] == 'r']
                one = P.get('intl')                             # 국제선: 인천 쪽 시각 하나 (출발 | 도착)
                if rows:
                    for side, (o, d) in enumerate(((P['a'], P['b']), (P['b'], P['a']))):
                        hx = xx + side * hw + pad
                        lab = Ctx('G', 0.8)
                        tex.append(self.put_box(hx, yy, cN, SH, self.inl.run('편명', lab), 'l', 'm'))
                        if one:
                            tex.append(self.put_box(hx + cN, yy, cT + cA, SH, self.inl.run('인천 %s' % ('발' if side == 0 else '착'), lab), 'r', 'm'))
                            continue
                        tex.append(self.put_box(hx + cN, yy, cT, SH, self.inl.run(o, lab), 'r', 'm'))
                        tex.append(self.put_box(hx + cN + cT + cA, yy, cT, SH, self.inl.run(d, lab), 'r', 'm'))
                        if wide:
                            xw = hx + cN + 2 * cT + cA + 0.8 * fs
                            for d_ in range(7): tex.append(self.put_box(xw + d_ * DWd, yy, DWd, SH, self.inl.run(WDN[d_], Ctx('G', 0.7)), 'c', 'm'))
                    yy += SH
                    rects.append(('h', xx, xx + colw, yy, 1))
                    r0 = yy
                    for _, r_ in rows:
                        for side, L in enumerate((P['out'], P['in'])):
                            if r_ >= len(L): continue
                            no, t, a, lab_ = L[r_][:4]
                            if wide: lab_ = L[r_][5]
                            hx = xx + side * hw + pad
                            if wide:
                                xw = hx + cN + 2 * cT + cA + 0.8 * fs
                                for d_, f_ in enumerate(L[r_][4]):
                                    if f_ == '1': rects.append(('dot', xw + (d_ + 0.5) * DWd, yy + R / 2, 0.32 * fs))
                            mk_ = self.air_marks(lab_)
                            if mk_: marks_at(hx - 0.2 * fs, yy, mk_)
                            co_, nu_ = self._fno(no)
                            if cC: tex.append(self.put_box(hx + cM, yy, cC, R, self.inl.run(co_, Ctx('G', 0.85).but(hscale=HS)), 'l', 'm'))
                            tex.append(self.put_box(hx + cM + cC, yy, cN - cM - cC, R, self.inl.run(nu_, Ctx('M', 1.0).but(hscale=hsN)), 'l', 'm'))
                            if one:
                                tex.append(self.put_box(hx + cN, yy, cT + cA, R, self.inl.run(hmf(t), Ctx('DM', 1.0)), 'r', 'm'))
                                continue
                            tex.append(self.put_box(hx + cN, yy, cT, R, self.inl.run(hmf(t), Ctx('DM', 1.0)), 'r', 'm'))
                            tex.append(self.put_box(hx + cN + cT, yy, cA, R, self.inl.run('→', Ctx('M', 0.8)), 'c', 'm'))
                            tex.append(self.put_box(hx + cN + cT + cA, yy, cT, R, self.inl.run(hmf(a), Ctx('DM', 1.0)), 'r', 'm'))
                        yy += R
                    rects.append(('v', xx + hw, r0 - SH, yy, 1))
                notes = [it for it in pc['items'] if it[0] == 'n']
                if notes:
                    n0 = yy
                    for _, l_, r_ in notes:
                        for x_, t_ in ((xx, l_), (xx + hw, r_)):
                            if not t_: continue
                            mk_, tx_ = t_.split('\t', 1) if '\t' in t_ else ('', t_)
                            if mk_: tex.append(self.put_box(x_ + pad - 0.3 * fs, yy, WMn, R, mark_(mk_), 'r', 'm'))
                            tex.append(self.put_box(x_ + pad - 0.3 * fs + WMn + 0.15 * fs, yy, hw - 2 * pad - WMn, R, seg(tx_, 0.85), 'l', 'm'))
                        yy += R
                    rects.append(('v', xx + hw, n0, yy, 1))
                yy += pad
                rects.append(('box', xx, Y, xx + colw, yy, self.rw[1]))
                yEnd = yy
            ends.append((xx, yEnd, len(rects) - 1 if rects and rects[-1][0] == 'box' else None))
        # 항공의 마지막 쪽: 남는 자리에 항공사 표 (이름 ··· 두 자·세 자 부호), 쪽 폭으로
        al = self.cfg.get('airlines', {})
        yAL = None
        if al and k == len(self.air) - 1:
            cf_ = self.cfg.get('airCodes')
            codes = json.load(open(os.path.join(self.base, cf_), encoding='utf-8')) if cf_ else {}
            ent = sorted(al.items(), key=lambda kv: kv[1])
            NA = 3; nr = -(-len(ent) // NA)
            hA = TH + nr * R + pad
            top = max(e[1] for e in ends)
            if top + hA <= yB + 0.01:
                yAL = yB - hA                                # 쪽 아래에 붙여
                Wf = colw * sec['NC']
                tex.append(self.put_box(x0 + pad, yAL, Wf, TH, self.inl.run('항공사', Ctx('GB', 1.15)), 'l', 'm'))
                rects.append(('h', x0, x0 + Wf, yAL + TH, 2))
                cw3 = Wf / NA
                for i_, (iata, nm) in enumerate(ent):
                    cx, ry = x0 + (i_ // nr) * cw3 + pad, yAL + TH + (i_ % nr) * R
                    nt = self.inl.run(nm, Ctx('M', 0.9)); ct = self.inl.run('%s　%s' % (iata, codes.get(iata, '')), Ctx('M', 0.9).but(hscale=HS))
                    tex.append(self.put_box(cx, ry, cw3 - 2 * pad, R, nt, 'l', 'm'))
                    tex.append(self.put_box(cx, ry, cw3 - 2 * pad, R, ct, 'r', 'm'))
                    a_, b_ = cx + self.inl.wc.get(nt, 1) * fs + 0.5 * fs, cx + cw3 - 2 * pad - self.inl.wc.get(ct, 1) * fs - 0.5 * fs
                    if b_ - a_ > fs: ops.append(self.dots(a_, b_, ry + R / 2))
                for j_ in range(1, NA): rects.append(('v', x0 + j_ * cw3, yAL + TH, yAL + hA, 1))
                rects.append(('box', x0, yAL, x0 + Wf, yB, self.rw[1]))
        yb_ = yAL if yAL is not None else yB
        for xx, yEnd, bi in ends:
            if 0 < yb_ - yEnd < R and bi is not None:      # 한 줄도 안 남으면 마지막 덩이를 아래 끝까지
                rects[bi] = rects[bi][:4] + (yb_,) + rects[bi][5:]
            elif yb_ - yEnd >= R: rects.append(('box', xx, yEnd, xx + colw, yb_, self.rw[1]))     # 남는 자리: 빈 상자
        tex += self.page_side_title(recto, [('', sec['title'])])
        return tex, ' '.join(ops) + ' ' + (self.pdf_ops(rects) if rects else '')

    # ── 고속버스: 출발 터미널마다(가나다) 행선지마다 소요·요금과 발차 시각을 죽. 두 단으로 흘려 짠다 ──
    def plan_bus(self):
        """고속버스: 출발 터미널마다 행선지마다 발차를 한 줄씩. [발 | 착 | 등급 | 월 화 수 목 금 토 일].
        요일 칸: 다니는 날에 점. 날에 따라 등급이 바뀌는 편은 점 대신 그날 등급 글자를 넣고 등급 칸은 비운다."""
        self.bus = []
        f = self.cfg.get('bus')
        if not f: return
        data = json.load(open(os.path.join(self.base, f), encoding='utf-8'))
        # 노선표로 옮긴 구간: 출발 터미널 목록에 참조 줄만 (「센트럴시티(서울) → 익산 ― 센트럴시티(서울) 61」)
        self.bus_tpage = {}
        # 표 이름 맞추기: 세로 띠 제목은 세로꼴 글자(︱︵︶)로 바뀌어 있고, 나눈 표는 「(둘째)」가 붙는다
        self._tkey = tkey = lambda t: re.sub(r'[(（](첫째|둘째|셋째|넷째|다섯째|여섯째)[)）]|\s', '', t.translate(str.maketrans('︱︵︶（）', '―()()')))
        for pi, pg in enumerate(self.pages):
            for pc in pg['pieces']:
                if pc['T'].title is not None: self.bus_tpage.setdefault(tkey(pc['T'].title.text()), pi)
        org = {O['from']: O for O in data['origins']}
        for A, D, tt, *df in data.get('tableRefs', []):
            if A not in org: org[A] = {'from': A, 'dests': []}; data['origins'].append(org[A])
            ex_ = next((X for X in org[A]['dests'] if X['to'] == D and 'times' in X), None)
            if ex_ is not None:                             # 같은 행선지 목록 덩이가 있으면 그 덩이에 「이 밖에 노선표 56」 (아산온양: 배방 경유는 목록, 아산탕정 경유는 노선표)
                if tt not in ex_.setdefault('tabRefs', []): ex_['tabRefs'].append(tt)
                continue
            ex2_ = next((X for X in org[A]['dests'] if X['to'] == D and ('see' in X or 'seeFrom' in X)), None)
            if ex2_ is not None:                            # 참조 줄 덩이(「→ 원주 행」)가 있으면 그 밑에 「→ 노선표」
                ex2_.setdefault('alsoTable', tt); continue
            org[A]['dests'].append({'to': D, 'seeTable': tt, 'dur': df[0] if df else None, 'fare': df[1] if len(df) > 1 else None})
        sn = data.get('names', {}); sh_ = lambda x: sn.get(x, x)      # 짧은 터미널 이름 (센트럴시티(서울) → 서울호남)
        for O in data['origins']:
            O['from'] = sh_(O['from'])
            for X in O['dests']:
                X['to'] = sh_(X['to'])
                for k_ in ('see', 'seeFrom'):
                    if k_ in X: X[k_] = sh_(X[k_])
                if 'via' in X: X['via'] = [[sh_(v[0])] + v[1:] for v in X['via']]
                if 'board' in X: X['board'] = [' '.join([sh_(v.split(' ', 1)[0])] + v.split(' ', 1)[1:]) for v in X['board']]     # 「천안종합운동장 +20분」도 짧은 이름으로
                if 'mid' in X:                              # 사이 칸 이름: 끝(또는 출발) 터미널 이름을 앞에 단 것은 줄여 (진주개양 → 개양, 원주문막 → 문막, 인천공항T1 → T1)
                    def _cut(n_, X_=X, O_=O):
                        for base_ in sorted({X_['to'], O_['from'], re.sub(r'\(.*\)|T\d$', '', X_['to']), re.sub(r'\(.*\)|T\d$', '', O_['from'])}, key=len, reverse=True):
                            if base_ and n_.startswith(base_) and len(n_) > len(base_): return n_[len(base_):]
                        return n_
                    X['mid'] = [[_cut(sh_(m[0]))] + m[1:] for m in X['mid']]
                if 'lab' in X: X['lab'] = [re.sub(r'^(→)?(\S+)', lambda mo: (mo.group(1) or '') + sh_(mo.group(2)), l_) if l_ else l_ for l_ in X['lab']]
        data['origins'].sort(key=lambda O: O['from'])
        for O in data['origins']: O['dests'].sort(key=lambda X: X['to'])
        R, fs = self.R, self.fs
        pad = 0.5 * fs
        TS, GW, DW = 2.7 * fs, 1.2 * fs, 0.9 * fs
        MW = 0.55 * fs                                      # 시외버스 표지(†) 칸
        MIDW0 = 3.6 * fs                                    # 발・착 사이: 사이 정류장 시각(둘까지)・이어지는 차 안내・「20분마다」
        NC = max(1, int(self.cw / (MW + 2 * TS + MIDW0 + GW + 7 * DW + 0.9 * fs)))
        colw = self.cw / NC
        MIDW = colw - 0.7 * fs - MW - 2 * TS - GW - 7 * DW       # 남는 폭은 사이 칸에
        TH, CH = 1.5 * R, 0.85 * R                          # 출발 터미널 머리, 칸 머리
        GP = 0.4 * R                                        # 행선지 이름 위 여백
        DH = R + GP
        SR = 0.85 * R                                       # 경유·승차 줄
        BG = 0.25 * R                                       # 덩이 아래 여백 (착 줄·참조 줄과 아래 괘선 사이)
        ww_ = colw - 1.0 * fs
        wsm = lambda t: self.inl.wc.get(self.inl.run(t, Ctx('M', 0.72).but(hscale=0.82)), len(t)) * fs
        hm_ = self.dur_text
        mm_ = lambda s_: int(s_[:-2]) * 60 + int(s_[-2:])
        hmc = lambda m: ('%d:%02d' % divmod(int(m), 60)) if m >= 60 else '%d분' % m        # 띠의 짧은 소요 「3:35」「30분」
        # 덩이 몸: 발차 시각을 줄줄이. 줄 머리는 요일 점(그 줄의 차가 다니는 날)·등급 네모·시외 †
        DWg = 0.56 * fs
        LBW = 2.45 * fs + 0.5 * fs                          # 줄 머리 폭 (다니는 날 석 자 + 시외 †)
        NT = 5                                              # 한 줄에 발차 시각 다섯
        SW = (colw - 2 * pad - LBW) / NT                    # 시각 한 칸: 시각 + 오른쪽 작은 칸(위: ◇ → 따위, 아래: 등급)
        GORD = {'우': 0, '프': 1, '일': 2, '심': 3, '심프': 4, '심일': 5, '◆': 6}
        def block_lines(X, O):
            """덩이: (머리 밑 작은 줄들, 시각 줄들). 시각 줄 = (줄 머리 또는 None, [칸...])"""
            rows = list(zip(X['times'], X.get('mt') or [[]] * len(X['times']), X.get('lab') or [''] * len(X['times'])))
            durs = collections.Counter((mm_(t[1]) - mm_(t[0])) % 1440 for t, _, _ in rows if t[1])
            dur0 = X['dur'] if X['dur'] in durs else (durs.most_common(1)[0][0] if durs else X['dur'])
            mids = X.get('mid') or []
            part = [k for k in range(len(mids)) if not all(mt[k] for _, mt, _ in rows if len(mt) > k)]
            pmk = {k: '◇△'[j] for j, k in enumerate(part[:2])}
            dlet, dl_ = {}, 'abcdefgh'
            for d_, _ in sorted(durs.items()):
                if d_ != dur0 and len(dlet) < len(dl_): dlet[d_] = dl_[len(dlet)]
            # 띠: 출발 ─ 사이 정류장(시각) ─ 끝
            el = []
            for k, m_ in enumerate(mids):
                offs = collections.Counter((mm_(mt[k]) - mm_(t[0])) % 1440 for t, mt, _ in rows if len(mt) > k and mt[k])
                if not offs: continue
                o_ = offs.most_common(1)[0][0]
                el.append((o_, m_[0] + pmk.get(k, ''), ('+' + hmc(o_)) if m_[1] == 'd' else hmc(o_)))
            for v in X.get('via', []):
                el.append((v[1] if v[1] not in (None, X['dur']) else 10 ** 6, v[0], hmc(v[1]) if v[1] not in (None, X['dur']) else ''))
            for s_ in X.get('board', []):
                n_, _, r_ = s_.partition(' ')
                el.append((-1, n_, r_.replace('시간 ', ':').replace('시간', ':00').replace('분', '') if r_ else ''))
            el.sort(key=lambda e: e[0])
            sub = []
            if el:
                parts_ = [O['from']] + ['%s %s' % (e[1], e[2]) if e[2] else e[1] for e in el] + ['%s %s' % (X['to'], hmc(dur0))]
                cur = ''
                for k_, p_ in enumerate(parts_):
                    sep_ = '' if k_ == 0 else ' ─ '
                    if cur and wsm(cur + sep_ + p_) > ww_: sub.append(cur + ' ─'); cur = '　' + p_
                    else: cur += sep_ + p_
                sub.append(cur)
            # 이어지는 차・소요가 다른 차 풀이
            leg = []
            cont, fromu = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
            for t, mt, lab in rows:
                if lab.startswith('→'):
                    n_, _, a_ = lab[1:].partition(' ')
                    if a_ and t[1]: cont[n_][(mm_(a_) - mm_(t[1])) % 1440] += 1
                elif lab.endswith('발'):
                    n_, _, d_ = lab[:-1].partition(' ')
                    if d_: fromu[n_][(mm_(t[0]) - mm_(d_)) % 1440] += 1
            CM = {}
            for j_, (n_, c_) in enumerate(sorted(cont.items())):
                CM['→' + n_] = '→⇒'[min(j_, 1)]; leg.append('%s %s까지 (%s 더)' % (CM['→' + n_], n_, hmc(c_.most_common(1)[0][0])))
            for j_, (n_, c_) in enumerate(sorted(fromu.items())):
                CM[n_] = '←⇐'[min(j_, 1)]; leg.append('%s %s 발 (%s 앞)' % (CM[n_], n_, hmc(c_.most_common(1)[0][0])))
            if dlet: leg.append('　'.join('%s %s' % (l_, hmc(d_)) for d_, l_ in sorted(dlet.items(), key=lambda kv: kv[1])) + ' 걸림')
            sub += leg
            if X.get('vnote'): sub.extend(X['vnote'].split('\n'))
            for tt_ in X.get('tabRefs', []): sub.append('이 밖에 노선표 {#%s}' % tt_)
            if X.get('gnote'):
                cur = ''
                for t_ in X['gnote'].split(', '):
                    if cur and wsm(cur + ', ' + t_) > ww_: sub.append(cur + ','); cur = '　' + t_
                    else: cur = (cur + ', ' + t_) if cur else t_
                sub.append(cur)
            # 시각 칸: 요일・등급・시외가 같은 차끼리 한 묶음
            grp = collections.OrderedDict()
            for t, mt, lab in rows:
                w = t[2]; gs_ = {g for g in w if g}
                gk = tuple(1 if g else 0 for g in w)            # 요일로만 묶고 등급은 시각마다 (날에 따라 바뀌는 차는 ◆)
                gr_ = next(iter(gs_)) if len(gs_) == 1 else '◆'
                mk = ''.join(pmk[k] for k in sorted(pmk) if len(mt) > k and mt[k])
                if lab.startswith('→'): mk += CM.get('→' + lab[1:].partition(' ')[0], '→')
                elif lab.endswith('발'): mk += CM.get(lab[:-1].partition(' ')[0], '←')
                if t[1]:
                    d_ = (mm_(t[1]) - mm_(t[0])) % 1440
                    if d_ in dlet: mk += dlet[d_]
                grp.setdefault((gk, '시' in t[3:]), []).append((t[0], mk, gr_))
            def gsort(kv):
                (gk, sb), toks = kv
                return (-sum(gk), gk[::-1], sb, mm_(toks[0][0]))
            lines = []
            for (gk, sb), toks in sorted(grp.items(), key=gsort):
                cells = [('t',) + tk_ for tk_ in toks]
                for k_ in range(0, len(cells), NT):
                    lines.append((((gk, sb) if k_ == 0 else None), cells[k_:k_ + NT]))
            return sub, lines
        items = []                                          # (종류, 내용)
        for O in data['origins']:
            items.append(('o', O['from']))
            for X in O['dests']:
                if 'times' not in X: items.append(('r', X)); continue
                X['_sub'], lines_ = block_lines(X, O)
                X['_nl'] = len(lines_)
                items.append(('d', X))
                for ln_ in lines_: items.append(('g', ln_, X))
        cols, col, y = [], [], 0.0
        cur_o = None
        def head(o, cont):
            nonlocal y
            col.append(('o', y, o)); y += TH + GP              # 출발 터미널 이름 위에도 행선지만큼 여백
            col.append(('c', y, None)); y += CH
        i = 0
        cap = self.ch
        while i < len(items):
            k, v = items[i][0], items[i][1]
            if k == 'o':
                cur_o = v
                if col and y + TH + GP + CH + DH + 3 * R > cap: cols.append(col); col, y = [], 0.0
                head(v, False); i += 1; cur_x = None; continue
            if not col: head(cur_o, True)
            if k == 'r':                                    # 참조 줄: 「서대구 → 동대구 행」「서울경부 → 평택 발 52」
                rh_ = DH + SR * (2 if v.get('alsoTable') else 1) + BG          # 「→ 원주 행」 밑에 「→ 노선표」도 (갈래 노선의 편이 표에 실린 것)
                if y + rh_ > cap + 1e-6: cols.append(col); col, y = [], 0.0; continue
                col.append(('r', y, v, cur_o)); y += rh_; i += 1; continue
            if k == 'd':
                cur_x = v
                hd = DH + SR * len(v['_sub']) + (BG if v['_sub'] else 0)      # 안내 줄 밑에도 덩이 아래만큼 여백
                need = hd + R * min(2, v['_nl'])               # 머리 밑에 적어도 두 줄
                if y + need > cap + 1e-6: cols.append(col); col, y = [], 0.0; continue
                col.append(('d', y, v, False, hd, cur_o)); y += hd; i += 1; continue
            if y + R > cap + 1e-6:
                cols.append(col); col, y = [], 0.0
                head(cur_o, True); col.append(('d', y, cur_x, True, DH, cur_o)); y += DH
            col.append((k, y, v) + tuple(items[i][2:])); y += R; i += 1
            if i >= len(items) or items[i][0] != 'g': y += BG
        if col: cols.append(col)
        pages = [cols[k:k + NC] for k in range(0, len(cols), NC)]
        self._bus = (colw, pad, TS, GW, DW, TH, CH, GP, NC, SR, BG, MIDW, DWg, LBW, SW)
        self.bus_opage = {}                                 # 출발 터미널 → 그 덩이가 시작하는 쪽 (self.pages 의 자리)
        self.bus_dpage = {}                                 # (출발, 행선지) → 그 행선지 덩이가 실린 쪽
        for i, p in enumerate(pages):
            for c_ in p:
                for it in c_:
                    if it[0] == 'o': self.bus_opage.setdefault(it[2], len(self.pages))
                    if it[0] == 'd' and not it[3]: self.bus_dpage[(it[5], it[2]['to'])] = len(self.pages)
            self.bus.append(p); self.pages.append({'pieces': [], 'lines': [], 'bus': i})

    @staticmethod
    def day_text(mask):
        """다니는 요일 (노선표 비고와 같게): 날마다는 빈칸, 이어진 날은 「금∼일」, 아니면 「토일」, 넉 자 넘으면 쉬는 날로 「금일휴」"""
        WD = '월화수목금토일'
        ws = [d for d in range(7) if mask[d]]
        def one(ws_):
            if len(ws_) == 7 or not ws_: return ''
            if ws_ == [0, 1, 2, 3, 4]: return '월∼금'
            if len(ws_) >= 3:
                for s0 in ws_:
                    if sorted((s0 + k) % 7 for k in range(len(ws_))) == ws_: return WD[s0] + '∼' + WD[(s0 + len(ws_) - 1) % 7]
            return ''.join(WD[w] for w in ws_)
        t = one(ws)
        if len(t) > 3:
            t2 = one([d for d in range(7) if not mask[d]]) + '휴'
            if len(t2) < len(t): t = t2
        return t

    @staticmethod
    def dur_text(m):
        """소요: 「3시간 20분」「45분」「2시간」"""
        h, mi = divmod(int(m), 60)
        return ('%d시간' % h if h else '') + (' ' if h and mi else '') + ('%d분' % mi if mi or not h else '')

    def bus_page(self, k, x0, recto):
        fs, R = self.fs, self.R
        colw, pad, TS, GW, DW, TH, CH, GP, NC, SR, BG, MIDW, DWg, LBW, SW = self._bus
        first = self.cfg.get('firstFolio', 2)
        yB = y0_ = self.mt
        yB = y0_ + self.ch
        tex, rects = [], []
        y0 = self.mt
        HS = 0.82
        WD = '월화수목금토일'
        rd = 0.16 * fs
        def dot(cx, cy): rects.append(('dot', cx, cy, 2 * rd))
        def gmark(g, sz):
            """등급 네모 한 자: □우 □프 □일, 심야는 검은 네모에 흰 글자 ■우 ■프 ■일"""
            base, fill = {'심': ('우', 1), '심프': ('프', 1), '심일': ('일', 1)}.get(g, (g, 0))
            if base not in ('우', '프', '일'): return self.inl.run(base, Ctx('M', sz))      # ※ ◆ 따위
            inner = self.inl.run(base, Ctx('G', sz * 0.88, 'FFFFFF' if fill else None))
            wh = 1.05 * sz * fs
            return r'\ttbadge{%.3f}{%.3f}{%d}{1.000}{%.3f}{%s}' % (wh, wh, fill, self.inl.c * sz * fs, inner)
        for ci in range(NC):                           # 단은 맞붙여 한 표처럼
            xx = x0 + ci * colw
            ww = colw
            col = self.bus[k][ci] if ci < len(self.bus[k]) else []
            if not col: rects.append(('box', xx, y0, xx + ww, yB, self.rw[1])); continue
            xL = xx + pad; xT0 = xx + pad + LBW                 # 줄 머리(요일 점・등급) | 발차 시각 칸들
            seg = []                                   # 세로줄을 그을 시각 줄 구간
            st = None; lastT = -1.0
            for it in col:
                kd, y = it[0], y0 + it[1]
                if kd != 'g' and st is not None: seg.append((st, lastT if lastT > st else y)); st = None
                if kd == 'g': lastT = y + R
                if kd == 'o':
                    if it[1] > 0: rects.append(('h', xx, xx + ww, y, 2))
                    tex.append(self.put_box(xx + pad, y + GP, ww - 2 * pad, TH, self.inl.run('%s 발' % it[2], Ctx('GB', 1.15)), 'l', 'm'))
                elif kd == 'c':
                    tex.append(self.put_box(xL, y, LBW - 0.5 * fs, CH, self.inl.run('운행일', Ctx('G', 0.62)), 'c', 'm'))
                    tex.append(self.put_box(xT0, y, xx + ww - pad - xT0, CH, self.inl.run('발차 시각', Ctx('G', 0.7)), 'l', 'm'))
                    rects.append(('h', xx, xx + ww, y + CH, 1))
                    st = y
                elif kd == 'r':                                # 참조 덩이: 머리(이름·소요·요금)는 여느 덩이처럼, 밑줄에 「→ 동대구 행 95」
                    X = it[2]
                    if it[1] > 0 and col[col.index(it) - 1][0] in ('g', 'r'): rects.append(('h', xx, xx + ww, y, 1))
                    y += GP
                    du = self.dur_text(X['dur']) if X.get('dur') else ''
                    fa = ('{:,}원'.format(X['fare'][0]) + ('∼' if X['fare'][1] != X['fare'][0] else '')) if X.get('fare') else ''
                    tex.append(self.put_box(xx + pad, y, ww - 2 * pad, R, self.inl.run(X['to'], Ctx('GB', 0.9)), 'l', 'm'))
                    tex.append(self.put_box(xx + pad, y, ww - 2 * pad, R, self.inl.run(du + '　' + fa, Ctx('M', 0.72).but(hscale=HS)), 'r', 'm'))
                    y += R
                    if 'see' in X: pg_, rt = self.bus_dpage.get((it[3], X['see'])), '%s 행' % X['see']
                    elif 'seeTable' in X: pg_, rt = self.bus_tpage.get(self._tkey(X['seeTable'])), '노선표'
                    else: pg_, rt = self.bus_opage.get(X['seeFrom']), '%s 발' % X['seeFrom']
                    rc = Ctx('M', 0.72).but(hscale=HS)
                    bx = (r'\kern%.3fbp ' % (0.3 * fs) + self.page_badge(pg_ + first, 0.9, None, 0.72)) if pg_ is not None else ''    # 쪽 번호는 철도처럼 네모 안에
                    tex.append(self.put_box(xx + pad, y, ww - 2 * pad, SR, self.inl.run('→ ' + rt, rc) + bx, 'l', 'm'))
                    if X.get('alsoTable'):
                        y += SR
                        pg2_ = self.bus_tpage.get(self._tkey(X['alsoTable']))
                        bx2 = (r'\kern%.3fbp ' % (0.3 * fs) + self.page_badge(pg2_ + first, 0.9, None, 0.72)) if pg2_ is not None else ''
                        tex.append(self.put_box(xx + pad, y, ww - 2 * pad, SR, self.inl.run('→ 노선표', rc) + bx2, 'l', 'm'))
                elif kd == 'd':
                    X = it[2]
                    if it[1] > 0 and col[col.index(it) - 1][0] in ('g', 'r'): rects.append(('h', xx, xx + ww, y, 1))
                    y += GP
                    du = self.dur_text(X['dur'])
                    fa = ('{:,}원'.format(X['fare'][0]) + ('∼' if X['fare'][1] != X['fare'][0] else '')) if X.get('fare') else ''
                    it_ = self.inl.run(du + '　' + fa, Ctx('M', 0.72).but(hscale=HS))
                    nt_ = self.inl.run(X['to'], Ctx('GB', 0.9))
                    room = ww - 2 * pad - self.inl.wc.get(it_, 0) * fs - 0.4 * fs        # 이름이 소요·요금에 닿으면 이름을 가로로 좁힌다
                    wn_ = self.inl.wc.get(nt_, 0) * fs
                    if wn_ > room > 0: nt_ = self.inl.run(X['to'], Ctx('GB', 0.9).but(hscale=max(0.6, room / wn_)))
                    tex.append(self.put_box(xx + pad, y, ww - 2 * pad, R, nt_, 'l', 'm'))
                    tex.append(self.put_box(xx + pad, y, ww - 2 * pad, R, it_, 'r', 'm'))
                    y += R
                    if not it[3]:
                        for ln in X.get('_sub', []):
                            parts_ = re.split(r'\{([^}]*)\}', ln)          # {프}: 등급 네모 표지
                            def pbadge_(p_):
                                pg_ = self.bus_tpage.get(self._tkey(p_[1:]))
                                return (r'\kern%.3fbp ' % (0.2 * fs) + self.page_badge(pg_ + first, 0.9, None, 0.72)) if pg_ is not None else ''
                            tex.append(self.put_box(xx + pad, y, ww - 2 * pad, SR, ''.join((pbadge_(p_) if p_.startswith('#') else gmark(p_, 0.66)) if k_ % 2 else self.inl.run(p_, Ctx('M', 0.72).but(hscale=HS)) for k_, p_ in enumerate(parts_) if p_), 'l', 'm'))
                            y += SR
                        if X.get('_sub'): y += BG
                    st = y
                else:                                          # 시각 줄: 머리(그 묶음 첫 줄만) + 시각 칸들
                    lab_, cells = it[2]
                    if lab_ is not None:
                        (gk, sb) = lab_
                        dt_ = self.day_text(gk)                # 노선표처럼 석 자까지: 「금∼일」「토일」「금일휴」, 날마다는 비움
                        if dt_:
                            ct_ = self.inl.run(dt_, Ctx('G', 0.74))
                            wd_ = self.inl.wc.get(ct_, len(dt_)) * fs
                            if wd_ > LBW - 0.6 * fs: ct_ = self.inl.run(dt_, Ctx('G', 0.74).but(hscale=max(0.5, (LBW - 0.6 * fs) / wd_)))
                            tex.append(self.put_box(xL, y, LBW - 0.5 * fs, R, ct_, 'c', 'm'))
                        if sb: tex.append(self.put_box(xL + LBW - 0.5 * fs, y, 0.4 * fs, R, self.inl.run('†', Ctx('M', 0.7)), 'c', 'm'))
                    for k_, c_ in enumerate(cells):
                        xs = xT0 + k_ * SW
                        if c_[0] == 'z':                       # 거의 같은 간격: 「매 20분」「15∼20분」
                            zt = ('매%d분' % c_[1]) if c_[1] == c_[2] else ('%d∼%d분' % (c_[1], c_[2]))
                            tex.append(self.put_box(xs, y, SW, R, self.inl.run('⋯' + zt + '⋯', Ctx('M', 0.68).but(hscale=0.8)), 'c', 'm'))
                            continue
                        _, tm_, mk_, gr_ = c_
                        MKW = 0.6 * fs
                        tex.append(self.put_box(xs, y, SW - MKW, R, self.inl.run(tm_, Ctx('DM', 0.95)), 'r', 'm'))
                        if mk_: tex.append(self.put_box(xs + SW - MKW + 0.04 * fs, y, MKW, 0.55 * R, self.inl.run(mk_, Ctx('M', 0.58 if len(mk_) == 1 else 0.46)), 'l', 'm'))
                        if gr_ != '우':                        # 등급: 시각 오른쪽 아래 작은 네모 (◆ 날에 따라 바뀜)
                            gm_ = self.inl.run('◆', Ctx('M', 0.5)) if gr_ == '◆' else gmark(gr_, 0.5)
                            tex.append(self.put_box(xs + SW - MKW + 0.04 * fs, y + 0.45 * R, MKW, 0.55 * R, gm_, 'l', 'm'))
            yE = y0 + max(it[1] + (TH + GP if it[0] == 'o' else CH if it[0] == 'c' else it[4] if it[0] == 'd' else R + GP + SR * (2 if it[2].get('alsoTable') else 1) + BG if it[0] == 'r' else R + BG) for it in col)
            if st is not None: seg.append((st, lastT if lastT > st else yE))
            for a, b in seg:
                rects.append(('v', xT0 - 0.15 * fs, a, b, 1))       # 줄 머리 | 시각
            if yB - yE < R: yE = yB                    # 한 줄도 안 남으면 빈 상자 없이 표를 쪽 끝까지 (아래는 여백으로)
            rects.append(('box', xx, y0, xx + ww, yE, self.rw[1]))
            if yB - yE >= R: rects.append(('box', xx, yE, xx + ww, yB, self.rw[1]))     # 남는 자리: 빈 상자
        tex += self.page_side_title(recto, [('', '고속버스')])
        return tex, self.pdf_ops(rects) if rects else ''

    # ── 책 뒤: 역명 색인과 판권 ──
    def station_pages(self, first):
        sp = collections.defaultdict(set)
        for pi, pg in enumerate(self.pages):
            for pc in pg.get('pieces', []):
                T = pc['T']; rs = set(pc['rows'])
                if T.line in self.cfg.get('otherModes', ['고속버스']): continue      # 버스 터미널은 역명 색인에 넣지 않는다
                for cl in T.cells:
                    if 'jtt-st' in cl.cls and 'jtt-th' not in cl.cls and cl.r in rs and T.kind[cl.c][0] == 'L':
                        nm = re.sub(r'[\(（].*?[\)）]|\s', '', cl.node.text())
                        nm = self.cfg.get('stationAlias', {}).get(nm, {}).get(T.line, nm)     # 이름이 같은 다른 역: 판교(경기)
                        if nm and nm != '〃': sp[nm].add(pi + first)
        return sp

    def plan_back(self):
        self.back = []
        si = self.cfg.get('stationIndex')
        if not si: return
        first = self.cfg.get('firstFolio', 2)
        fs = self.fs
        sp = self.station_pages(first)
        def rng(ps):
            ps = sorted(ps); out = []; a = b = ps[0]
            for p in ps[1:]:
                if p == b + 1: b = p
                else: out.append((a, b)); a = b = p
            out.append((a, b))
            return ', '.join(str(a) if a == b else '%d∼%d' % (a, b) for a, b in out)
        NC = si.get('cols', 4)
        fw, fp, pad, R = self.frame_w, self.frame_pad, self.band_inset, self.R
        colw = (self.cw - 2 * (fw + fp)) / NC
        ww = colw - 2 * pad                      # 단 안의 글줄 폭
        lh = R
        cap = int((self.ch - 2 * (fw + fp)) / lh + 1e-6)
        wd = lambda t, c: self.inl.wc.get(self.inl.run(t, c), len(t)) * fs
        CHO = 'ㄱㄱㄴㄷㄷㄹㅁㅂㅂㅅㅅㅇㅈㅈㅊㅋㅌㅍㅎ'
        units, cur = [], None             # unit: 함께 둘 줄들 [(종류, …)]
        for nm in sorted(sp):
            c0 = CHO[(ord(nm[0]) - 0xAC00) // 588] if '가' <= nm[0] <= '힣' else nm[0]
            ps = rng(sp[nm])
            if wd(nm, Ctx('M', 1.0)) + wd(ps, Ctx('M', 1.0)) + 2 * fs <= ww: ent = [('e', nm, ps)]
            else:                          # 쪽이 많으면 첫 줄은 이름에 점으로 이어 채우고, 나머지는 다음 줄에 (쉼표에서)
                ent, ln_ = [], ''
                lim = ww - wd(nm, Ctx('M', 1.0)) - 2 * fs        # 첫 줄에 쪽을 적을 폭
                for part in ps.split(', '):
                    t_ = (ln_ + ', ' + part) if ln_ else part
                    if ln_ and wd(t_ + ',', Ctx('M', 1.0)) > (lim if not ent else ww - fs):
                        ent.append(('e', nm, ln_ + ',') if not ent else ('p', '', ln_ + ',')); ln_ = part
                    else: ln_ = t_
                ent.append(('e', nm, ln_) if not ent else ('p', '', ln_))
            if c0 != cur:
                cur = c0; units.append([('b', '', ''), ('h', c0, '')] + ent)      # 자음 머리 위는 한 줄 비운다 (단 맨 위면 안 비움)
            else: units.append(ent)
        al = {}                                          # 항공사 표는 항공 마지막 쪽의 남는 자리에 (air_page)
        if al:
            cf_ = self.cfg.get('airCodes')
            codes = json.load(open(os.path.join(self.base, cf_), encoding='utf-8')) if cf_ else {}
            ent = [('e', nm, '%s　%s' % (k, codes.get(k, ''))) for k, nm in sorted(al.items(), key=lambda kv: kv[1])]
            units.append([('b', '', ''), ('h', '항공사', '')] + ent)
        def fill(us, c_):
            cols, col, cu, ucs = [], [], [], []
            for ui, u in enumerate(us):
                if col and len(col) + len(u) > c_: cols.append(col); ucs.append(cu); col, cu = [], []
                col += u[1:] if (not col and u[0][0] == 'b') else u; cu.append(ui)
            if col: cols.append(col); ucs.append(cu)
            return cols, ucs
        cols, ucs = fill(units, cap)
        pages = [cols[i:i + NC] for i in range(0, len(cols), NC)]
        # 마지막 쪽: 단을 고르게, 아래에 판권
        colo = self.cfg.get('colophon', [])
        hc = (len(colo) + 2) * lh if colo else 0
        rest = units[ucs[(len(pages) - 1) * NC][0]:]
        t = max(1, math.ceil(sum(len(u) for u in rest) / NC))
        while True:
            lc, _ = fill(rest, t)
            if len(lc) <= NC: break
            t += 1
        pages[-1] = lc
        fit = 2 * (fw + fp) + t * lh + hc <= self.ch
        for i, p in enumerate(pages):
            ln = i == len(pages) - 1
            self.back.append({'cols': p, 'colophon': bool(colo) and fit and ln,
                              'h': (2 * (fw + fp) + t * lh) if ln and colo and fit else self.ch})
        if colo and not fit: self.back.append({'cols': [], 'colophon': True, 'h': 0})
        self._ix = (colw, pad, lh)
        for i in range(len(self.back)): self.pages.append({'pieces': [], 'lines': [], 'back': i})

    def dots(self, a_, b_, yl):
        """이름과 쪽 번호를 잇는 점: 글줄 가운데 높이에 둥근 점"""
        p = 0.32 * self.fs
        n = int((b_ - a_) / p)
        a2 = b_ - n * p                                 # 오른쪽(쪽 번호) 끝에 맞춘다
        return 'q 0.55 w 1 J 0 G [0 %.3f] 0 d %.3f %.3f m %.3f %.3f l S Q' % (p, a2, self.H - yl, b_, self.H - yl)

    def title_page(self):
        """속표지 (1쪽, 쪽 번호 없음): 위에 책 이름, 아래에 목차와 범례를 모아"""
        fs, H = self.fs, self.H
        first = self.cfg.get('firstFolio', 2)
        x0, y0, W = self.mi, self.mt, self.cw
        R = self.R
        tex, ops, rects = [], [], []
        wd = lambda t: self.inl.wc.get(t, 1.0) * fs
        tp = self.cfg.get('titlePage', {})
        tex.append(self.put_box(x0, y0, W, 4.6 * fs, self.inl.run(tp.get('title', '시각표'), Ctx('GB', 4.6)), 'l', 't'))
        tex.append(self.put_box(x0, y0 + 5.6 * fs, W, 1.6 * fs, self.inl.run(tp.get('sub', ''), Ctx('M', 1.6)), 'l', 't'))
        gut = 3 * fs
        hh, ih = 2 * R, 1.5 * R                          # 범례 머리 행, 항목 행
        rng_ = lambda a, b: ('%d' % a) if a == b else ('%d∼%d' % (a, b))
        def head(xx, yy, w, name):
            tex.append(self.put_box(xx, yy, w, hh, self.inl.run(name, Ctx('GB', 1.1)), 'l', 'm'))
        # 목차: 큰 갈래(철도 · 역명 색인, 뒤에 항공 · 버스가 붙을 자리) 밑에 노선. 들여쓰기·밑줄 없이 글자 굵기로만 가른다
        lp = self.line_pages(first)
        bk_ = [i for i, pg in enumerate(self.pages) if 'back' in pg and self.back[pg['back']]['cols']]
        OTHER = self.cfg.get('otherModes', ['고속버스'])     # 철도 밖의 큰 갈래 (노선 이름 = 갈래 이름)
        rail = [(nm, a, b, T) for nm, (a, b, T) in lp.items() if nm not in OTHER]
        seq = [('h', '철도', min(x[1] for x in rail), max(x[2] for x in rail), None)] + [('i',) + x for x in rail]
        bi_ = [i for i, pg in enumerate(self.pages) if 'bus' in pg]
        for om in OTHER:
            if om in lp and not (om == '고속버스' and bi_): seq += [('g',), ('h', om, lp[om][0], lp[om][1], None)]
        for key_, lab_ in (('air', '항공'), ('bus', '고속버스')):
            ai_ = [i for i, pg in enumerate(self.pages) if key_ in pg]
            if key_ == 'bus' and ai_ and '고속버스' in lp:          # 고속버스: 노선표 + 터미널별 목록을 한 갈래로
                a_, b_ = lp['고속버스'][0], ai_[-1] + first
                seq += [('g',), ('h', lab_, a_, b_, None), ('i', '노선별', lp['고속버스'][0], lp['고속버스'][1], None),
                        ('i', '터미널별', ai_[0] + first, ai_[-1] + first, None)]
                continue
            if ai_: seq += [('g',), ('h', lab_, ai_[0] + first, ai_[-1] + first, None)]
            if key_ == 'air' and len(getattr(self, 'air_secs', [])) > 1:          # 항공 밑에 장마다
                for si_, sc_ in enumerate(self.air_secs):
                    pi_ = [i for i, pg in enumerate(self.pages) if pg.get('airSec') == si_]
                    if pi_: seq.append(('i', sc_['sub'] if 'sub' in sc_ else sc_['title'], pi_[0] + first, pi_[-1] + first, None))
        if bk_: seq += [('g',), ('h', '역명 색인', bk_[0] + first, bk_[-1] + first, None)]
        # 범례: 세 단 (등급 · KTX · 관광열차)
        lg = self.cfg.get('legend', [])
        groups, flat = [], []
        for head_, body_ in lg:
            if head_ or not groups: groups.append([head_, []])
            for it in [x.strip() for x in body_.split('　') if x.strip()]:
                m_ = re.match(r'^(B?S\{[^}]*\})\s+(.*)$', it)
                if m_: groups[-1][1].append((len(flat), m_.group(2).replace('`', ''))); flat.append(m_.group(1))
                else: groups[-1][1].append((None, it))
        rows_ = []
        if flat:
            html = run_module('title "x"\n\n[stations]\n가\n\n[notes]\n' + '\n'.join(flat), os.path.join(HERE, 'src', 'Timetable.lua'), os.path.join(HERE, 'build'))
            nd = parse_html(html).find(lambda n: 'jtt-notes' in n.cls)
            rows_ = [k_ for k_ in nd.kids if isinstance(k_, Node)] if nd is not None else []
        lg_h = max([hh + len(it) * ih for _, it in groups] + [0])
        bottom = y0 + self.ch
        yl0 = bottom - lg_h
        sh = {'h': hh, 'i': ih, 'g': R}
        def colh(xs): return sum(sh[x[0]] for x in xs)
        best = None                                      # 두 단: 높이가 고르게, 갈래 머리가 단 끝에 홀로 남지 않게
        for k_ in range(1, len(seq)):
            if seq[k_ - 1][0] in ('h', 'g'): continue
            c1, c2 = seq[:k_], [x for n_, x in enumerate(seq[k_:]) if not (n_ == 0 and x[0] == 'g')]
            m_ = max(colh(c1), colh(c2) + (hh if c2[0][0] == 'i' else 0))      # 이어지는 단은 갈래 머리 높이만큼 내려서 (줄을 맞춘다)
            if best is None or m_ < best[0]: best = (m_, c1, c2)
        _, c1, c2 = best
        yc0 = yl0 - 2 * R - best[0]
        cw2 = (W - gut) / 2
        for c_i, col in enumerate((c1, c2)):
            xx = x0 + c_i * (cw2 + gut); yy = yc0 + (hh if col[0][0] == 'i' else 0)
            for x in col:
                if x[0] == 'g': yy += R; continue
                _, inm, ia, ib, T = x
                hd_ = x[0] == 'h'; h_ = sh[x[0]]
                kt = T is not None and self.is_ktx(T)
                it = self.inl.run(inm, Ctx('GB', 1.1) if hd_ else Ctx('M', 1.0, '0A5FE0' if kt else None))
                ip = self.inl.run(rng_(ia, ib), Ctx('M', 1.1 if hd_ else 1.0))
                tex.append(self.put_box(xx, yy, cw2, h_, it, 'l', 'm'))
                tex.append(self.put_box(xx, yy, cw2, h_, ip, 'r', 'm'))
                ops.append(self.dots(xx + wd(it) + 0.6 * fs, xx + cw2 - wd(ip) - 0.6 * fs, yy + h_ / 2))
                yy += h_
        nG = max(1, len(groups))
        cw3 = (W - (nG - 1) * gut) / nG
        bw_ = 4.2 * fs
        for g_, (head_, items) in enumerate(groups):
            xx = x0 + g_ * (cw3 + gut); yy = yl0
            head(xx, yy, cw3, head_); yy += hh
            for n_, name in items:
                if n_ is None:
                    tex.append(self.put_box(xx, yy, cw3, ih, self.inl.run(name, Ctx('M', 1.0)), 'l', 'm'))
                else:
                    ln_ = self.inl.lines(rows_[n_], Ctx('M', 1.0)) if n_ < len(rows_) else []
                    if ln_: tex.append(self.put_box(xx, yy, bw_, ih, self.inl.flat(ln_[0]), 'l', 'm'))
                    tex.append(self.put_box(xx + bw_, yy, cw3 - bw_, ih, self.inl.run(name, Ctx('M', 1.0)), 'l', 'm'))
                yy += ih
        if rects: ops.append(self.pdf_ops(rects))
        return [r'\begin{picture}(%.3f,%.3f)' % (self.W, self.H), r'\put(0,0){\pdfextension literal{%s}}' % ' '.join(ops)] + tex + [r'\end{picture}', r'\newpage']

    def back_page(self, k, x0, recto):
        fs = self.fs
        tex, ops, rects = [], [], []
        H = self.H; y0 = self.mt
        colw, pad, lh = self._ix
        fw, fp = self.frame_w, self.frame_pad
        ix, iy = x0 + fw + fp, y0 + fw + fp
        bp = self.back[k]
        wd = lambda t: self.inl.wc.get(t, 1.0) * fs
        c_ = Ctx('M', 1.0)
        for ci, col in enumerate(bp['cols']):
            xx = ix + ci * colw + pad; ww = colw - 2 * pad
            for li, (kind, nm, ps) in enumerate(col):
                yy = iy + li * lh
                yl = yy + lh / 2
                if kind == 'b': continue
                if kind == 'h':
                    ht = self.inl.run(nm, Ctx('GB', 1.0))
                    tex.append(self.put_box(xx, yy, ww, lh, ht, 'l', 'm'))
                    ym = yy + lh / 2
                    ops.append('q %.3f w 0 G %.3f %.3f m %.3f %.3f l S Q' % (self.rw[1], xx + wd(ht) + 0.5 * fs, H - ym, xx + ww, H - ym))
                    continue
                nt = self.inl.run(nm, c_) if nm else ''
                pt = self.inl.run(ps, c_) if ps else ''
                if nm: tex.append(self.put_box(xx, yy, ww, lh, nt, 'l', 'm'))
                if ps: tex.append(self.put_box(xx, yy, ww, lh, pt, 'r', 'm'))
                if kind == 'e':
                    a_, b_ = xx + wd(nt) + 0.5 * fs, xx + ww - wd(pt) - 0.5 * fs
                    if b_ - a_ > fs: ops.append(self.dots(a_, b_, yl))
        if bp['colophon']:
            colo = self.cfg.get('colophon', [])
            yb = y0 + self.ch - len(colo) * lh
            for i, t in enumerate(colo):
                tex.append(self.put_box(x0, yb + i * lh, self.cw, lh, self.inl.run(t, Ctx('GB' if i == 0 else 'M', 1.0)), 'l', 'm'))
        tex += self.page_side_title(recto, [('', '역명 색인')]) if bp['cols'] else []
        if rects: ops.insert(0, self.pdf_ops(rects))
        return tex, ' '.join(ops)

    def emit(self, out_tex):
        first = self.cfg.get('firstFolio', 2)
        self._tpages = [(p, pc['T']) for p, pg in enumerate(self.pages) for pc in pg['pieces']]
        body = []
        # 여러 쪽에 걸친 노선: 쪽마다 부번 (경부선 (1), (2) …)
        seqno = collections.defaultdict(dict)
        for pi, pg in enumerate(self.pages):
            for k in pg['lines']: seqno[k][pi] = len(seqno[k]) + 1
        if self.cfg.get('titlePage'): body += self.title_page()      # 속표지 (1쪽)
        for pi, pg in enumerate(self.pages):
            folio = first + pi
            recto = folio % 2 == 1
            x0 = self.mi if recto else self.mo
            tex, rects = [], []
            if 'front' in pg or 'back' in pg or 'air' in pg or 'bus' in pg:     # 노선도·색인·범례 / 항공 / 고속버스 / 역명 색인·판권
                t_, lit_ = self.front_page(pg['front'], x0, first) if 'front' in pg else self.air_page(pg['air'], x0, recto) if 'air' in pg \
                    else self.bus_page(pg['bus'], x0, recto) if 'bus' in pg else self.back_page(pg['back'], x0, recto)
                tex += t_
                tex += self.page_furniture(folio, recto, '', '', None)
                body.append(r'\begin{picture}(%.3f,%.3f)' % (self.W, self.H))
                if lit_: body.append(r'\put(0,0){\pdfextension literal{%s}}' % lit_)
                body += tex
                body.append(r'\end{picture}')
                body.append(r'\newpage')
                continue
            for pc in pg['pieces']:
                t, r, w, h = self.render_piece(pc['T'], pc['ch'], pc['rows'], x0 + pc.get('x', 0), self.mt + pc['y'], pc['notes'],
                                               line=pc['T'].line, part=pc['part'], hb=pc['hb'], pc=pc)
                tex += t; rects += r
            # 머리글은 노선 이름만 (책을 넘기며 찾는 자리). 몇째 조각인지는 표의 세로 제목 끝에
            if self.page_title:
                tex += self.page_side_title(recto, pg['lines'], pg.get('dirs'), {k: seqno[k][pi] for k in pg['lines'] if len(seqno[k]) > 1})
                tex += self.page_furniture(folio, recto, '', '', self.page_legend([pc['T'] for pc in pg['pieces']]))
            else:
                tex += self.page_furniture(folio, recto, '·'.join(ln for _, ln in pg['lines']), '')
            body.append(r'\begin{picture}(%.3f,%.3f)' % (self.W, self.H))
            if rects: body.append(r'\put(0,0){\pdfextension literal{%s}}' % self.pdf_ops(rects))
            body += tex
            body.append(r'\end{picture}\newpage')
        body = self.resolve_refs(body)
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
    if cfg.get('busCaps'):                       # 고속버스 노선표: 표마다 한 쪽 폭에 드는 편 수 (routes2.py 가 띠를 나눌 때 앞 띠에 꽉 채우려고)
        caps = {}
        for T in tables:
            if T.line not in cfg.get('otherModes', []) or T.title is None: continue
            tt = re.sub(r'（[^）]*）', '', T.title.text().replace('︱', '―').replace('︵', '（').replace('︶', '）')).strip()
            caps[tt + ('|both' if getattr(T, 'both', False) else '')] = bk.cap(T, 'B', True)
        json.dump(caps, open(os.path.join(base, cfg['busCaps']), 'w'), ensure_ascii=False, indent=0)
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
