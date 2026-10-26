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
import json, math, os, re, subprocess, sys
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
    """빈 열의 칸: 마지막 열차 열의 칸과 같은 괘선, 내용은 없음"""
    def __init__(self, ref):
        self.ref = ref
        self.r, self.c, self.rs, self.cs = ref.r, ref.c, ref.rs, ref.cs
        self.cls = ref.cls - {'jtt-t1'}
        self.style = {k: v for k, v in ref.style.items() if k.startswith('border')}
        self.lines = []

def cell_of(T, r, j):
    if isinstance(j, tuple):
        ref = T.occ.get((r, j[1]))
        if ref is None: return None
        key = (id(ref), j[2])
        g = T.ghosts.get(key)
        if g is None: g = T.ghosts[key] = Ghost(ref)
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

# ───────────────────────── 줄 안 요소 ─────────────────────────
# 줄(line) = 요소 목록. 요소: ('tex', tex, size)  ('just', [tex…], size)  ('obj', tex, w_em, h_em, size)
GOTHIC = {'DG', 'DGB', 'GB', 'G'}
HANGUL_RUN = re.compile('[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]+')

class Inline:
    def __init__(self, fs, hg_up=0.05):
        self.fs = fs          # 기준 글자 크기 (bp)
        self.hg_up = hg_up    # 고딕 한글을 올리는 양 (em)

    def font(self, ctx):
        s = ctx.size * self.fs
        t = r'\f%s\fontsize{%.3fbp}{%.3fbp}\selectfont ' % (ctx.font, s, s * 1.25)
        if ctx.color: t += r'\color[HTML]{%s}' % ctx.color
        return t

    def run(self, s, ctx, vertical=False):
        if not s: return ''
        out = []
        for ch in s:
            if ch == ' ': out.append(r'\ ')
            else: out.append(esc(ch))
        t = ''.join(out)
        # 은돋움의 한글은 숫자·한자보다 낮게 앉는다 → 고딕의 한글만 조금 올린다 (가로쓰기에서만)
        if not vertical and ctx.font in GOTHIC and self.hg_up:
            t = HANGUL_RUN.sub(lambda m: r'\raisebox{%.3fem}{%s}' % (self.hg_up, m.group(0)), t)
        return '{' + self.font(ctx) + t + '}'

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
        tex = r'\ttbadge{%.3f}{%.3f}{%d}{%.3f}{%.3f}{%s}' % (wb, hb, 1 if filled else 0, sx, 0.37 * ctx.size * self.fs, inner)
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

