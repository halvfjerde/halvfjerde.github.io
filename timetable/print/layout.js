/*
 * 시각표 인쇄 — 쪽 나누기
 *
 * 위키가 그린 시각표(.jtt-wrap)를 그대로 받아, 판형의 판면에 맞춰 자른다.
 *   · 옆으로 넘치면 열차(.jtt-t 열)로 자르고, 역명 등 왼쪽·오른쪽 고정 칸은 쪽마다 되풀이한다.
 *   · 아래로 넘치면 역(행)으로 자르고, 머리 행(.jtt-hr)은 쪽마다 되풀이, 꼬리 행(.jtt-f1 …)은 마지막에만.
 *   · 표마다 '나누기' / '줄여 맞추기' / '펼침면' 을 고른다.
 * 쪽은 표지를 1로 센다. 왼쪽 철이면 홀수 쪽이 오른쪽 면(recto), 오른쪽 철이면 짝수 쪽이 오른쪽 면이다.
 * 위키 문서에는 없는 것(철하는 쪽, 항목이 시작할 면, 찍히는 쪽 번호)은 설계도에서 정한다.
 */

export const MM = 96 / 25.4;
export const SIZES = {
  A4: [210, 297], B5: [182, 257], A5: [148, 210], B6: [128, 182],
};

