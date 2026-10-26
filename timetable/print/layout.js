/*
 * 시각표 인쇄 — 쪽 나누기
 *
 * 위키가 그린 시각표(.jtt-wrap)를 그대로 받아, 판형의 판면에 맞춰 자른다.
 *   · 옆으로 넘치면 열차(.jtt-t 열)로 자르고, 역명 등 왼쪽·오른쪽 고정 칸은 쪽마다 되풀이한다.
 *   · 아래로 넘치면 역(행)으로 자르고, 머리 행(.jtt-hr)은 쪽마다 되풀이, 꼬리 행(.jtt-f1 …)은 마지막에만.
 *   · 표마다 '나누기' / '줄여 맞추기' / '펼침면' 을 고른다.
 * 쪽 번호는 표지를 1로 센다. 왼쪽 철이므로 홀수 쪽이 오른쪽(recto), 짝수 쪽이 왼쪽(verso)이다.
 */

export const MM = 96 / 25.4;
export const SIZES = {
  A4: [210, 297], B5: [182, 257], A5: [148, 210], B6: [128, 182],
};

const STR = {
  ko: { toc: '차례', cont: '계속', colophon: '판권', issued: '펴낸 날', publisher: '펴낸 곳', data: '자료',
        rev: '판', fonts: '글꼴', source: '쩌모위키 시각표 (w.halv.kr)' },
  ja: { toc: '目次', cont: 'つづく', colophon: '奥付', issued: '発行日', publisher: '発行', data: '資料',
        rev: '版', fonts: '書体', source: '쩌모위키 時刻表 (w.halv.kr)' },
};

/* ── 표의 격자 ─────────────────────────────────────────────────────── */

/** 표를 격자로: 칸마다 시작 행·열과 걸친 수 */
export function grid(table) {
  const rows = [...table.rows];
  const occ = [];
  const cells = [];
  let ncol = 0;
  rows.forEach((tr, r) => {
    let c = 0;
    for (const td of tr.cells) {
      while (occ[r] && occ[r][c]) c++;
      const cs = Math.max(1, td.colSpan || 1);
      const rs = Math.max(1, td.rowSpan || 1);
      for (let i = 0; i < rs; i++) {
        occ[r + i] ??= [];
        for (let j = 0; j < cs; j++) occ[r + i][c + j] = true;
      }
      cells.push({ td, r, c, cs, rs });
      c += cs;
      ncol = Math.max(ncol, c);
    }
  });
  return { rows, cells, ncol };
}

/** 열차 열의 범위 [t0, t1), 머리 행 끝 hEnd, 꼬리 행 시작 fStart */
function shape(table) {
  const g = grid(table);
  let t0 = Infinity, t1 = -1;
  for (const x of g.cells) {
    if (x.td.classList.contains('jtt-t')) { t0 = Math.min(t0, x.c); t1 = Math.max(t1, x.c + x.cs); }
  }
  if (t1 < 0) { t0 = g.ncol; t1 = g.ncol; }
  let hEnd = 0;
  while (hEnd < g.rows.length && g.rows[hEnd].classList.contains('jtt-hr')) hEnd++;
  // 머리 행에서 아래로 걸친 칸이 있으면 그 끝까지를 머리로
  for (const x of g.cells) if (x.r < hEnd) hEnd = Math.max(hEnd, x.r + x.rs);
  let fStart = g.rows.length;
  for (let r = hEnd; r < g.rows.length; r++) {
    const cl = g.rows[r].classList;
    if (cl.contains('jtt-f1') || cl.contains('jtt-fr')) { fStart = r; break; }
  }
  // 행 사이에서 끊어도 되는 자리: 위아래로 걸친 칸이 없는 곳
  const rowOK = new Array(g.rows.length + 1).fill(true);
  const colOK = new Array(g.ncol + 1).fill(true);
  for (const x of g.cells) {
    for (let i = x.r + 1; i < x.r + x.rs; i++) rowOK[i] = false;
    for (let j = x.c + 1; j < x.c + x.cs; j++) colOK[j] = false;
  }
  return { g, t0, t1, hEnd, fStart, rowOK, colOK };
}