def strut(size, fs):
    s = size * fs
    L = 1.25 * s
    c = 0.37 * s
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
        self.inl = Inline(self.fs, cfg.get('hangulGothicUp', 0.05))
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
    def title_tex(self, T):
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
                if isinstance(k, str): chars(k.replace('\n', ''), font)
                elif 'jtt-dir' in k.cls:
                    down = 'jtt-dir--down' in k.cls
                    hollow = 'jtt-dir--o' in k.cls
                    t = k.text()
                    bs = 0.84 * em
                    bw = bs * (1 + 0.16)
                    bh = bs * (len(t) + 0.36 + 0.6)
                    stack = ''.join(r'\hbox to %.3fbp{\hss\rule[%.3fbp]{0pt}{%.3fbp}%s\hss}' % (bw, -0.12 * bs, bs, self.inl.run(ch, Ctx('GB', size * 0.84, None if hollow else 'FFFFFF'), True)) for ch in t)
                    items.append(r'\hbox to %.3fbp{\hss\ttdir{%.3f}{%.3f}{%d}{%d}{%.3f}{%.3f}{%s}\hss}' % (
                        1.3 * em, bw, bh, 1 if down else 0, 1 if hollow else 0, 0.4 * em, (0.6 if not down else 0.36) * bs, stack))
                    hgt += bh / em + 0.3
                    items.append(r'\kern%.3fbp' % (0.3 * em))
                elif k.cls & {'jtt-sub', 'jtt-box'}: walk(k, 'M')
                else: walk(k, font)
        walk(T.title, 'GB')
        return r'\vbox{\offinterlineskip ' + ''.join(items) + '}', hgt * em, (1.3 + 0.3) * em

    # ── 쪽 나누기: 펼침면 (왼쪽 면 = 제목+역명+열차, 오른쪽 면 = 열차+오른쪽 역명+제목) ──
    def chunks(self, T, fit):
        L = [j for j, k in enumerate(T.kind) if k[0] == 'L']
        Tc = [j for j, k in enumerate(T.kind) if k[0] == 'T']
        Rc = [j for j, k in enumerate(T.kind) if k[0] == 'R']
        if not Rc:            # 오른쪽 역명이 없으면 왼쪽 묶음을 거울처럼
            Rc = [j for j in reversed(L) if T.kind[j][1] in ('st', 'ad')]
            self.mirror = True
        else:
            self.mirror = False
        _, _, TW = self.title_tex(T)
        fw = self.frame_w + self.frame_pad
        Lw = sum(T.colW[j] for j in L)
        Rw = sum(T.colW[j] for j in Rc)
        out = []
        i, k = 0, 0
        while i < len(Tc):
            side = ('L' if k % 2 == 0 else 'R') if fit == 'spread' else 'B'
            if side == 'L': fixed = TW + 2 * fw + Lw
            elif side == 'R': fixed = TW + 2 * fw + Rw
            else: fixed = TW + 2 * fw + Lw + Rw
            cap = max(1, int((self.cw - fixed) // self.P0))
            n = min(cap, len(Tc) - i)
            cols = Tc[i:i + n]
            # 모자란 자리는 빈 열로 판면 끝까지 (JTB 처럼). 남는 폭(열 하나에 못 미치는)은 역명 칸에
            cols = cols + [('G', Tc[-1], g) for g in range(cap - n)]
            extra = self.cw - fixed - cap * self.P0
            if side == 'L': keep = L + cols
            elif side == 'R': keep = cols + Rc
            else: keep = L + cols + Rc
            out.append({'side': side, 'cols': keep, 'trains': cols, 'extra': max(0, extra)})
            i += n; k += 1
        # 마지막 조각이 왼쪽 면이면, 오른쪽 면의 역명 없이 끝나므로 그대로 둔다
        return out

    def bands(self, T):
        """행으로 나누기: 머리 행은 띠마다, 꼬리 행은 마지막 띠에만"""
        head = list(range(T.hEnd))
        foot = list(range(T.fStart, T.nrow))
        body = list(range(T.hEnd, T.fStart))
        hb = self.headband_h(T)
        avail = self.ch - 2 * (self.frame_w + self.frame_pad) - hb - self.notes_h(T)
        Hh = sum(T.rowH[r] for r in head)
        Hf = sum(T.rowH[r] for r in foot)
        out, cur, y = [], [], Hh
        for r in body:
            if y + T.rowH[r] + Hf > avail and cur and y + T.rowH[r] > avail:
                out.append(cur); cur, y = [], Hh
            # 행 묶음(역 하나에 두 줄)을 가르지 않도록: rowspan 이 걸친 행은 함께
            cur.append(r); y += T.rowH[r]
        if cur: out.append(cur)
        return [head + b + (foot if i == len(out) - 1 else []) for i, b in enumerate(out)]

    def headband_h(self, T):
        if T.head is None: return 0
        px = T.head.style.get('height', '')
        m = re.match(r'([\d.]+)px', px)
        em = float(m.group(1)) / 14.4 if m else 1.5
        return math.ceil(em * self.fs / self.R - 0.2) * self.R

    def notes_h(self, T):
        if T.notes is None: return 0
        n = len([k for k in T.notes.kids if isinstance(k, Node)])
        return (n * 1.35 * 0.8 + 0.5) * self.fs

    # ── 표 조각 하나를 쪽에 ──
    def render_piece(self, T, ch, rows, x0, y0, with_notes, notes_room=True):
        """x0,y0: 조각 왼쪽 위 (쪽 좌표, 위에서 아래로). 그릴 것 목록과 크기를 돌려준다"""
        fs = self.fs
        tex, rects = [], []
        side = ch['side']
        ttl, ttlH, TW = self.title_tex(T)
        fw, fp = self.frame_w, self.frame_pad
        # 열 x 위치
        cols = ch['cols']
        widths = [width_of(T, j) for j in cols]
        # 남는 폭을 역명 칸에
        if ch['extra'] > 0:
            tgt = None
            for idx, j in enumerate(cols):
                if kind_of(T, j)[0] in ('L', 'R') and kind_of(T, j)[1] == 'st':
                    tgt = idx
                    if side != 'R': break
            if tgt is not None: widths[tgt] += ch['extra']
        tx = x0 + (TW if side != 'R' else 0)
        fx0 = tx
        xs = [tx + fw + fp]
        for w in widths: xs.append(xs[-1] + w)
        fx1 = xs[-1] + fp + fw
        # 행 y 위치
        hb = self.headband_h(T)
        ty = y0 + fw + fp
        ys = [ty + hb]
        for r in rows: ys.append(ys[-1] + T.rowH[r])
        nh = self.notes_h(T) if with_notes else 0
        fy1 = ys[-1] + nh + fp + fw
        # 틀
        rects += self.frame_rects(fx0, y0, fx1, fy1, fw)
        # 제목
        if side == 'R':
            tex.append(self.put_box(fx1 + 0.3 * fs, y0, TW - 0.3 * fs, ttlH, ttl, 'l', 't'))
        else:
            tex.append(self.put_box(x0, y0, TW - 0.3 * fs, ttlH, ttl, 'l', 't'))
        # 노선 머리띠
        if hb:
            hd = T.head
            parts = [n for n in hd.kids if isinstance(n, Node)]
            color = None
            col = hd.style.get('color')
            if col and col.startswith('#'): color = col[1:].upper()
            if len(color or '') == 3: color = ''.join(c * 2 for c in color)
            for p, al in zip(parts, 'lcr'):
                lines = self.inl.lines(p, Ctx('DM', 1.0, color))
                if not any(lines): continue
                W = xs[-1] - xs[0] - 1.2 * fs
                lt = line_tex(lines[0], W, al, fs, self.inl)
                tex.append(self.put_box(xs[0] + 0.6 * fs, ty, W, hb, lt, al, 'm'))
            rects.append(self.hrule(xs[0], xs[-1], ty + hb, 1))
        # 칸
        rowpos = {r: i for i, r in enumerate(rows)}
        colpos = {j: i for i, j in enumerate(cols)}
        if side == 'R' and self.mirror:
            pass
        seen = set()
        for r in rows:
            for j in cols:
                cell = cell_of(T, r, j)
                if cell is None or id(cell) in seen or isinstance(cell, Ghost): continue
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
        mir = side == 'R' and self.mirror
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
                    if mir and kind_of(T, cols[k])[0] == 'L' and kind_of(T, cols[k - 1])[0] == 'T': w = 2
                    elif mir and kind_of(T, cols[k])[0] == 'L': w = wmax(la, rb)
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

    # ── 머리글·쪽 번호 ──
    def page_furniture(self, folio, recto, runhead, part):
        fs = self.fs
        tex = []
        x0 = self.mi if recto else self.mo
        base_y = self.mt - 3.5 * MM
        Y = self.H - base_y
        rh = self.inl.run(runhead, Ctx('GB', 8.5 / fs))
        if part:
            rh += r'\ {\fM\fontsize{8.5bp}{10bp}\selectfont (%s)}' % esc(part)
        fo = r'{\fGB\fontsize{13bp}{13bp}\selectfont %s}' % folio
        if recto:
            tex.append(r'\put(%.3f,%.3f){\makebox(0,0)[br]{%s}}' % (x0 + self.cw - 12 * MM, Y, rh))
            tex.append(r'\put(%.3f,%.3f){\makebox(0,0)[br]{%s}}' % (x0 + self.cw, Y, fo))
        else:
            tex.append(r'\put(%.3f,%.3f){\makebox(0,0)[bl]{%s}}' % (x0 + 12 * MM, Y, rh))
            tex.append(r'\put(%.3f,%.3f){\makebox(0,0)[bl]{%s}}' % (x0, Y, fo))
        return tex

    # ── 항목 하나(표) ──
    def add_table(self, item):
        src = item['src'] if os.path.isabs(item['src']) else os.path.join(self.base, item['src'])
        text = open(src, encoding='utf-8').read()
        blocks = invoke_blocks(text)
        data = blocks[item.get('idx', 0)]
        mod = os.path.join(HERE, 'src', 'Timetable.lua')
        html = run_module(data, mod, os.path.join(HERE, 'build'))
        root = parse_html(html)
        wrap = root.find(lambda n: 'jtt-wrap' in n.cls)
        T = build_table(wrap)
        self.prepare(T)
        chs = self.chunks(T, item.get('fit', 'spread'))
        bands = self.bands(T)
        # 펼침면: 짝(L,R)마다 띠를 돈다
        groups = [chs[i:i + 2] for i in range(0, len(chs), 2)] if item.get('fit', 'spread') == 'spread' else [[c] for c in chs]
        total = len(chs) * len(bands)
        k = 0
        for gi, grp in enumerate(groups):
            for bi, rows in enumerate(bands):
                for ch in grp:
                    last = gi == len(groups) - 1 and bi == len(bands) - 1 and ch is grp[-1]
                    self.pages.append({'T': T, 'ch': ch, 'rows': rows, 'notes': last,
                                       'label': item.get('label', ''), 'k': k, 'total': total})
                    k += 1

    def emit(self, out_tex):
        first = self.cfg.get('firstFolio', 2)
        body = []
        for pi, pg in enumerate(self.pages):
            folio = first + pi
            recto = folio % 2 == 1
            x0 = self.mi if recto else self.mo
            tex, rects, w, h = self.render_piece(pg['T'], pg['ch'], pg['rows'], x0, self.mt, pg['notes'])
            part = ORD_KO[pg['k']] if pg['total'] > 1 else ''
            tex += self.page_furniture(folio, recto, pg['label'], part)
            body.append(r'\begin{picture}(%.3f,%.3f)' % (self.W, self.H))
            body.append(r'\put(0,0){\pdfextension literal{%s}}' % self.pdf_ops(rects))
            body += tex
            body.append(r'\end{picture}\newpage')
        f = self.cfg.get('fonts', {})
        pre = PREAMBLE % {
            'W': self.W, 'H': self.H,
            'mincho': f.get('mincho', 'Shippori Mincho'), 'minchoKo': f.get('minchoKo', 'UnBatang'),
            'gothic': f.get('gothic', 'Zen Kaku Gothic New'), 'gothicKo': f.get('gothicKo', 'UnDotum'),
            'gothicB': f.get('gothicBold', 'Zen Kaku Gothic New Bold'), 'gothicKoB': f.get('gothicKoBold', 'UnDotum Bold'),
            'dia': f.get('dia', 'DiaPro'),
            'layout': 'TwoPageLeft' if first % 2 == 0 else 'TwoPageRight',
        }
        with open(out_tex, 'w', encoding='utf-8') as fo:
            fo.write(pre + '\n'.join(body) + '\n\\end{document}\n')

ORD_KO = ['첫째', '둘째', '셋째', '넷째', '다섯째', '여섯째', '일곱째', '여덟째', '아홉째', '열째',
          '열한째', '열두째', '열셋째', '열넷째', '열다섯째', '열여섯째']

PREAMBLE = r'''\documentclass{article}
\usepackage[paperwidth=%(W).3fbp,paperheight=%(H).3fbp,margin=0pt]{geometry}
\usepackage{fontspec}
\usepackage{graphicx}
\usepackage[dvipsnames]{xcolor}
\pagestyle{empty}
\setlength{\unitlength}{1bp}
\setlength{\parindent}{0pt}
\directlua{
luaotfload.add_fallback("fbM", {"%(minchoKo)s:mode=node;", "%(dia)s:mode=node;"})
luaotfload.add_fallback("fbDM", {"%(mincho)s:mode=node;", "%(minchoKo)s:mode=node;"})
luaotfload.add_fallback("fbDG", {"%(gothic)s:mode=node;", "%(gothicKo)s:mode=node;"})
luaotfload.add_fallback("fbDGB", {"%(gothicB)s:mode=node;", "%(gothicKoB)s:mode=node;"})
luaotfload.add_fallback("fbGB", {"%(gothicKoB)s:mode=node;", "%(dia)s:mode=node;"})
luaotfload.add_fallback("fbG", {"%(gothicKo)s:mode=node;", "%(dia)s:mode=node;"})
}
\newfontfamily\fM{%(mincho)s}[RawFeature={fallback=fbM}]
\newfontfamily\fDM{%(dia)s}[RawFeature={fallback=fbDM;-liga;-ccmp}]
\newfontfamily\fDG{%(dia)s}[RawFeature={fallback=fbDG;-liga;-ccmp}]
\newfontfamily\fDGB{%(dia)s}[RawFeature={fallback=fbDGB;-liga;-ccmp;+titl}]
\newfontfamily\fGB{%(gothicB)s}[RawFeature={fallback=fbGB}]
\newfontfamily\fG{%(gothic)s}[RawFeature={fallback=fbG}]
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
    for it in cfg['items']:
        if it.get('type', 'table') == 'table': bk.add_table(it)
    out = os.path.join(HERE, 'build', cfg.get('name', 'book') + '.tex')
    bk.emit(out)
    r = subprocess.run(['lualatex', '-interaction=nonstopmode', '-halt-on-error', os.path.basename(out)],
                       cwd=os.path.dirname(out), capture_output=True)
    log = r.stdout.decode('utf-8', 'replace')
    if r.returncode != 0:
        print(log[-3000:]); sys.exit(1)
    miss = set(re.findall(r'Missing character: There is no (.) ', log))
    if miss: print('missing glyphs:', ' '.join(sorted(miss)))
    print('pages:', len(bk.pages), '→', out[:-4] + '.pdf')

if __name__ == '__main__':
    main()