const STR = {
  ko: { toc: '차례', cont: '계속', contd: ' (계속)', more: '외', colophon: '판권', issued: '펴낸 날', publisher: '펴낸 곳', data: '자료',
        rev: '판', fonts: '글꼴', source: '쩌모위키 시각표 (w.halv.kr)' },
  ja: { toc: '目次', cont: 'つづく', contd: '（つづき）', more: '他', colophon: '奥付', issued: '発行日', publisher: '発行', data: '資料',
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
  // 끊는 자리의 값: 그 자리를 가로지르는 칸이 많을수록 나쁘다.
  // 역명·거리 같은 왼쪽 칸(着·發 한 쌍 등)을 가르는 것은 아주 나쁘게, 열차 칸의 긴 주기(注記)는 조금 나쁘게 친다.
  const rowCost = new Array(g.rows.length + 1).fill(0);
  const colCost = new Array(g.ncol + 1).fill(0);
  for (const x of g.cells) {
    const fixed = !x.td.classList.contains('jtt-t');
    for (let i = x.r + 1; i < x.r + x.rs; i++) rowCost[i] += fixed ? 100 : 1;
    for (let j = x.c + 1; j < x.c + x.cs; j++) colCost[j] += 1;
  }
  return { g, t0, t1, hEnd, fStart, rowCost, colCost };
}

/**
 * 넣을 수 있는 데까지(maxEnd) 가운데 끊을 자리를 고른다: 뒤쪽 1/4 안에서 값이 가장 싼 곳, 같으면 더 뒤.
 * 그 안에 깨끗한 자리가 없으면 그냥 maxEnd 에서 (걸친 칸은 잘라서 양쪽에 둔다).
 */
function pickBreak(start, maxEnd, last, cost, window) {
  if (maxEnd >= last) return last;
  if (maxEnd <= start) return start + 1;
  const from = Math.max(start + 1, maxEnd - (window ?? Math.max(1, Math.floor((maxEnd - start) / 4))));
  let best = maxEnd;
  for (let k = maxEnd; k >= from; k--) if (cost[k] < cost[best]) best = k;
  return best;
}

/**
 * [start, end) 를 묶음으로 자른 끝자리들. fits(a, b, shrink): 묶음 [a, b) 가 (자리를 shrink 만큼 줄여도) 들어가는가.
 * 먼저 꽉 채워 묶음 수를 정하고, balance 면 묶음 수가 늘지 않는 데까지 자리를 줄여 고르게 나눈다
 * (끝에 자투리 한두 줄만 남는 일이 없게).
 */
function cutsFor(start, end, fits, cost, balance, maxShrink) {
  const greedy = (shrink) => {
    const out = [];
    for (let a = start; a < end;) {
      let b = a + 1;
      while (b < end && fits(a, b + 1, shrink)) b++;
      const cut = pickBreak(a, b, end, cost);
      out.push(cut);
      a = cut;
    }
    return out;
  };
  const base = greedy(0);
  if (!balance || base.length <= 1) return base;
  let lo = 0, hi = maxShrink, best = base;
  for (let it = 0; it < 22; it++) {
    const mid = (lo + hi) / 2;
    const r = greedy(mid);
    if (r.length <= base.length) { best = r; lo = mid; } else hi = mid;
  }
  return best;
}

/**
 * 표를 잘라 낸 사본. keepRows[r], keepCols[c] 가 참인 행·열만 남긴다.
 * 걸친 칸은 남는 만큼만 걸치게 줄이고, 첫 행이 잘려 나간 칸은 남는 첫 행으로 옮긴다.
 */
export function clipTable(src, keepRows, keepCols, t0, g = grid(src)) {
  // 남길 칸만 복제해 새 표를 짓는다 (큰 표를 통째로 복제하지 않는다)
  const t = src.cloneNode(false);
  const body = document.createElement('tbody');
  t.appendChild(body);
  const firstCol = keepCols.findIndex(Boolean);
  let firstTrain = -1;
  for (let j = t0; j < keepCols.length; j++) if (keepCols[j]) { firstTrain = j; break; }
  const byRow = new Map();
  for (const x of g.cells) {
    let cs = 0, rs = 0, firstRow = -1;
    for (let j = x.c; j < x.c + x.cs; j++) if (keepCols[j]) cs++;
    if (!cs) continue;
    for (let i = x.r; i < x.r + x.rs; i++) if (keepRows[i]) { rs++; if (firstRow < 0) firstRow = i; }
    if (!rs) continue;
    const td = x.td.cloneNode(true);
    if (cs !== x.cs) td.colSpan = cs;
    if (rs !== x.rs) td.rowSpan = rs;
    td.classList.remove('jtt-t1', 'jtt-c1');
    const covers = (j) => j >= 0 && x.c <= j && j < x.c + x.cs;
    if (covers(firstCol)) td.classList.add('jtt-c1');
    if (covers(firstTrain) && td.classList.contains('jtt-t')) td.classList.add('jtt-t1');
    if (!byRow.has(firstRow)) byRow.set(firstRow, []);
    byRow.get(firstRow).push({ c: x.c, td });
  }
  g.rows.forEach((tr, i) => {
    if (!keepRows[i]) return;
    const nr = tr.cloneNode(false);
    for (const { td } of (byRow.get(i) || []).sort((a, b) => a.c - b.c)) nr.appendChild(td);
    body.appendChild(nr);
  });
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

/* ── 격자 (升目) ───────────────────────────────────────────────────── */
/*
 * 실제 시각표처럼 책 전체가 한 격자를 쓴다: 열 폭 P, 행 높이 R.
 *   · 판면 폭 = N×P. 열차 열은 P 의 배수, 왼쪽(역명 등)·오른쪽 고정 칸 묶음도 P 의 배수가 되게 역명 칸을 늘린다.
 *     → 세로 괘선이 모두 격자 위에 온다.
 *   · 행은 R 의 배수. 한 줄짜리 행은 굵은 줄(二重線 등)이 있어도 줄 간격을 좁혀 R 에 맞춘다.
 *   · 단(段)은 R 의 배수 높이에서 시작하고, 단의 남는 폭은 괘선만 있는 빈 열로 채운다 (쪽에 놓을 때).
 * 판면 폭이 P 의 정수배이고 위 여백이 앞뒤 쪽에서 같으므로, 종이가 비쳐도 앞뒤 괘선이 겹친다.
 */

/** 행 높이를 R 의 배수로: 행의 아래 괘선이 조각 윗변에서 T0 + R 의 배수 거리에 오게 */
function snapRows(el, tb, R, T0) {
  const rows = [...tb.rows];
  if (!rows.length) return;
  const top0 = rect(tb).top - rect(el).top;
  const nat = rows.map((r) => rect(r).height);
  const TOL = 4.5;   // 한 줄짜리로 보아 R 로 줄이는 한도 (이중선 3px 등)
  const set = [];
  let y = top0;
  rows.forEach((tr, i) => {
    const h = nat[i];
    let end = Math.ceil((y + h - T0 - (h <= R + TOL ? TOL : 0.5)) / R - 1e-6) * R + T0;
    if (end - y < R * 0.5) end += R;
    const nh = end - y;
    tr.style.height = `${nh}px`;
    if (nh < h - 0.01) {
      for (const td of tr.cells) {
        if (td.rowSpan !== 1) continue;
        const lh = parseFloat(getComputedStyle(td).lineHeight);
        if (lh) td.style.lineHeight = `${Math.max(1, lh - (h - nh))}px`;
      }
    }
    set.push(nh);
    y = end;
  });
  // 줄여도 줄지 않은 행(큰 상자가 든 칸 등)은 다음 격자까지 늘린다
  const got = rows.map((r) => rect(r).height);
  y = top0;
  rows.forEach((tr, i) => {
    let h = set[i];
    if (got[i] > h + 0.3) {
      h = Math.ceil((y + got[i] - 0.3 - T0) / R - 1e-6) * R + T0 - y;
      tr.style.height = `${h}px`;
    }
    y += h;
  });
}

/**
 * 열 폭을 격자에 맞춘다. cols: 잘린 표의 열마다 { nat, gw, kind: 'L'|'T'|'R', st }.
 * 왼쪽 묶음(표 제목·틀 포함)과 오른쪽 묶음(틀 포함)은 P 의 배수로 늘려 남는 폭을 역명 칸에 준다.
 * 묶음이 없으면 맞닿은 열차 열이 틀 몫을 떠안는다.
 */
function snapCols(el, tb, cols, P) {
  const er = rect(el), tr = rect(tb);
  const frame = tb.closest('.jtt-frame');
  const fr = rect(frame), fcs = getComputedStyle(frame);
  const ttl = el.querySelector('.jtt-title');
  // 표 오른쪽 몫: 틀의 테두리·안쪽 여백 (+ 오른쪽에 붙은 표 제목)
  const offL = tr.left - er.left;
  const offR = parseFloat(fcs.borderRightWidth) + parseFloat(fcs.paddingRight)
    + (ttl && rect(ttl).left >= fr.right - 0.5 ? rect(ttl).right - fr.right : 0);
  const w = cols.map((c) => (c.kind === 'T' ? c.gw : c.nat));
  const idx = (k) => cols.map((c, i) => (c.kind === k ? i : -1)).filter((i) => i >= 0);
  const L = idx('L'), T = idx('T'), Rr = idx('R');
  const up = (v) => Math.ceil(v / P - 1e-3) * P;
  const widen = (ids, off) => {
    const e = off + ids.reduce((a, i) => a + w[i], 0);
    const st = ids.find((i) => cols[i].st) ?? ids.reduce((a, i) => (w[i] > w[a] ? i : a), ids[0]);
    w[st] += up(e) - e;
  };
  if (L.length) widen(L, offL);
  else if (T.length) { w[T[0]] -= offL; if (w[T[0]] < P * 0.5) w[T[0]] += P; }
  let absorbRight = 0;
  if (Rr.length) widen(Rr, offR);
  else if (T.length) { w[T[T.length - 1]] -= offR; absorbRight = offR; }
  tb.querySelector('colgroup')?.remove();
  const cg = document.createElement('colgroup');
  for (const v of w) { const c = document.createElement('col'); c.style.width = `${v}px`; cg.appendChild(c); }
  tb.insertBefore(cg, tb.firstChild);
  tb.style.tableLayout = 'fixed';
  const tw = w.reduce((a, b) => a + b, 0);
  tb.style.width = `${tw}px`;
  const gi = { P, absorbRight };
  // 표 머리글·주기(注記)처럼 표보다 넓은 것이 틀에 있으면 빈 열로 채워 표가 틀을 꽉 채우게 한다
  const short = er.width - (offL + tw + offR);
  if (short > 0.5 && T.length) padTable(el, Math.ceil(short / P - 1e-3), gi);
  return gi;
}

/** 같은 행들로 된 조각들의 행 높이를 가장 높은 것에 맞춘다 */
function equalizeRows(built) {
  const n = Math.min(...built.map((b) => b.rowH.length));
  for (let i = 0; i < n; i++) {
    const mx = Math.max(...built.map((b) => b.rowH[i]));
    for (const b of built) {
      if (b.rowH[i] >= mx - 0.2) continue;
      b.el.querySelector('table.jtt').rows[i].style.height = `${mx}px`;
      b.h += mx - b.rowH[i];
      b.tableH += mx - b.rowH[i];
      b.rowH[i] = mx;
    }
  }
}

/**
 * 왼쪽 묶음(앞 nL 열)을 행 끝으로 거울처럼 옮긴다: [역 칸 | 열차] → [열차 | 역 칸(거꾸로)].
 * 행마다 묶음 안의 칸 차례를 뒤집어 끝에 붙이면, 위에서 내려온 칸(rowspan)의 자리도 거울로 맞는다.
 */
function mirrorBlock(tb, nL) {
  if (!nL) return;
  const g = grid(tb);
  const rows = new Map();
  for (const x of g.cells) {
    if (x.c + x.cs > nL) continue;
    if (!rows.has(x.r)) rows.set(x.r, []);
    rows.get(x.r).push(x);
  }
  for (const [r, xs] of rows) {
    for (const x of xs.slice().reverse()) {
      x.td.classList.remove('jtt-c1');
      x.td.classList.add('jtt-mir');
      if (x.c + x.cs === nL) x.td.classList.add('jtt-mir1');   // 열차 열과 맞닿는 칸
      g.rows[r].appendChild(x.td);
    }
  }
  tb.classList.add('jtt-mirror');
}

/** 쪽에 놓을 때 남는 폭을 빈 열 k 개로 채운다 (열차 열 끝, 오른쪽 묶음 앞에) */
function padTable(wrapEl, k, gi) {
  const tb = wrapEl.querySelector('table.jtt');
  const cg = tb?.querySelector('colgroup');
  if (!tb || !cg || k < 1) return;
  const { g, t1: b } = shape(tb);
  const cols = [...cg.children];
  const add = [];
  for (let i = 0; i < k; i++) { const c = document.createElement('col'); c.style.width = `${gi.P}px`; add.push(c); }
  add.forEach((c) => cg.insertBefore(c, cols[b] || null));
  if (gi.absorbRight && cols[b - 1]) {   // 틀 몫을 마지막 빈 열로 옮긴다
    cols[b - 1].style.width = `${parseFloat(cols[b - 1].style.width) + gi.absorbRight}px`;
    add[k - 1].style.width = `${gi.P - gi.absorbRight}px`;
  }
  tb.style.width = `${parseFloat(tb.style.width) + k * gi.P}px`;
  const n = g.rows.length;
  const covered = new Array(n).fill(false);    // 열차 열과 오른쪽 묶음에 걸친 칸이 있는 행: 그 칸을 넓힌다
  const fromAbove = new Array(n).fill(false);  // 오른쪽 묶음 첫 열이 위 행에서 내려온 칸으로 차 있는 행
  for (const x of g.cells) {
    if (x.c < b && x.c + x.cs > b) { x.td.colSpan = x.cs + k; for (let i = x.r; i < x.r + x.rs; i++) covered[i] = true; }
    else if (x.c === b) for (let i = x.r + 1; i < x.r + x.rs; i++) fromAbove[i] = true;
  }
  for (let r = 0; r < n; r++) {
    if (covered[r]) continue;
    let span = 1;
    while (r + span < n && fromAbove[r + span] && !covered[r + span]) span++;
    const after = g.cells.find((x) => x.r === r && x.c >= b);
    for (let i = 0; i < k; i++) {
      const td = document.createElement('td');
      td.className = 'jtt-t jtt-pad';
      if (span > 1) td.rowSpan = span;
      g.rows[r].insertBefore(td, after ? after.td : null);
    }
    r += span - 1;
  }
}

/* ── 표를 쪽 조각으로 ──────────────────────────────────────────────── */

/**
 * 표 하나를 조각들로. 조각: { el, w, h, side: 'L'|'R'|null, last: 마지막 가로 조각인가 }
 * opt: { fit: 'split'|'shrink'|'spread', scale, fs, availW, availH, grid, fill, startY, tierH, firstW, firstH, … }
 */
export async function tableFragments(srcWrap, box, opt, pre) {
  const plan = await planTable(srcWrap, box, opt, pre);
  if (!plan || Array.isArray(plan)) return plan;
  return plan.cut(opt.startY || 0, opt.tierH || 0);
}

/**
 * 표 하나를 그려 놓고 잴 것을 다 잰다 (판형과 상관없는 것만: 열 폭, 행, 긴 주기 칸, 표 제목, 줄 높이).
 * 같은 표·같은 글자 크기면 다시 잴 필요가 없으므로 layoutBook 이 붙잡아 둔다.
 */
export async function measureTable(srcWrap, box, fs) {
  const holder = place(box, srcWrap.cloneNode(true), fs);
  rect(holder);
  await document.fonts.ready;
  const wrap = holder.firstChild;
  const wr = rect(wrap);
  const table = wrap.querySelector('table.jtt');
  const M = { fs, wrap, wr: { width: wr.width, height: wr.height }, table };
  if (!table) return M;
  const S = shape(table);
  const { g, t0, t1, hEnd } = S;
  const tr = rect(table);
  const titleEl = wrap.querySelector('.jtt-title');
  const vertical = titleEl && getComputedStyle(titleEl).writingMode.startsWith('vertical');
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
  // 열차 칸의 긴 세로 주기처럼 걸친 행을 내용으로 다 쓰는 칸은, 가르면 남은 행들이 늘어난다 → 고정 칸처럼 가르지 않는다
  // 또 잘린 조각의 높이를 미리 셈할 수 있게, 여러 행에 걸친 열차 칸의 내용 높이를 적어 둔다
  const tallCells = [];
  for (const x of g.cells) {
    if (x.rs < 2 || !x.td.classList.contains('jtt-t')) continue;
    // 내용 전체(글자·괄호·<br>로 쌓인 줄)의 높이: 칸 안 내용을 감싸는 범위의 높이
    const rg = document.createRange();
    rg.selectNodeContents(x.td);
    const need = x.td.childNodes.length ? rg.getBoundingClientRect().height : 0;
    if (need > rect(x.td).height * 0.5) for (let i = x.r + 1; i < x.r + x.rs; i++) S.rowCost[i] += 99;
    if (need > 0 && x.r >= hEnd) tallCells.push({ r0: x.r, r1: x.r + x.rs, c0: x.c, c1: x.c + x.cs, need: need + 2 });
  }
  const td = table.querySelector('td');
  const fcs = getComputedStyle(table.closest('.jtt-frame') || table);
  // 격자를 정할 때 쓰는 열차 열 폭 (첫 열차 열은 왼쪽 줄이 없어 1px 좁으므로 뺀다)
  const trainW = [];
  for (let j = t0 + 1; j < t1; j++) if (colW[j]) trainW.push(colW[j]);
  Object.assign(M, {
    S, colW, tallCells, trainW,
    trL: tr.left - wr.left, trR: wr.right - tr.right, tableW: tr.width,
    titleW: vertical ? rect(titleEl).width : 0,
    titleH0: titleEl ? rect(titleEl).height : 0,
    titleFont: titleEl ? parseFloat(getComputedStyle(titleEl).fontSize) : 0,
    lh: td ? parseFloat(getComputedStyle(td).lineHeight) : 0,
    T0: (parseFloat(fcs.borderTopWidth) + parseFloat(fcs.paddingTop)) || 0,
    hasNotes: !!wrap.querySelector('.jtt-notes'),
  });
  return M;
}

/** 실린 표들의 잰 값으로 책의 격자를 정한다 (열차 열 폭은 9할이 들어가는 폭) */
function gridFromMeasures(measures, availW, fsPt) {
  const ws = [];
  let lh = 0, T0 = 0;
  for (const M of measures) {
    if (!M?.table) continue;
    ws.push(...M.trainW);
    if (!lh && M.lh) { lh = M.lh; T0 = M.T0; }
  }
  if (!ws.length) return null;
  ws.sort((a, b) => a - b);
  const pNat = ws[Math.min(ws.length - 1, Math.floor(ws.length * 0.9))];
  const N = Math.max(4, Math.floor(availW / (pNat * 0.97)));   // 3% 까지는 좁혀도 글자가 들어간다
  lh ||= fsPt * 1.25 * 96 / 72;
  return { P: availW / N, N, R: Math.ceil(lh * 8) / 8, T0 };   // R: 한 줄 높이. 괘선이 든 행은 줄 간격을 좁혀 맞춘다
}

/**
 * 표를 재고 가로 조각(열차 묶음)까지 정해 둔다. 세로 띠는 cut(startY, tierH) 로 — 쪽의 어디서 시작하느냐에 따라 다르므로.
 * 돌려주는 것: 조각 배열(나눌 것 없음) | null(이어 싣기 불가) | { cut, hChunks, spread, w0 }
 * M: measureTable 의 결과. 글자 크기가 같으면 다시 재지 않고 쓴다
 */
export async function planTable(srcWrap, box, opt, M) {
  const hasTrains = !!srcWrap.querySelector('table.jtt td.jtt-t');
  const G = opt.grid && hasTrains ? opt.grid : null;   // 격자를 쓰면 글자 크기는 책 전체가 같다
  let fs = opt.fs * (G ? 1 : (opt.scale || 1));
  if (!M || M.fs !== fs) M = await measureTable(srcWrap, box, fs);
  let wrap = M.wrap;
  let wr = M.wr;
  const contH = opt.contH ?? (G ? Math.ceil(5 * MM / G.R) * G.R : 5 * MM);   // '계속' 표시 몫
  const RR = opt.grid?.R;
  const snapY = (v) => (RR ? Math.ceil(v / RR - 1e-3) * RR : v);
  const gapY = opt.gapY ?? 0;

  if (!G && opt.fit === 'shrink') {
    const s = Math.min(1, opt.availW / wr.width, opt.availH / wr.height);
    if (s < 0.999) {
      fs = Math.max(fs * s, opt.fs * (opt.minScale || 0.7));
      M = await measureTable(srcWrap, box, fs);
      wrap = M.wrap;
      wr = M.wr;
    }
  }
  if (!G && wr.width <= opt.availW + 0.5 && wr.height <= opt.availH + 0.5) {
    return [{ el: wrap, w: wr.width, h: wr.height, side: null, last: true, fs }];
  }

  const table = M.table;
  if (!table) return [{ el: wrap, w: wr.width, h: wr.height, side: null, last: true, fs, overflow: true }];
  const { S, colW, tallCells, titleW, titleH0 } = M;
  const { g, t0, t1, hEnd, fStart } = S;
  const nrow = g.rows.length;
  const extraW = wr.width - M.tableW;
  const sum = (arr, a, b) => arr.slice(a, b).reduce((p, q) => p + q, 0);
  const leftW = sum(colW, 0, t0), rightW = sum(colW, t1, g.ncol);
  // 격자: 열차 열은 P 의 배수로
  const gw = colW.map((v, j) => (G && j >= t0 && j < t1 ? Math.max(1, Math.ceil(v / G.P - 0.1)) * G.P : v));
  const isSt = new Array(g.ncol).fill(false);
  for (const x of g.cells) if (x.cs === 1 && (x.td.classList.contains('jtt-st') || x.td.classList.contains('jtt-r-st'))) isSt[x.c] = true;
  // 오른쪽 고정 칸이 없는 표를 펼침면에 실으면, 오른쪽 면의 바깥 끝에 역 이름 칸(역명·着発)을 거울처럼 단다
  const isAd = new Array(g.ncol).fill(false);
  for (const x of g.cells) if (x.cs === 1 && x.td.classList.contains('jtt-ad')) isAd[x.c] = true;
  let mirCols = [];
  for (let j = 0; j < t0; j++) if (isSt[j] || isAd[j]) mirCols.push(j);
  if (!mirCols.length) mirCols = Array.from({ length: t0 }, (_, j) => j);
  const mirW = mirCols.reduce((a, j) => a + colW[j], 0);
  // 잘린 표의 열 차례대로 (거울이면 열차 열 다음에 왼쪽 묶음을 거꾸로, 오른쪽 묶음으로 친다)
  const colInfo = (keepCols, mirror) => {
    const cols = keepCols.map((k, j) => (k ? { nat: colW[j], gw: gw[j], kind: j < t0 ? 'L' : j < t1 ? 'T' : 'R', st: isSt[j] } : null)).filter(Boolean);
    if (!mirror) return cols;
    const nL = cols.filter((c) => c.kind === 'L').length;
    return [...cols.slice(nL), ...cols.slice(0, nL).reverse().map((c) => ({ ...c, kind: 'R' }))];
  };

  // 조각의 껍데기(제목·틀·주기): 표 자리만 비워 두고 한 번만 복제해 둔다
  const shell = srcWrap.cloneNode(true);
  { const ph = document.createElement('table'); ph.className = 'jtt-ph'; shell.querySelector('table.jtt').replaceWith(ph); }

  /** 잘라 낸 조각을 놓아 보고, 지워지기 전에 크기를 다 재 둔다 */
  const build = (keepRows, keepCols, { notes, title, mirror }) => {
    const w = shell.cloneNode(true);
    const clipped = clipTable(table, keepRows, keepCols, t0, g);
    if (mirror) mirrorBlock(clipped, keepCols.slice(0, t0).filter(Boolean).length);
    w.querySelector('table.jtt-ph').replaceWith(clipped);
    if (!notes) w.querySelectorAll('.jtt-notes').forEach((n) => n.remove());
    if (!title) w.querySelectorAll('.jtt-title').forEach((n) => n.remove());
    const el = place(box, w, fs).firstChild;
    const tb = el.querySelector('table.jtt');
    if (G) snapRows(el, tb, G.R, G.T0);
    // 세로쓰기 표 제목이 잘린 표보다 길면 표 높이에서 줄을 바꾼다 (제목 때문에 조각이 길어지지 않게)
    const ttl = el.querySelector('.jtt-title');
    const frame = el.querySelector('.jtt-frame');
    if (ttl && frame && titleW) {
      const fh = rect(frame).height;
      const natH = rect(ttl).height;
      if (natH > fh + 0.5) {
        ttl.style.height = `${fh}px`;
        ttl.style.whiteSpace = 'normal';
        // 미리 비워 둔 줄 수(titleLine)를 넘게 꺾여야 하면 글자를 줄인다 (조각이 판면보다 넓어지지 않게)
        const lines = titleLine ? 2 : 1;
        if (natH > fh * lines) ttl.style.fontSize = `${parseFloat(getComputedStyle(ttl).fontSize) * (fh * lines / natH) * 0.96}px`;
      }
    }
    const gi = G ? snapCols(el, tb, colInfo(keepCols, mirror), G.P) : null;
    const er = rect(el);
    return {
      el, w: er.width, h: er.height, tableH: rect(tb).height, grid: gi,
      rowH: [...tb.rows].map((r) => rect(r).height),
      notesH: [...el.querySelectorAll('.jtt-notes')].reduce((a, n) => a + rect(n).height, 0),
    };
  };
  const allRows = new Array(nrow).fill(true);

  /* 1. 가로 조각: 열차(열)로 자른다. 펼침면이면 왼쪽(L)·오른쪽(R) 쪽을 번갈아 */
  const spread = opt.fit === 'spread' && wr.width > opt.availW + 0.5;
  // 제목이 판면 높이보다 길면 조각마다 한 줄 더 꺾일 수 있으니 그만큼 비워 둔다
  const titleLine = titleW && titleH0 > opt.availH * (opt.fill ? 0.3 : 0.6) ? M.titleFont * 1.4 : 0;
  const gUp = (v) => Math.ceil(v / G.P - 1e-3) * G.P;
  // 가로 조각 i 의 판면 폭: 앞 표가 남긴 단의 오른쪽에 이어 실을 때(opt.firstW)는 첫 조각만 그 폭
  const wAt = (i) => (i === 0 && opt.firstW ? opt.firstW : opt.availW);
  const availFor = G
    ? (side, i) => wAt(i) - (side !== 'R' ? gUp(M.trL + leftW + titleLine) : 0)
      - (side !== 'L' && (t1 < g.ncol || side === 'R') ? gUp(M.trR + (t1 < g.ncol ? rightW : mirW)) : 0)
    : (side, i) => wAt(i) - (side !== 'R' ? extraW + leftW + titleLine : extraW - titleW)
      - (side !== 'L' ? (t1 < g.ncol ? rightW : side === 'R' ? mirW : 0) : 0);
  const sideOf = (i) => (spread ? (i % 2 ? 'R' : 'L') : null);
  const colSum = (a, b) => sum(G ? gw : colW, a, b);
  const slack = G ? -0.5 : 2;
  const greedyCols = (start, idx) => {
    const out = [];
    for (let a = start, k = idx; a < t1; k++) {
      const av = availFor(sideOf(k), k);
      let b = a + 1;
      while (b < t1 && colSum(a, b + 1) <= av - slack) b++;
      const cut = pickBreak(a, b, t1, S.colCost);
      out.push(cut);
      a = cut;
    }
    return out;
  };
  // 펼침면이 아니면 열차 수를 고르게 나눈다 (17+2 보다 10+9).
  // 격자에서는 실제 시각표처럼 쪽을 꽉 채우고, 남은 좁은 조각은 다른 조각과 한 쪽에 나란히 놓는다.
  let plan = spread || opt.firstW ? greedyCols(t0, 0)
    : cutsFor(t0, t1, (a, b, sh) => colSum(a, b) <= availFor(null, 1) - slack - sh, S.colCost, !G, opt.availW * 0.9);
  const chunks = [];
  for (let c = t0, i = 0, pi = 0; c < t1; i++, pi++) {
    const side = sideOf(i);
    const withLeft = side !== 'R', withRight = side !== 'L';
    const mirror = side === 'R' && t1 >= g.ncol;
    const planned = plan[pi] ?? t1;
    let cut = planned, keepCols, tall;
    for (;;) {   // 실제로 놓아 보고 폭이 넘치면 한 열씩 줄인다
      const cc = cut, cs = c;
      keepCols = Array.from({ length: g.ncol }, (_, j) => (j < t0 && (withLeft || (mirror && mirCols.includes(j)))) || (j >= cs && j < cc) || (j >= t1 && withRight));
      tall = build(allRows, keepCols, { notes: false, title: withLeft, mirror });
      if (tall.w <= wAt(i) + 0.5 || cut <= c + 1) break;
      cut--;
    }
    chunks.push({ keepCols, tall, withLeft, side, mirror, overW: tall.w > wAt(i) + 0.5 });
    c = cut;
    if (cut !== planned) { plan = greedyCols(c, i + 1); pi = -1; }
  }
  if (opt.firstW) {   // 이어 싣기는 첫 조각에 열차가 둘 이상 들고 남은 높이에 한 띠로 들어갈 때만
    const c0 = chunks[0];
    const n0 = c0.keepCols.slice(t0, t1).filter(Boolean).length;
    if (chunks.length < 2 || n0 < 2 || c0.overW || c0.tall.h + contH > opt.firstH) return null;
  }

  /* 2. 세로 띠: 역(행)으로 자른다.
        보통은 가로 조각마다 따로 자르고 고르게 나눈다 (한 무리의 열차를 끝 역까지 → 다음 무리).
        '구간 맞추기'면 모든 조각을 같은 역에서 끊고, 구간 차례로 늘어놓는다. 펼침면은 짝끼리 맞춘다. */
  const groups = [];
  if (opt.align) groups.push(chunks);
  else for (let i = 0; i < chunks.length; i += spread ? 2 : 1) groups.push(chunks.slice(i, i + (spread ? 2 : 1)));
  const lastNotesH = notesHeight();
  // 쪽 꽉 채우기(JTB식): 띠를 고르게 나누지 않고, 쪽에 남은 높이만큼 흘려 넣는다.
  // y 는 다음 띠가 놓일 높이 (쪽에 놓는 쪽과 같은 셈법: 단 높이는 R 의 배수, 단 사이 gapY)
  const fillMode = opt.fill && !opt.align;
  const cut = (startY, tierH0) => {
  const frags = [];
  let y = startY || 0;
  groups.forEach((grp, gi) => {
    const lastGroup = gi === groups.length - 1;
    const rowH = Array.from({ length: nrow }, (_, i) => Math.max(...grp.map((ch) => ch.tall.rowH[i] || 0)));
    const extraH = Math.max(...grp.map((ch) => ch.tall.h - ch.tall.tableH));
    const headH = sum(rowH, 0, hEnd), footH = sum(rowH, fStart, nrow);
    const notesH = lastGroup ? lastNotesH : 0;
    // 띠 [a, b) 의 행 높이 합. 띠 끝에서 잘리는 긴 주기 칸은 남은 행에 내용을 다 담아야 하므로 그만큼 늘려 셈한다
    const gCells = tallCells.filter((tc) => grp.some((ch) => ch.keepCols.slice(tc.c0, tc.c1).some(Boolean)));
    const rowSum = (a, b) => {
      let base = sum(rowH, a, b), defic = 0;
      for (const tc of gCells) {
        if (tc.r1 <= a || tc.r0 >= b || (tc.r0 >= a && tc.r1 <= b)) continue;
        defic = Math.max(defic, tc.need - sum(rowH, Math.max(a, tc.r0), Math.min(b, tc.r1)));
      }
      return base + defic;
    };
    const bandOf = (r, cut) => {
      const lastBand = cut >= fStart;
      const keepRows = Array.from({ length: nrow }, (_, i) => i < hEnd || (i >= r && i < cut) || (lastBand && i >= fStart));
      const built = grp.map((ch, k) => build(keepRows, ch.keepCols, { notes: lastGroup && lastBand && k === grp.length - 1, title: ch.withLeft, mirror: ch.mirror }));
      if (built.length > 1) equalizeRows(built);   // 펼침면(과 구간 맞추기)의 조각들은 행 높이를 같게: 왼쪽·오른쪽 면의 줄이 맞는다
      return built;
    };
    const over = (built, cut) => Math.max(...built.map((b) => b.h + (lastGroup && cut >= fStart ? 0 : contH) - opt.availH));

    // 잰 높이와 실제 높이는 다를 수 있다 (잘린 주기 칸이 행을 늘이는 등). 넘치면 여유(margin)를 늘려 처음부터 다시 나눈다.
    // 마지막 시도에서만 띠 하나를 줄여 맞춘다 (끝에 자투리가 생길 수 있다).
    let bands = null;
    if (fillMode) {
      bands = [];
      const tail = (b) => (b >= fStart ? footH + notesH : contH);
      const needOf = (bl, c) => snapY(Math.max(...bl.map((x) => x.h)) + (lastGroup && c >= fStart ? 0 : contH));
      for (let r = hEnd, guard = 0; guard < 500; guard++) {
        if (spread) y = 0;   // 펼침면 조각은 저마다 한 쪽
        // 쪽 밑에 머리만 크고 역은 몇 개 없는 띠는 만들지 않는다: 역 다섯 개 이상, 머리 높이의 3/4 이상
        let minEnd = Math.min(fStart, r + 5);
        while (minEnd < fStart && rowSum(r, minEnd) < headH * 0.75) minEnd++;
        const titleNeed = titleW ? titleH0 / (titleLine ? 2 : 1) - (extraH - 8) : 0;   // 표 제목이 두 줄 안에 들 높이
        if (y > 0 && snapY(Math.max(extraH + headH + rowSum(r, minEnd) + tail(minEnd), titleNeed)) > opt.availH - y + 0.5) y = 0;
        const room = opt.availH - y;
        let cut = fStart;
        if (hEnd < fStart) {
          let b = r + 1;
          while (b < fStart && snapY(extraH + headH + rowSum(r, b + 1) + tail(b + 1)) <= room + 0.5) b++;
          cut = pickBreak(r, b, fStart, S.rowCost, Math.max(2, Math.floor((b - r) / 10)));
          // 다음 쪽에 역 두세 개만 넘어가지 않게 (외톨이 줄): 남는 역이 넷보다 적으면 조금 앞에서 끊는다
          if (cut < fStart && fStart - cut < 4 && fStart - 4 > r + 4) cut = pickBreak(r, fStart - 4, fStart, S.rowCost, 2);
        }
        let built = bandOf(r, cut);
        while (needOf(built, cut) > room + 0.5 && cut > r + 1) { cut = pickBreak(r, cut - 1, fStart, S.rowCost, 2); built = bandOf(r, cut); }
        if (needOf(built, cut) > room + 0.5 && y > 0) { y = 0; continue; }   // 남은 높이에 한 줄도 안 들어가면 새 쪽
        bands.push({ r, cut, built });
        const tierH = gi === 0 && bands.length === 1 && opt.firstW ? tierH0 || 0 : 0;   // 옆에 이어 실은 첫 조각은 그 단의 높이를 따른다
        y = snapY(y + Math.max(needOf(built, cut), tierH) + gapY);
        if (y >= opt.availH - 0.5) y = 0;
        if (cut >= fStart) break;
        r = cut;
      }
    }
    for (let margin = 3, attempt = 0; attempt < 5 && !bands; attempt++) {
      const fits = (a, b, sh = 0) => extraH + headH + rowSum(a, b) + (b >= fStart ? footH + notesH : contH) <= opt.availH - margin - sh;
      const plan = hEnd >= fStart ? [fStart] : cutsFor(hEnd, fStart, fits, S.rowCost, !opt.align, opt.availH * 0.9);
      const res = [];
      let worst = 0;
      for (let r = hEnd, pi = 0; pi < plan.length; pi++) {
        const built = bandOf(r, plan[pi]);
        worst = Math.max(worst, over(built, plan[pi]));
        if (worst > 0.5 && attempt < 4) break;
        res.push({ r, cut: plan[pi], built });
        r = plan[pi];
      }
      if (worst <= 0.5) bands = res;
      else if (attempt < 4) margin += worst + 2;
      else {   // 마지막: 넘치는 띠만 줄이고 나머지는 꽉 채운다
        bands = [];
        for (let r = hEnd; r < fStart || (r === hEnd && hEnd >= fStart);) {
          let cut = cutsFor(r, fStart, fits, S.rowCost, false, 0)[0] ?? fStart;
          let built = bandOf(r, cut);
          while (over(built, cut) > 0.5 && cut > r + 1) { cut = pickBreak(r, cut - 1, fStart, S.rowCost); built = bandOf(r, cut); }
          bands.push({ r, cut, built });
          if (cut <= r || cut >= fStart) break;
          r = cut;
        }
      }
    }

    bands.forEach(({ cut, built }) => {
      const lastBand = cut >= fStart;
      built.forEach((b, k) => {
        const ch = grp[k];
        const last = lastGroup && lastBand && k === grp.length - 1;
        const sameBandNext = k < grp.length - 1;
        frags.push({
          el: b.el, w: b.w, h: b.h, side: ch.side, fs, last, grid: b.grid,
          cont: !last && !(ch.side === 'L' && sameBandNext),
          contDir: sameBandNext || lastBand ? 'h' : 'v',
          overflow: ch.overW || b.h > opt.availH + 0.5 || b.w > opt.availW + 0.5,
        });
      });
    });
  });
  return frags;
  };
  return { cut, hChunks: chunks.length, spread: chunks.some((ch) => ch.side), w0: chunks[0].tall.w };

  function notesHeight() {
    if (!M.hasNotes) return 0;
    const t = build(allRows, chunks[chunks.length - 1].keepCols, { notes: true, title: true });
    return t.notesH;
  }
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

const FRAG_CACHE = new Map();   // [표·조건·자리] → 조각들 (다시 그릴 때 그대로 쓴다)
const INFO_CACHE = new Map();   // [표·조건] → 가로 조각 수·펼침면인가·첫 조각 폭
const MEASURE = new WeakMap();  // 표 → ('글자 크기|글꼴' → 잰 값)

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
  const T0 = performance.now(); const lap = (k) => globalThis.__ttlog?.push(k + ' ' + Math.round(performance.now() - T0));
  const box = measurer(mroot, g);
  // 표지·차례 글자의 글꼴을 미리 받아 둘 곳
  const warmBox = document.createElement('div');
  warmBox.className = 'm-box';
  warmBox.style.width = `${g.cw}mm`;
  mroot.appendChild(warmBox);
  const availW = g.cw * MM, availH = g.ch * MM;
  const warnings = new Set();

  /* 0. 표마다 한 번 그려 재 둔다 (글꼴도 이때 받는다). 같은 표·같은 글자 크기·같은 글꼴이면 지난번 잰 것을 쓴다.
        그 값으로 책의 격자를 정한다 */
  const tabs = book.items.filter((it) => it.type === 'table')
    .map((it) => ({ it, t: docs.get(`${it.title}@${it.oldid}`)?.tables[it.idx] })).filter((x) => x.t);
  const mkey = `${book.fs}|${book.fonts}|${book.fonts === 'local' ? `${book.localMincho}|${book.localGothic}` : ''}`;
  const measures = new Map();   // 표 → 잰 값
  warmBox.insertAdjacentHTML('beforeend', `<div class="m-free">${esc([book.title, book.subtitle, book.edition, book.publisher, book.date, L.toc].join(' '))}</div>`);
  for (let i = 0; i < tabs.length; i++) {
    const { t } = tabs[i];
    if (measures.has(t.el)) continue;
    let m = MEASURE.get(t.el)?.get(mkey);
    if (!m) {
      onProgress?.(`재는 중 ${i + 1} / ${tabs.length}`);
      m = await measureTable(t.el, box, book.fs);
      if (!MEASURE.has(t.el)) MEASURE.set(t.el, new Map());
      MEASURE.get(t.el).set(mkey, m);
    }
    measures.set(t.el, m);
  }
  await document.fonts.ready;
  const G = book.grid === false ? null : gridFromMeasures(measures.values(), availW, book.fs);
  lap('grid');
  const rightBound = book.binding === 'right';
  const isRightHand = (n) => (n % 2 === 1) !== rightBound;   // n 쪽이 펼쳤을 때 오른쪽 면인가
  const snapY = (v) => (G ? Math.ceil(v / G.R - 1e-3) * G.R : v);
  const fillMode = book.fill !== false;   // 쪽 꽉 채우기(JTB식): 단 사이는 한 줄, '계속'은 자리를 잡지 않고 틀 밑에
  const gapY = fillMode ? snapY(G ? G.R : 3 * MM) : snapY(G ? 4 * MM : 7 * MM);
  const contH = fillMode ? 0 : snapY(5 * MM);

  // 표의 계획(재기·가로 조각)은 이번 그리기 동안 붙잡아 두고, 쪽의 자리마다 세로 띠만 새로 자른다
  const plans = new Map();
  const planFor = async (b, ex) => {
    const pk = JSON.stringify([b.ck, Math.round(ex.firstW || 0), Math.round(ex.firstH || 0)]);
    if (!plans.has(pk)) plans.set(pk, await planTable(b.src, box, { ...b.fopt, ...ex }, measures.get(b.src)));
    return plans.get(pk);
  };
  const fragsFor = async (b, ex) => {
    const fk = JSON.stringify([b.ck, Math.round(ex.firstW || 0), Math.round(ex.firstH || 0), Math.round(ex.startY || 0), Math.round(ex.tierH || 0)]);
    if (FRAG_CACHE.has(fk)) return FRAG_CACHE.get(fk);
    const plan = await planFor(b, ex);
    const fr = !plan || Array.isArray(plan) ? plan : plan.cut(ex.startY || 0, ex.tierH || 0);
    FRAG_CACHE.set(fk, fr);
    if (FRAG_CACHE.size > 400) FRAG_CACHE.delete(FRAG_CACHE.keys().next().value);
    if (fr?.some((f) => f.overflow)) warnings.add(`판면을 넘침: ${b.item.label}`);
    return fr;
  };

  /* 1. 본문 조각들 */
  const blocks = [];   // { kind, item, frags | html }
  for (let i = 0; i < book.items.length; i++) {
    const it = book.items[i];
    onProgress?.(`나누는 중 ${i + 1} / ${book.items.length}`);
    if (it.type === 'table') {
      const d = docs.get(`${it.title}@${it.oldid}`);
      const t = d?.tables[it.idx];
      if (!t) { warnings.add(`표를 찾지 못함: ${it.label || it.title}`); continue; }
      const fopt = {
        fit: it.fit || 'split', scale: (it.scale || 100) / 100, fs: book.fs, align: !!book.alignBands,
        minScale: 0.7, availW, availH, grid: G, fill: fillMode, gapY, contH,
      };
      // 가로 조각까지만 정해 둔다 (세로 띠는 쪽에 놓을 때 그 자리에 맞춰). 같은 표·같은 조건이면 지난번 것을 다시 쓴다
      const ck = JSON.stringify([it.title, it.oldid, it.idx, fopt, mkey]);
      const b = { kind: 'table', item: it, lang: langOf(t.titleText + it.title), src: t.el, fopt, ck };
      b.info = INFO_CACHE.get(ck);
      if (!b.info) {
        const plan = await planFor(b, {});
        b.info = !plan || Array.isArray(plan) ? { hChunks: 1, spread: false, w0: plan?.[0]?.w || 0 } : { hChunks: plan.hChunks, spread: plan.spread, w0: plan.w0 };
        INFO_CACHE.set(ck, b.info);
        if (INFO_CACHE.size > 400) INFO_CACHE.delete(INFO_CACHE.keys().next().value);
      }
      blocks.push(b);
    } else if (it.type === 'divider') {
      blocks.push({ kind: 'divider', item: it });
    } else if (it.type === 'text') {
      // '빈 곳에 끼워 넣기': 囲み記事(お知らせ) 상자로 만들어, 표 쪽의 남는 아래쪽에 넣는다
      if (it.float) {
        box.innerHTML = '';
        const nb = noteBox(it);
        box.appendChild(nb);
        await document.fonts.ready;
        const h = rect(nb).height;
        if (h < availH * 0.8) { blocks.push({ kind: 'note', item: it, html: nb.outerHTML, h }); continue; }
      }
      blocks.push({ kind: 'text', item: it, pages: await textPages(it.text || '', box, availH) });
    }
  }

  lap('plans');
  /* 2. 쪽 배치 (차례 쪽 수를 맞출 때까지 되풀이) */
  let tocPages = book.parts.toc ? 1 : 0;
  let pages, tocEntries, secMarks;
  for (let round = 0; round < 4; round++) {
    pages = [];
    tocEntries = [];
    secMarks = new Map();   // 쪽 없는 구역: 그 구역이 시작하는 쪽(차례 번호) → 이름
    let deferred = null;    // 쪽 없는 구역에 준 쪽 번호: 다음에 생기는 쪽에 단다
    if (book.parts.cover) pages.push({ kind: 'cover' });
    for (let k = 0; k < tocPages; k++) pages.push({ kind: 'toc', part: k });
    let cur = null;   // 지금 채우는 표 쪽
    // 다음 쪽이 hand('left'|'right') 면이 되게 한다 (아니면 빈 쪽을 하나 넣는다)
    const startOn = (hand) => { if ((hand === 'right') !== isRightHand(pages.length + 1)) pages.push({ kind: 'blank' }); };
    // 囲み記事: 기다리다가, 표 쪽을 떠날 때 그 쪽 아래에 남은 자리에 들어가면 넣는다 (쪽 아래에 붙여서)
    const pending = [];
    const fitNotes = () => {
      if (!cur || cur.side || cur.kind !== 'table' || !pending.length) return;
      const tier = cur.tiers[cur.tiers.length - 1];
      const y0 = tier ? snapY(tier.y + tier.h + gapY) : 0;
      const take = [];
      let tot = 0;
      for (const n of pending) {
        const add = snapY(n.h) + (take.length ? gapY : 0);
        if (y0 + tot + add > availH + 0.5) break;
        take.push(n);
        tot += add;
      }
      if (!take.length) return;
      let y = Math.max(y0, G ? Math.floor((availH - tot) / G.R + 1e-6) * G.R : availH - tot);
      for (const n of take) {
        cur.frags.push({ note: n, x: 0, y });
        cur.tiers.push({ y, x: availW, h: snapY(n.h) });
        if (n.item.toc) tocEntries.push({ text: n.item.toc, page: pages.indexOf(cur) + 1, level: 0 });
        y = snapY(y + snapY(n.h) + gapY);
      }
      pending.splice(0, take.length);
    };
    const closePage = () => { fitNotes(); cur = null; };
    for (const b of blocks) {
      if (b.kind === 'note') { pending.push(b); continue; }
      // 항목의 시작: 새 쪽 / 왼쪽·오른쪽 면 / 쪽 번호 다시 매기기 (번호만 주면 그 번호의 홀짝에 맞는 면에서)
      const it = b.item;
      const restart = it.folio === '' || it.folio == null || !Number.isFinite(+it.folio) ? null : Math.trunc(+it.folio);
      const spreadItem = b.kind === 'table' && b.info.spread;
      let hand = it.start === 'left' || it.start === 'right' ? it.start : null;
      if (restart != null && !hand) hand = isRightHand(restart) ? 'right' : 'left';
      if (spreadItem) hand = null;   // 펼침면은 스스로 면을 정한다
      if (hand || it.start === 'page' || restart != null || b.kind !== 'table') closePage();
      if (hand) startOn(hand);
      const firstIdx = pages.length;
      const markRestart = () => {
        if (restart == null) return;
        const k = pages.findIndex((pg, i) => i >= firstIdx && pg.kind !== 'blank');
        if (k >= 0) pages[k].restart = restart;
      };
      if (b.kind === 'divider' && b.item.inline) {   // 쪽 없이 구역만: 다음 쪽부터 새 구역
        secMarks.set(pages.length, b.item.text || '');
        tocEntries.push({ text: b.item.text || '', page: pages.length + 1, level: 0, sec: true });
        if (restart != null) deferred = { restart, firstIdx };
        continue;
      }
      if (b.kind === 'divider') {
        pages.push({ kind: 'divider', item: b.item });
        markRestart();
        tocEntries.push({ text: b.item.text || '', page: pages.length, level: 0, sec: true });
        continue;
      }
      if (b.kind === 'text') {
        b.pages.forEach((html, k) => {
          pages.push({ kind: 'text', html, item: b.item });
          if (k === 0 && b.item.toc) tocEntries.push({ text: b.item.toc, page: pages.length, level: 0 });
        });
        markRestart();
        continue;
      }
      // 표: 쪽은 단(段)들로 채운다. 조각은 지금 단의 오른쪽에 들어가면 나란히, 아니면 아래에 새 단, 그도 안 되면 새 쪽.
      // 격자에서는 단의 오른쪽이 넉넉히 남았는데 표가 거기 다 들어가지 않으면, 실제 시각표처럼 첫 열차들을 거기에 이어 싣는다.
      let frags = null;
      const tier0 = book.pack && cur && !cur.side && !spreadItem ? cur.tiers[cur.tiers.length - 1] : null;
      if (G && tier0) {
        const remW = availW - tier0.x;
        const remH = Math.floor(availH / G.R + 1e-6) * G.R - tier0.y;
        if (b.info.hChunks > 1 && b.info.w0 > remW + 0.5 && remW >= 4 * G.P - 0.5 && remH > availH * 0.15) {
          frags = await fragsFor(b, { firstW: remW, firstH: remH, startY: tier0.y, tierH: tier0.h });
        }
      }
      // 쪽 꽉 채우기: 이 쪽의 남은 높이에서부터 띠를 자른다
      if (!frags) {
        let startY = fillMode && tier0 && !b.fopt.align ? snapY(tier0.y + tier0.h + gapY) : 0;
        if (startY >= availH - 0.5) startY = 0;
        frags = await fragsFor(b, { startY });
      }
      // 오른쪽 철에서는 펼침면의 오른쪽 면이 먼저 온다: 짝(L, R)을 (R, L)로
      if (rightBound && spreadItem) {
        frags = frags.slice();
        for (let i = 0; i + 1 < frags.length; i++) {
          if (frags[i].side === 'L' && frags[i + 1].side === 'R') { [frags[i], frags[i + 1]] = [frags[i + 1], frags[i]]; i++; }
        }
      }
      frags.forEach((f, k) => {
        if (f.side) closePage();
        if (f.side && (f.side === 'R') !== isRightHand(pages.length + 1)) {   // 펼침면: L 은 왼쪽 면, R 은 오른쪽 면에
          pages.push({ kind: 'blank' });
        }
        const need = snapY(f.h + (f.cont ? contH : 0));
        const free = book.pack && cur && !f.side && !cur.side;
        const tier = cur && cur.tiers[cur.tiers.length - 1];
        let y;
        if (free && tier.x + f.w <= availW + 0.5 && tier.y + need <= availH + 0.5) {
          cur.frags.push({ f, x: tier.x, y: tier.y });
          tier.x += f.w;
          tier.h = Math.max(tier.h, need);
          if (!cur.labels.includes(b.item.label)) cur.labels.push(b.item.label);
        } else if (free && (y = snapY(tier.y + tier.h + gapY)) + need <= availH + 0.5) {
          cur.tiers.push({ y, x: f.w, h: need });
          cur.frags.push({ f, x: 0, y });
          if (!cur.labels.includes(b.item.label)) cur.labels.push(b.item.label);
        } else {
          fitNotes();
          // 펼침면 왼쪽 쪽의 표는 제본 쪽(오른쪽)에 붙인다 (격자에서는 빈 열로 판면 폭을 채우므로 같다)
          const x = f.side === 'L' && !G ? Math.max(0, availW - f.w) : 0;
          cur = { kind: 'table', tiers: [{ y: 0, x: x + f.w, h: need }], frags: [{ f, x, y: 0 }], labels: [b.item.label],
                  lang: b.lang, side: f.side, contFirst: k > 0 && !(spreadItem && k % 2 === 1) };   // 펼침면의 맞은편 쪽은 '이어짐'이 아니다
          pages.push(cur);
        }
        if (k === 0) tocEntries.push({ text: b.item.label, page: pages.length, level: 1 });
        if (f.side) cur = null;   // 펼침면 쪽에는 더 싣지 않는다
      });
      markRestart();
      if (deferred && pages.length > deferred.firstIdx) {
        const k = pages.findIndex((pg, i) => i >= deferred.firstIdx && pg.kind !== 'blank');
        if (k >= 0) { pages[k].restart = deferred.restart; deferred = null; }
      }
    }
    // 남은 囲み記事는 마지막 표 쪽에, 그래도 남으면 새 쪽에 차례로
    fitNotes();
    while (pending.length) {
      cur = { kind: 'table', tiers: [], frags: [], labels: [], lang: book.lang, side: null };
      pages.push(cur);
      let y = 0;
      while (pending.length && (y === 0 || y + snapY(pending[0].h) <= availH + 0.5)) {
        const n = pending.shift();
        cur.frags.push({ note: n, x: 0, y });
        if (n.item.toc) tocEntries.push({ text: n.item.toc, page: pages.length, level: 0 });
        y = snapY(y + snapY(n.h) + gapY);
      }
    }
    cur = null;
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

  lap('placed');
  /* 3. 그리기 */
  out.innerHTML = '';
  // 찍히는 쪽 번호: 표지부터 1, 2, … 다시 매기라는 쪽에서 그 수로
  const folios = [];
  pages.forEach((p, i) => folios.push(p.restart ?? (i ? folios[i - 1] + 1 : 1)));
  for (const e of tocEntries) e.page = folios[e.page - 1];
  // 구역(중표지) 색: 찾기 표와 차례의 띠가 같은 색
  let si = -1;
  for (const e of tocEntries) if (e.sec) e.color = book.color === 'mono' ? '#000' : TAB_COLORS[++si % TAB_COLORS.length];
  const tocChunks = book.parts.toc ? await splitToc(tocEntries, box, availH, L) : [];
  // 찾기 표(爪): 중표지마다 한 구역. 구역의 쪽들 바깥 가장자리에 구역 이름을 단다
  let sec = null, secN = -1;
  pages.forEach((p, i) => {
    if (secMarks.has(i)) sec = { text: secMarks.get(i), idx: ++secN };
    if (p.kind === 'divider') sec = { text: p.item.text || '', idx: ++secN };
    if (sec && sec.text && ['divider', 'table', 'text'].includes(p.kind)) p.sec = sec;
  });
  pages.forEach((p, i) => {
    const n = i + 1;
    const sheet = makeSheet(book, g, isRightHand(n));
    if (book.parts.thumb !== false && p.sec) sheet.querySelector('.page').insertAdjacentHTML('beforeend', thumbTab(book, g, isRightHand(n), p.sec));
    const page = sheet.querySelector('.page');
    const content = page.querySelector('.content');
    let runhead = '', folio = String(folios[i]);
    if (p.kind === 'cover') {
      page.insertAdjacentHTML('beforeend', coverPage(book, g, isRightHand(n), tocEntries.filter((e) => e.sec && e.text)));
      folio = '';
      page.classList.add('is-cover');
    }
    else if (p.kind === 'toc') { content.appendChild(tocChunks[p.part] || document.createElement('div')); }
    else if (p.kind === 'divider') { content.appendChild(divider(p.item)); folio = ''; page.classList.add('is-blank'); }
    else if (p.kind === 'text') { const d = document.createElement('div'); d.className = 'textpage'; d.innerHTML = p.html; content.appendChild(d); runhead = p.item.toc || ''; }
    else if (p.kind === 'blank') { folio = ''; page.classList.add('is-blank'); }
    else if (p.kind === 'colophon') { content.appendChild(colophon(book, docs, L)); runhead = ''; page.classList.add('is-blank'); }
    else if (p.kind === 'table') {
      // 머리글: 이 쪽에 실린 표 이름들 (같은 앞부분은 한 번만), 앞 쪽에서 이어지면 '(つづき)'
      runhead = joinLabels(p.labels, (STR[p.lang] || L).more) + (p.contFirst ? (STR[p.lang] || L).contd : '');
      // 단마다 마지막 조각의 오른쪽을 빈 열로 판면 끝까지 채운다
      const lastOf = new Map();
      for (const pl of p.frags) if (pl.f && (!lastOf.has(pl.y) || pl.x > lastOf.get(pl.y).x)) lastOf.set(pl.y, pl);
      p.frags.forEach((pl) => {
        if (pl.note) {
          const d = document.createElement('div');
          d.className = 'frag';
          d.style.left = `${pl.x}px`;
          d.style.top = `${pl.y}px`;
          d.style.width = `${availW}px`;
          d.innerHTML = pl.note.html;
          content.appendChild(d);
          return;
        }
        const { f, x, y } = pl;
        const holder = document.createElement('div');
        holder.className = 'frag';
        holder.style.left = `${x}px`;
        holder.style.top = `${y}px`;
        holder.style.setProperty('--bk-fs', `${f.fs}pt`);
        const el = f.el.cloneNode(true);
        if (G && f.grid && lastOf.get(y) === pl) {
          const k = Math.round((availW - x - f.w) / G.P);
          if (k >= 1) padTable(el, k, f.grid);
        }
        holder.appendChild(el);
        if (f.cont) {
          const c = document.createElement('div');
          c.className = fillMode ? 'cont cont-abs' : 'cont';
          c.textContent = (STR[p.lang] || L).cont + (f.contDir === 'v' ? ' ↓' : ' →');
          holder.appendChild(c);
        }
        content.appendChild(holder);
      });
    }
    if (book.parts.runhead && runhead) page.querySelector('.runhead').textContent = runhead;
    if (book.parts.folio && folio) page.querySelector('.folio').textContent = folio;
    out.appendChild(sheet);
  });
  lap('drawn');
  mroot.innerHTML = '';
  return { pages: pages.length, warnings: [...warnings], size: [W, H] };
}

/** 머리글: 'A B 下り' + 'A B 上り' → 'A B 下り・上り'. 셋보다 많으면 앞의 둘과 '외 n'(他 n) */
function joinLabels(labels, more = '외') {
  let ls = [...new Set((labels || []).filter(Boolean))];
  if (ls.length <= 1) return ls[0] || '';
  const rest = ls.length > 3 ? ls.length - 2 : 0;
  if (rest) ls = ls.slice(0, 2);
  const toks = ls.map((l) => l.split(/\s+/));
  let k = 0;
  while (toks.every((t) => t.length > k + 1 && t[k] === toks[0][k])) k++;
  const body = k ? `${toks[0].slice(0, k).join(' ')} ${toks.map((t) => t.slice(k).join(' ')).join('・')}` : ls.join(' · ');
  return rest ? `${body} ${more} ${rest}` : body;
}

/** 囲み記事 상자 */
function noteBox(it) {
  const d = document.createElement('div');
  d.className = 'notebox';
  d.innerHTML = mdLite(it.text || '');
  return d;
}

/** 찾기 표(爪): 바깥 가장자리의 구역 표시. 재단선을 넣으면 도련까지 칠한다 */
const TAB_COLORS = ['#1f3a6e', '#7c2230', '#24603a', '#6e4d12', '#46307a', '#14606a'];
function thumbTab(book, g, recto, sec) {
  const TH = 24, GAP = 2;
  const slots = Math.max(1, Math.floor((g.ch - 10) / (TH + GAP)));
  const top = g.top + 5 + (sec.idx % slots) * (TH + GAP);
  const vis = Math.max(3.5, Math.min(7, g.outer - 2));
  const bleed = book.output?.marks ? BLEED : 0;
  const bg = book.color === 'mono' ? '#000' : TAB_COLORS[sec.idx % TAB_COLORS.length];
  const side = recto ? `right:${-bleed}mm;padding-right:${bleed}mm` : `left:${-bleed}mm;padding-left:${bleed}mm`;
  return `<div class="thumb" style="top:${top}mm;height:${TH}mm;width:${vis}mm;${side};background:${bg}">${esc(sec.text)}</div>`;
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
  const fp = book.folioPos || 'bottom-outer';
  page.className = `page ${recto ? 'recto' : 'verso'} fol-${fp}`;
  Object.assign(page.style, {
    left: `${marks ? CROP : 0}mm`, top: `${marks ? CROP : 0}mm`, width: `${g.W}mm`, height: `${g.H}mm`,
  });
  const inL = recto ? g.inner : g.outer;
  const inR = recto ? g.outer : g.inner;
  page.innerHTML = `<div class="runhead" style="left:${inL}mm;right:${inR}mm;bottom:${g.H - g.top + 2}mm"></div>`
    + `<div class="content" style="left:${inL}mm;top:${g.top}mm;width:${g.cw}mm;height:${g.ch}mm"></div>`
    + (fp === 'top-outer'
      ? `<div class="folio" style="left:${inL}mm;right:${inR}mm;bottom:${g.H - g.top + 2 + 1.2}mm"></div>`
      : `<div class="folio" style="left:${inL}mm;right:${inR}mm;top:${g.H - g.bottom + 5}mm"></div>`);
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

/**
 * 표지: 월간 시각표처럼. 위쪽 색 띠(도련까지)에 책 이름과 큰 달 숫자(호), 아래에 부제·주요 내용(구역과 쪽)·펴낸 날·펴낸 곳.
 * '표지 머리'가 '2026년 10월호'·'1979年3月号' 꼴이면 해와 달을 뽑아 큰 숫자로.
 */
function coverPage(book, g, recto, secs) {
  const ja = book.lang === 'ja';
  const m = /(\d{3,4})\s*[年년.\-/]\s*(\d{1,2})/.exec(book.edition || '');
  const bleed = book.output?.marks ? BLEED : 0;
  const inL = recto ? g.inner : g.outer, inR = recto ? g.outer : g.inner;
  const bandH = Math.round(g.H * 0.36);
  const bg = book.color === 'mono' ? '#000' : TAB_COLORS[0];
  const issue = m
    ? `<div class="cv2-issue"><span class="cv2-year">${esc(m[1])}${ja ? '年' : '년'}</span><span class="cv2-month">${+m[2]}</span><span class="cv2-gou">${ja ? '月号' : '월호'}</span></div>`
    : (book.edition ? `<div class="cv2-issue cv2-issue-t">${esc(book.edition)}</div>` : '');
  const list = secs.length
    ? `<div class="cv2-cl">${ja ? '主な内容' : '주요 내용'}</div><ul class="cv2-secs">${secs.map((e) => `<li><i style="background:${e.color || '#000'}"></i><span>${esc(e.text)}</span><b>${e.page}</b></li>`).join('')}</ul>`
    : '';
  return `<div class="cv2-band" style="left:${-bleed}mm;right:${-bleed}mm;top:${-bleed}mm;height:${bandH + bleed}mm;background:${bg};padding:${g.top + bleed}mm ${inR + bleed}mm 7mm ${inL + bleed}mm">
      <div class="cv2-title">${esc(book.title || '')}</div>${issue}</div>
    <div class="cv2-body" style="left:${inL}mm;right:${inR}mm;top:${bandH + 8}mm;bottom:${g.bottom}mm">
      ${book.subtitle ? `<div class="cv2-sub">${esc(book.subtitle)}</div>` : ''}${list}
      <div class="cv2-foot"><div>${esc(book.date || '')}</div><div class="cv2-pub">${esc(book.publisher || '')}</div></div>
    </div>`;
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
  // 구역(중표지)은 색 띠로, 그 아래 표들은 점선과 쪽 번호로 (JTB 시각표의 さくいん처럼)
  if (e.sec) return `<li class="toc-l0 toc-sec" style="background:${e.color || '#000'}"><span>${esc(e.text)}</span><i></i><span class="toc-p">${e.page}</span></li>`;
  return `<li class="toc-l${e.level}"><span>${esc(e.text)}</span><i></i><span class="toc-p">${e.page}</span></li>`;
}

async function splitToc(entries, box, availH, L) {
  const pages = [];
  let wrap, ul;
  const start = (first) => {
    wrap = document.createElement('div');
    wrap.className = box.getBoundingClientRect().width < 100 * MM ? 'toc toc-1col' : 'toc';
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
  const fonts = {
    shaken: 'DiaPro (OFL) · 石井明朝·石井ゴシック (TypeSquare) · 은바탕·은돋움 (GPL)',
    antique: 'DiaPro · Shippori Mincho B1 · Zen Kaku Gothic Antique · Song Myung (OFL) · 은바탕·은돋움 (GPL)',
    shippori: 'DiaPro · Shippori Mincho · Zen Kaku Gothic New (OFL) · 은바탕·은돋움 (GPL)',
    tokumin: 'DiaPro · Kaisei Tokumin · Shippori Antique B1 · Gowun Batang (OFL) · 은바탕·은돋움 (GPL)',
    local: `DiaPro (OFL) · ${[book.localMincho, book.localGothic].filter(Boolean).join('·') || 'Zen'} · 은바탕·은돋움 (GPL)`,
  }[book.fonts] || 'DiaPro (OFL) · Zen Old Mincho·Zen Kaku Gothic New (OFL) · 은바탕·은돋움 (GPL)';
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