/**
 * 표를 잘라 낸 사본. keepRows[r], keepCols[c] 가 참인 행·열만 남긴다.
 * 걸친 칸은 남는 만큼만 걸치게 줄이고, 첫 행이 잘려 나간 칸은 남는 첫 행으로 옮긴다.
 */
export function clipTable(src, keepRows, keepCols, t0) {
  const t = src.cloneNode(true);
  const g = grid(t);
  const firstCol = keepCols.findIndex(Boolean);
  let firstTrain = -1;
  for (let j = t0; j < keepCols.length; j++) if (keepCols[j]) { firstTrain = j; break; }
  const moves = [];
  const kept = [];
  for (const x of g.cells) {
    let cs = 0, rs = 0, firstRow = -1;
    for (let j = x.c; j < x.c + x.cs; j++) if (keepCols[j]) cs++;
    for (let i = x.r; i < x.r + x.rs; i++) if (keepRows[i]) { rs++; if (firstRow < 0) firstRow = i; }
    if (!cs || !rs) { x.td.remove(); continue; }
    if (cs !== x.cs) x.td.colSpan = cs;
    if (rs !== x.rs) x.td.rowSpan = rs;
    x.td.classList.remove('jtt-t1', 'jtt-c1');
    const covers = (j) => j >= 0 && x.c <= j && j < x.c + x.cs;
    if (covers(firstCol)) x.td.classList.add('jtt-c1');
    if (covers(firstTrain) && x.td.classList.contains('jtt-t')) x.td.classList.add('jtt-t1');
    kept.push(x);
    if (firstRow !== x.r) moves.push({ x, firstRow });
  }
  for (const { x, firstRow } of moves) {
    const tr = g.rows[firstRow];
    const after = kept.find((y) => y.r === firstRow && y.td.parentNode === tr && y.c > x.c);
    tr.insertBefore(x.td, after ? after.td : null);
  }
  g.rows.forEach((tr, i) => { if (!keepRows[i]) tr.remove(); });
  return t;
}

/* ── 재기 ──────────────────────────────────────────────────────────── */

/** 잴 곳: 화면 밖에 판면 폭의 상자를 둔다 */
function measurer(root, g) {
  root.innerHTML = '';
  const box = document.createElement('div');
  box.className = 'm-box';
  box.style.width = `${g.cw}mm`;
  root.appendChild(box);
  return box;
}

function rect(el) { return el.getBoundingClientRect(); }

/** wrap 하나를 재기 상자에 놓고 크기를 잰다 (폭은 내용대로) */
function place(box, el, fs) {
  box.innerHTML = '';
  const holder = document.createElement('div');
  holder.className = 'm-free';
  if (fs) holder.style.setProperty('--bk-fs', `${fs}pt`);
  holder.appendChild(el);
  box.appendChild(holder);
  return holder;
}

/* ── 표를 쪽 조각으로 ──────────────────────────────────────────────── */

/**
 * 표 하나를 조각들로. 조각: { el, w, h, side: 'L'|'R'|null, last: 마지막 가로 조각인가 }
 * opt: { fit: 'split'|'shrink'|'spread', scale, fs, availW, availH, lang }
 */
export async function tableFragments(srcWrap, box, opt) {
  let fs = opt.fs * (opt.scale || 1);
  let holder = place(box, srcWrap.cloneNode(true), fs);
  rect(holder);
  await document.fonts.ready;
  let wrap = holder.firstChild;
  let wr = rect(wrap);
  const contH = 5 * MM;   // '계속' 표시 몫

  if (opt.fit === 'shrink') {
    const s = Math.min(1, opt.availW / wr.width, opt.availH / wr.height);
    if (s < 0.999) {
      fs = Math.max(fs * s, opt.fs * (opt.minScale || 0.7));
      holder = place(box, srcWrap.cloneNode(true), fs);
      await document.fonts.ready;
      wrap = holder.firstChild;
      wr = rect(wrap);
    }
  }
  if (wr.width <= opt.availW + 0.5 && wr.height <= opt.availH + 0.5) {
    return [{ el: wrap, w: wr.width, h: wr.height, side: null, last: true, fs }];
  }

  const table = wrap.querySelector('table.jtt');
  if (!table) return [{ el: wrap, w: wr.width, h: wr.height, side: null, last: true, fs, overflow: true }];
  const S = shape(table);
  const { g, t0, t1, hEnd, fStart } = S;
  const tr = rect(table);
  const titleEl = wrap.querySelector('.jtt-title');
  const titleW = titleEl && getComputedStyle(titleEl).writingMode.startsWith('vertical') ? rect(titleEl).width : 0;
  const notesH = [...wrap.querySelectorAll('.jtt-notes')].reduce((a, n) => a + rect(n).height, 0);
  const extraW = wr.width - tr.width;
  const extraH = wr.height - tr.height - notesH;

  // 열 폭: 한 칸짜리 칸에서 잰다
  const colW = new Array(g.ncol).fill(0);
  for (const x of g.cells) if (x.cs === 1) colW[x.c] = Math.max(colW[x.c], rect(x.td).width);
  for (const x of g.cells) {           // 한 칸짜리가 없는 열은 걸친 칸에서 나눠 채운다
    if (x.cs === 1) continue;
    const known = colW.slice(x.c, x.c + x.cs).reduce((a, b) => a + b, 0);
    const zero = colW.slice(x.c, x.c + x.cs).filter((v) => !v).length;
    if (zero) {
      const rest = Math.max(0, rect(x.td).width - known) / zero;
      for (let j = x.c; j < x.c + x.cs; j++) if (!colW[j]) colW[j] = rest;
    }
  }
  const rowH = g.rows.map((r) => rect(r).height);
  const sum = (arr, a, b) => arr.slice(a, b).reduce((p, q) => p + q, 0);
  const leftW = sum(colW, 0, t0), rightW = sum(colW, t1, g.ncol);
  const headH = sum(rowH, 0, hEnd), footH = sum(rowH, fStart, g.rows.length);

  let safeW = 0, safeH = 0;   // 실제로 놓아 보고 넘치면 늘린다
  for (let attempt = 0; attempt < 6; attempt++) {
    /* 세로 띠: 역(행)으로 자른다 */
    const bands = [];
    let r = hEnd;
    const availH = opt.availH - safeH;
    while (r < fStart) {
      let h = extraH + headH;
      let end = r, lastGood = -1;
      for (let k = r; k < fStart; k++) {
        h += rowH[k];
        const lastBand = k + 1 === fStart;
        const need = h + (lastBand ? footH + notesH : contH);
        if (need > availH && k > r) break;
        end = k + 1;
        if (S.rowOK[end] || end === fStart) lastGood = end;
        if (need > availH) break;
      }
      const cut = end === fStart ? fStart : (lastGood > r ? lastGood : Math.max(end, r + 1));
      bands.push([r, cut]);
      r = cut;
    }
    if (!bands.length) bands.push([hEnd, fStart]);

    /* 가로 조각: 열차(열)로 자른다 */
    const spread = opt.fit === 'spread';
    const chunks = [];
    let c = t0, side = 'L';
    while (c < t1) {
      const withLeft = !spread || side === 'L';
      const withRight = !spread || side === 'R';
      let avail = opt.availW - safeW - (withLeft ? extraW + leftW : extraW - titleW) - (withRight ? rightW : 0);
      let w = 0, end = c, lastGood = -1;
      for (let k = c; k < t1; k++) {
        if (w + colW[k] > avail && k > c) break;
        w += colW[k];
        end = k + 1;
        if (S.colOK[end] || end === t1) lastGood = end;
      }
      const cut = end === t1 ? t1 : (lastGood > c ? lastGood : end);
      chunks.push({ a: c, b: cut, withLeft, withRight, withTitle: withLeft, side: spread ? side : null });
      c = cut;
      side = side === 'L' ? 'R' : 'L';
    }
    if (!chunks.length) chunks.push({ a: t0, b: t1, withLeft: true, withRight: true, withTitle: true, side: null });
    if (spread && chunks.length === 1) chunks[0].side = null;

    /* 조각을 만들어 놓아 보고 잰다 */
    const frags = [];
    let overW = 0, overH = 0;
    bands.forEach(([ra, rb], bi) => {
      const lastBand = bi === bands.length - 1;
      const keepRows = g.rows.map((_, i) => i < hEnd || (i >= ra && i < rb) || (lastBand && i >= fStart));
      chunks.forEach((ch, ci) => {
        const lastChunk = ci === chunks.length - 1;
        const keepCols = new Array(g.ncol).fill(false).map((_, j) =>
          (j < t0 && ch.withLeft) || (j >= ch.a && j < ch.b) || (j >= t1 && ch.withRight));
        const w = srcWrap.cloneNode(true);
        const srcTable = w.querySelector('table.jtt');
        srcTable.replaceWith(clipTable(table, keepRows, keepCols, t0));
        if (!(lastBand && lastChunk)) w.querySelectorAll('.jtt-notes').forEach((n) => n.remove());
        if (!ch.withTitle) w.querySelectorAll('.jtt-title').forEach((n) => n.remove());
        const hold = place(box, w, fs);
        const fr = rect(hold.firstChild);
        overW = Math.max(overW, fr.width - opt.availW);
        const needH = fr.height + (lastBand && lastChunk ? 0 : contH);
        overH = Math.max(overH, needH - opt.availH);
        frags.push({
          el: hold.firstChild, w: fr.width, h: fr.height, side: ch.side, fs,
          last: lastBand && lastChunk,
          cont: !(lastBand && lastChunk) && !(ch.side === 'L' && !lastChunk),
        });
      });
    });
    if (overW <= 0.5 && overH <= 0.5) return frags;
    if (overW > 0.5) safeW += overW + 1;
    if (overH > 0.5) safeH += overH + 1;
    if (attempt === 5) return frags.map((f) => ({ ...f, overflow: true }));
  }
  return [];
}

/* ── 문서에서 표 꺼내기 ────────────────────────────────────────────── */

/** 위키 HTML 에서 표(.jtt-wrap)들을 차례대로. 앞선 제목(h2…h4)과 표 제목을 함께 */
export function extractTables(html) {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const out = [];
  const heads = {};
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_ELEMENT);
  let n;
  while ((n = walker.nextNode())) {
    const tag = n.tagName;
    if (/^H[2-6]$/.test(tag)) {
      const lv = +tag[1];
      heads[lv] = n.textContent.trim();
      for (let k = lv + 1; k <= 6; k++) delete heads[k];
      continue;
    }
    if (n.classList.contains('jtt-wrap') && !n.parentElement.closest('.jtt-wrap')) {
      const dir = n.querySelector('.jtt-dir')?.textContent.trim() || '';
      const titleText = (n.querySelector('.jtt-title')?.textContent || '').replace(/\s+/g, ' ').trim();
      out.push({ idx: out.length, el: n, dir, titleText, heads: Object.keys(heads).sort().map((k) => heads[k]) });
    }
  }
  return out;
}

export const shortTitle = (t) => t.replace(/^[^:]+:/, '').replace(/\//g, ' ');

export function defaultLabel(title, t) {
  const parts = [shortTitle(title)];
  for (const h of t.heads) {
    if (!h || h === t.dir || t.titleText.includes(h) || parts.includes(h)) continue;
    parts.push(h);
  }
  if (t.dir) parts.push(t.dir);
  return parts.join(' ');
}

const langOf = (s) => (/[぀-ヿ]/.test(s) ? 'ja' : /[가-힣]/.test(s) ? 'ko' : 'ja');

/* ── 책 한 권을 쪽들로 ─────────────────────────────────────────────── */

/**
 * book: 설계도, docs: Map('title@oldid' → { title, revid, timestamp, tables: extractTables(...) })
 * out: 쪽들을 넣을 곳, mroot: 재기 상자를 둘 곳
 */
export async function layoutBook(book, docs, out, mroot, onProgress) {
  const P = book.page;
  const [W, H] = P.size === 'custom' ? [P.w, P.h] : SIZES[P.size];
  const g = { W, H, ...P.margin };
  g.cw = W - g.inner - g.outer;
  g.ch = H - g.top - g.bottom;
  const L = STR[book.lang] || STR.ko;
  const box = measurer(mroot, g);
  const availW = g.cw * MM, availH = g.ch * MM;
  const warnings = [];

  /* 0. 글꼴을 미리 다 받아 둔다 (CJK 글꼴은 글자 묶음마다 따로 받으므로, 쓰일 글자를 한 번 그려 본다) */
  box.innerHTML = '';
  for (const it of book.items) {
    if (it.type !== 'table') continue;
    const t = docs.get(`${it.title}@${it.oldid}`)?.tables[it.idx];
    if (t) { const h = document.createElement('div'); h.className = 'm-free'; h.appendChild(t.el.cloneNode(true)); box.appendChild(h); }
  }
  box.insertAdjacentHTML('beforeend', `<div class="m-free">${esc([book.title, book.subtitle, book.publisher, book.date, L.toc].join(' '))}</div>`);
  for (let k = 0; k < 3; k++) { rect(box); await document.fonts.ready; await new Promise(requestAnimationFrame); }

  /* 1. 본문 조각들 */
  const blocks = [];   // { kind, item, frags | html }
  for (let i = 0; i < book.items.length; i++) {
    const it = book.items[i];
    onProgress?.(`${i + 1} / ${book.items.length}`);
    if (it.type === 'table') {
      const d = docs.get(`${it.title}@${it.oldid}`);
      const t = d?.tables[it.idx];
      if (!t) { warnings.push(`표를 찾지 못함: ${it.label || it.title}`); continue; }
      const frags = await tableFragments(t.el, box, {
        fit: it.fit || 'split', scale: (it.scale || 100) / 100, fs: book.fs,
        minScale: 0.7, availW, availH, lang: langOf(t.titleText + it.title),
      });
      if (frags.some((f) => f.overflow)) warnings.push(`판면을 넘침: ${it.label}`);
      blocks.push({ kind: 'table', item: it, frags, lang: langOf(t.titleText + it.title) });
    } else if (it.type === 'divider') {
      blocks.push({ kind: 'divider', item: it });
    } else if (it.type === 'text') {
      blocks.push({ kind: 'text', item: it, pages: await textPages(it.text || '', box, availH) });
    }
  }

  /* 2. 쪽 배치 (차례 쪽 수를 맞출 때까지 되풀이) */
  let tocPages = book.parts.toc ? 1 : 0;
  let pages, tocEntries;
  for (let round = 0; round < 4; round++) {
    pages = [];
    tocEntries = [];
    if (book.parts.cover) pages.push({ kind: 'cover' });
    for (let k = 0; k < tocPages; k++) pages.push({ kind: 'toc', part: k });
    let cur = null;   // 지금 채우는 표 쪽
    for (const b of blocks) {
      if (b.kind === 'divider') {
        cur = null;
        pages.push({ kind: 'divider', item: b.item });
        tocEntries.push({ text: b.item.text || '', page: pages.length, level: 0 });
        continue;
      }
      if (b.kind === 'text') {
        cur = null;
        b.pages.forEach((html, k) => {
          pages.push({ kind: 'text', html, item: b.item });
          if (k === 0 && b.item.toc) tocEntries.push({ text: b.item.toc, page: pages.length, level: 0 });
        });
        continue;
      }
      // 표
      b.frags.forEach((f, k) => {
        const gap = 7 * MM;
        const whole = b.frags.length === 1;
        if (f.side === 'L' && pages.length % 2 === 0) {   // 펼침면 왼쪽은 짝수 쪽에서
          pages.push({ kind: 'blank' });
          cur = null;
        }
        if (whole && book.pack && cur && cur.used + gap + f.h <= availH) {
          cur.frags.push(f);
          cur.used += gap + f.h;
          cur.labels.push(b.item.label);
        } else {
          cur = { kind: 'table', frags: [f], used: f.h + (f.cont ? 5 * MM : 0), labels: [b.item.label], lang: b.lang,
                  runhead: b.item.label, side: f.side };
          pages.push(cur);
        }
        if (k === 0) tocEntries.push({ text: b.item.label, page: pages.length, level: 1 });
        if (!whole) cur = null;   // 나뉜 표가 있는 쪽에는 더 싣지 않는다
      });
    }
    if (book.parts.colophon) {
      const total = pages.length + 1;
      if (book.pad4 && total % 4) for (let k = 0; k < 4 - (total % 4); k++) pages.push({ kind: 'blank' });
      pages.push({ kind: 'colophon' });
    } else if (book.pad4 && pages.length % 4) {
      while (pages.length % 4) pages.push({ kind: 'blank' });
    }
    if (!book.parts.toc) break;
    const need = await tocPageCount(tocEntries, box, availH, L);
    if (need === tocPages) break;
    tocPages = need;
  }

  /* 3. 그리기 */
  out.innerHTML = '';
  const tocChunks = book.parts.toc ? await splitToc(tocEntries, box, availH, L) : [];
  pages.forEach((p, i) => {
    const n = i + 1;
    const recto = n % 2 === 1;
    const sheet = makeSheet(book, g, recto);
    const page = sheet.querySelector('.page');
    const content = page.querySelector('.content');
    let runhead = '', folio = String(n);
    if (p.kind === 'cover') { content.appendChild(cover(book)); folio = ''; page.classList.add('is-cover'); }
    else if (p.kind === 'toc') { content.appendChild(tocChunks[p.part] || document.createElement('div')); runhead = L.toc; }
    else if (p.kind === 'divider') { content.appendChild(divider(p.item)); folio = ''; }
    else if (p.kind === 'text') { const d = document.createElement('div'); d.className = 'textpage'; d.innerHTML = p.html; content.appendChild(d); runhead = p.item.toc || ''; }
    else if (p.kind === 'blank') { folio = ''; }
    else if (p.kind === 'colophon') { content.appendChild(colophon(book, docs, L)); runhead = ''; }
    else if (p.kind === 'table') {
      runhead = p.runhead || '';
      p.frags.forEach((f, k) => {
        const holder = document.createElement('div');
        holder.className = 'frag';
        if (f.side === 'L') holder.classList.add('frag-l');   // 펼침면: 왼쪽 쪽의 표는 제본 쪽(오른쪽)에 붙인다
        holder.style.setProperty('--bk-fs', `${f.fs}pt`);
        if (k) holder.style.marginTop = '7mm';
        holder.appendChild(f.el.cloneNode(true));
        if (f.cont) {
          const c = document.createElement('div');
          c.className = 'cont';
          c.textContent = (STR[p.lang] || L).cont + ' →';
          holder.appendChild(c);
        }
        content.appendChild(holder);
      });
    }
    if (book.parts.runhead && runhead) page.querySelector('.runhead').textContent = runhead;
    if (book.parts.folio && folio) page.querySelector('.folio').textContent = folio;
    out.appendChild(sheet);
  });
  mroot.innerHTML = '';
  return { pages: pages.length, warnings, size: [W, H] };
}

/* ── 쪽 틀 ─────────────────────────────────────────────────────────── */

const CROP = 15;   // 재단선을 둘 바깥 여백(mm)
const BLEED = 3;

function makeSheet(book, g, recto) {
  const marks = book.output?.marks;
  const sw = g.W + (marks ? 2 * CROP : 0), sh = g.H + (marks ? 2 * CROP : 0);
  const sheet = document.createElement('section');
  sheet.className = 'sheet';
  sheet.style.width = `${sw}mm`;
  sheet.style.height = `${sh}mm`;
  const page = document.createElement('div');
  page.className = `page ${recto ? 'recto' : 'verso'}`;
  Object.assign(page.style, {
    left: `${marks ? CROP : 0}mm`, top: `${marks ? CROP : 0}mm`, width: `${g.W}mm`, height: `${g.H}mm`,
  });
  const inL = recto ? g.inner : g.outer;
  const inR = recto ? g.outer : g.inner;
  page.innerHTML = `<div class="runhead" style="left:${inL}mm;right:${inR}mm;bottom:${g.H - g.top + 4}mm"></div>`
    + `<div class="content" style="left:${inL}mm;top:${g.top}mm;width:${g.cw}mm;height:${g.ch}mm"></div>`
    + `<div class="folio" style="left:${inL}mm;right:${inR}mm;top:${g.H - g.bottom + 5}mm"></div>`;
  sheet.appendChild(page);
  if (marks) sheet.insertAdjacentHTML('afterbegin', cropMarks(sw, sh, g.W, g.H));
  return sheet;
}

/** 일본식 재단선(トンボ): 모서리에 재단선·도련선 두 겹, 변 가운데에 십자 */
function cropMarks(sw, sh, W, H) {
  const o = CROP, b = BLEED, L = [];
  const line = (x1, y1, x2, y2) => L.push(`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`);
  for (const [x, sx] of [[o, -1], [o + W, 1]]) {
    for (const [y, sy] of [[o, -1], [o + H, 1]]) {
      // 가로 두 줄 (재단선 높이·도련 높이), 세로 두 줄
      line(x + sx * b, y, x + sx * (o - 1), y);
      line(x, y + sy * b, x + sx * (o - 1), y + sy * b);
      line(x, y + sy * b, x, y + sy * (o - 1));
      line(x + sx * b, y, x + sx * b, y + sy * (o - 1));
    }
  }
  const cx = o + W / 2, cy = o + H / 2;
  for (const y of [o - b - 1, o + H + b + 1]) {
    const yy = y < o ? y - 6 : y + 6;
    line(cx - 8, (y + yy) / 2, cx + 8, (y + yy) / 2);
    line(cx, Math.min(y, yy), cx, Math.max(y, yy));
  }
  for (const x of [o - b - 1, o + W + b + 1]) {
    const xx = x < o ? x - 6 : x + 6;
    line((x + xx) / 2, cy - 8, (x + xx) / 2, cy + 8);
    line(Math.min(x, xx), cy, Math.max(x, xx), cy);
  }
  return `<svg class="marks" viewBox="0 0 ${sw} ${sh}" width="${sw}mm" height="${sh}mm" aria-hidden="true">${L.join('')}</svg>`;
}

/* ── 표지·중표지·글 쪽·차례·판권 ──────────────────────────────────── */

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function cover(book) {
  const d = document.createElement('div');
  d.className = 'cover';
  d.innerHTML = `<div class="cv-top">${esc(book.edition || '')}</div>
    <h1 class="cv-title">${esc(book.title || '')}</h1>
    <div class="cv-sub">${esc(book.subtitle || '')}</div>
    <div class="cv-foot"><div>${esc(book.date || '')}</div><div class="cv-pub">${esc(book.publisher || '')}</div></div>`;
  return d;
}

function divider(it) {
  const d = document.createElement('div');
  d.className = 'divider';
  d.innerHTML = `<div class="dv-title">${esc(it.text || '')}</div>${it.sub ? `<div class="dv-sub">${esc(it.sub)}</div>` : ''}`;
  return d;
}

/** 아주 간단한 글: 빈 줄로 문단, '# ' 제목, '- ' 목록 */
export function mdLite(src) {
  return src.split(/\n{2,}/).map((p) => {
    const t = p.trim();
    if (!t) return '';
    if (/^#\s/.test(t)) return `<h2>${esc(t.replace(/^#\s+/, ''))}</h2>`;
    if (/^-\s/.test(t)) return `<ul>${t.split('\n').map((l) => `<li>${esc(l.replace(/^-\s+/, ''))}</li>`).join('')}</ul>`;
    return `<p>${esc(t).replace(/\n/g, '<br>')}</p>`;
  }).join('');
}

async function textPages(src, box, availH) {
  const html = mdLite(src);
  const tmp = document.createElement('div');
  tmp.className = 'textpage';
  tmp.innerHTML = html;
  const parts = [...tmp.children];
  const pages = [];
  let cur = [];
  box.innerHTML = '';
  const probe = document.createElement('div');
  probe.className = 'textpage';
  box.appendChild(probe);
  await document.fonts.ready;
  for (const el of parts) {
    probe.appendChild(el);
    if (rect(probe).height > availH && cur.length) {
      probe.removeChild(el);
      pages.push(cur.map((e) => e.outerHTML).join(''));
      probe.innerHTML = '';
      probe.appendChild(el);
      cur = [];
    }
    cur.push(el);
  }
  if (cur.length || !pages.length) pages.push(cur.map((e) => e.outerHTML).join(''));
  return pages;
}

function tocRow(e) {
  return `<li class="toc-l${e.level}"><span>${esc(e.text)}</span><i></i><span class="toc-p">${e.page}</span></li>`;
}

async function splitToc(entries, box, availH, L) {
  const pages = [];
  let wrap, ul;
  const start = (first) => {
    wrap = document.createElement('div');
    wrap.className = 'toc';
    if (first) wrap.innerHTML = `<h2 class="toc-h">${esc(L.toc)}</h2>`;
    ul = document.createElement('ul');
    wrap.appendChild(ul);
    box.innerHTML = '';
    box.appendChild(wrap);
  };
  start(true);
  for (const e of entries) {
    ul.insertAdjacentHTML('beforeend', tocRow(e));
    if (rect(wrap).height > availH && ul.children.length > 1) {
      const li = ul.lastElementChild;
      li.remove();
      pages.push(wrap.cloneNode(true));
      start(false);
      ul.appendChild(li);
    }
  }
  pages.push(wrap.cloneNode(true));
  box.innerHTML = '';
  return pages;
}

async function tocPageCount(entries, box, availH, L) {
  return (await splitToc(entries, box, availH, L)).length || 1;
}

function fmtDate(iso, lang) {
  if (!iso) return '';
  const d = new Date(iso);
  return lang === 'ja' ? `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日` : `${d.getFullYear()}. ${d.getMonth() + 1}. ${d.getDate()}.`;
}

function colophon(book, docs, L) {
  const used = [];
  const seen = new Set();
  for (const it of book.items) {
    if (it.type !== 'table') continue;
    const k = `${it.title}@${it.oldid}`;
    if (seen.has(k)) continue;
    seen.add(k);
    const d = docs.get(k);
    used.push(`<li>${esc(shortTitle(it.title))} <span class="cl-rev">${esc(L.rev)} ${it.oldid}${d?.timestamp ? ` · ${fmtDate(d.timestamp, book.lang)}` : ''}</span></li>`);
  }
  const fonts = book.fonts === 'shaken'
    ? 'DiaPro (OFL) · 石井明朝·石井ゴシック (TypeSquare) · 은바탕·은돋움 (GPL)'
    : 'DiaPro (OFL) · Zen Old Mincho·Zen Kaku Gothic New (OFL) · 은바탕·은돋움 (GPL)';
  const d = document.createElement('div');
  d.className = 'colophon';
  d.innerHTML = `<div class="cl-box">
    <div class="cl-title">${esc(book.title || '')}</div>
    ${book.subtitle ? `<div class="cl-sub">${esc(book.subtitle)}</div>` : ''}
    <dl>
      ${book.date ? `<dt>${esc(L.issued)}</dt><dd>${esc(book.date)}</dd>` : ''}
      ${book.publisher ? `<dt>${esc(L.publisher)}</dt><dd>${esc(book.publisher)}</dd>` : ''}
      <dt>${esc(L.data)}</dt><dd>${esc(L.source)}<ul>${used.join('')}</ul></dd>
      <dt>${esc(L.fonts)}</dt><dd>${esc(fonts)}</dd>
    </dl>
    ${book.colophonNote ? `<div class="cl-note">${mdLite(book.colophonNote)}</div>` : ''}
  </div>`;
  return d;
}
