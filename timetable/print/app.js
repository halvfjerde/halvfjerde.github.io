/* 시각표 인쇄 — 고르기·설정·미리보기 */
import { layoutBook, extractTables, defaultLabel, shortTitle, SIZES } from './layout.js?v=12';

const $ = (s) => document.querySelector(s);
const KEY = 'tt-print-book-v1';
const API = 'api.php';

const today = () => { const d = new Date(); return `${d.getFullYear()}. ${d.getMonth() + 1}. ${d.getDate()}.`; };
// 기본은 JTB 시각표처럼: 알맞은 여백, 7pt, 쪽 번호는 위 바깥, 격자에 맞춰 쪽 끝까지 흘려 넣는다
const DEFAULT = () => ({
  v: 3, title: '시각표', subtitle: '', edition: '', date: today(), publisher: '', lang: 'ko', colophonNote: '',
  page: { size: 'B5', w: 182, h: 257, margin: { top: 14, bottom: 9, inner: 13, outer: 9 } },
  fs: 7, fonts: 'free', color: 'color', binding: 'left', folioPos: 'top-outer',
  parts: { cover: true, toc: true, runhead: true, folio: true, colophon: true, thumb: true },
  pack: true, grid: true, fill: true, alignBands: false, pad4: false, output: { marks: false },
  items: [],
});

/* ── 상태 ── */
let book = load() || DEFAULT();
// 읽기(디지털판): 주소의 #read= 에 책 설계도가 눌려 들어 있다. 편집 중인 책(브라우저 저장)은 건드리지 않는다
let reading = false;
if (location.hash.startsWith('#read=')) {
  try { book = merge(DEFAULT(), upgrade(await unpackBook(location.hash.slice(6)))); reading = true; } catch (e) { console.warn('읽기 링크를 풀지 못함', e); }
}
document.body.classList.toggle('reading', reading);
addEventListener('hashchange', () => { if (location.hash.startsWith('#read=') || reading) location.reload(); });
if (reading) {
  document.title = `${book.title || '시각표'}${book.edition ? ` ${book.edition}` : ''}`;
  document.querySelector('.brand h1').textContent = document.title;
  document.querySelector('.brand .sub').hidden = true;
}

/** 설계도 ↔ 주소에 넣을 글자 (deflate + base64url) */
async function packBook(b) {
  const z = new Blob([JSON.stringify(b)]).stream().pipeThrough(new CompressionStream('deflate-raw'));
  const u8 = new Uint8Array(await new Response(z).arrayBuffer());
  let s = '';
  for (const x of u8) s += String.fromCharCode(x);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
async function unpackBook(str) {
  const b64 = str.replace(/-/g, '+').replace(/_/g, '/');
  const bin = atob(b64 + '==='.slice((b64.length + 3) % 4));
  const z = new Blob([Uint8Array.from(bin, (c) => c.charCodeAt(0))]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
  return JSON.parse(await new Response(z).text());
}
const docs = new Map();          // 'title@revid' → { title, revid, timestamp, latest, tables }
let pageList = [];               // 위키의 시각표 문서들
const open = new Set();          // 펼친 문서

function load() {
  try { const j = JSON.parse(localStorage.getItem(KEY) || 'null'); return j && j.v >= 1 && j.v <= 3 ? merge(DEFAULT(), upgrade(j)) : null; } catch (e) { return null; }
}
/** 옛 설계도: 손대지 않은 옛 기본값(1판의 넓은 여백·8pt·아래 쪽 번호, 2판의 좁은 여백)은 지금 기본값으로 바꾼다 */
function upgrade(j) {
  const m = j.page?.margin;
  const is = (t, b, i, o) => m && m.top === t && m.bottom === b && m.inner === i && m.outer === o;
  if (j.v === 1) {
    if (is(14, 14, 16, 12)) delete j.page.margin;
    if (j.fs === 8) delete j.fs;
    if (j.folioPos === 'bottom-outer') delete j.folioPos;
  }
  if (j.v === 2 && is(11, 6, 10, 6)) delete j.page.margin;
  j.v = 3;
  return j;
}
function persist() { if (reading) return; try { localStorage.setItem(KEY, JSON.stringify(book)); } catch (e) { /* 저장 불가 */ } }
function merge(base, j) {
  const out = { ...base, ...j };
  out.page = { ...base.page, ...(j.page || {}), margin: { ...base.page.margin, ...(j.page?.margin || {}) } };
  out.parts = { ...base.parts, ...(j.parts || {}) };
  out.output = { ...base.output, ...(j.output || {}) };
  out.items = Array.isArray(j.items) ? j.items : [];
  return out;
}

/* ── 위키 자료 ── */
async function api(params) {
  const r = await fetch(`${API}?${new URLSearchParams(params)}`);
  const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok || j.error) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}

const inflight = new Map();      // 같은 문서를 동시에 두 번 받지 않는다
async function getDoc(title, oldid) {
  const key = `${title}@${oldid || 'latest'}`;
  if (docs.has(key)) return docs.get(key);
  if (inflight.has(key)) return inflight.get(key);
  const p = (async () => {
    const j = await api(oldid ? { action: 'page', title, oldid } : { action: 'page', title });
    const d = { title: j.title, revid: j.revid, timestamp: j.timestamp, latest: j.latest, tables: extractTables(j.html) };
    docs.set(`${title}@${j.revid}`, d);
    if (!oldid) docs.set(key, d);
    return d;
  })();
  inflight.set(key, p);
  try { return await p; } finally { inflight.delete(key); }
}

/** 많은 일을 n 개씩만 동시에 (위키 서버가 한꺼번에 파싱하느라 막히지 않게) */
async function pool(list, n, fn, onEach) {
  let i = 0, done = 0;
  const out = new Array(list.length);
  await Promise.all(Array.from({ length: Math.min(n, list.length) }, async () => {
    while (i < list.length) {
      const k = i++;
      try { out[k] = await fn(list[k]); } catch (e) { console.warn(e); }
      onEach?.(++done, list.length);
    }
  }));
  return out;
}

/** 노선·해 차례: '시각표:경춘선/2010년' → ['경춘선', '2010년'] 을 숫자까지 자연스럽게 */
const collator = new Intl.Collator(['ko', 'ja'], { numeric: true });
const lineOf = (title) => shortTitle(title).split(' ')[0];
const byTitle = (a, b) => collator.compare(lineOf(a), lineOf(b)) || collator.compare(a, b);

/* ── 자료 목록 ── */
const NS_ORDER = { 3006: 0 };
function renderSources() {
  const q = $('#srcFind').value.trim().toLowerCase();
  const ul = $('#srcList');
  ul.innerHTML = '';
  const list = pageList
    .filter((p) => !q || p.title.toLowerCase().includes(q) || p.displaytitle.toLowerCase().includes(q))
    .sort((a, b) => (NS_ORDER[a.ns] ?? 9) - (NS_ORDER[b.ns] ?? 9) || byTitle(a.title, b.title));
  for (const p of list) {
    const li = document.createElement('li');
    const ns = p.title.includes(':') ? p.title.split(':')[0] : '';
    li.innerHTML = `<button type="button" class="doc"><span class="ns">${esc(ns)}</span><span>${esc(shortTitle(p.title))}</span>`
      + `<span class="d">${p.timestamp ? p.timestamp.slice(0, 10) : ''}</span></button>`;
    li.querySelector('.doc').onclick = () => { open.has(p.title) ? open.delete(p.title) : open.add(p.title); renderSources(); };
    if (open.has(p.title)) {
      const box = document.createElement('div');
      box.innerHTML = '<div class="loading">불러오는 중…</div>';
      li.appendChild(box);
      getDoc(p.title).then((d) => {
        const tl = document.createElement('ul');
        tl.className = 'tables';
        d.tables.forEach((t) => {
          const row = document.createElement('li');
          const label = defaultLabel(p.title, t);
          row.innerHTML = `<span>${esc(t.titleText || label)}${t.heads.length ? ` <small style="color:var(--ui-faint)">${esc(t.heads.join(' · '))}</small>` : ''}</span><button type="button">+ 싣기</button>`;
          row.querySelector('button').onclick = () => addTable(p.title, d.revid, t.idx, label);
          tl.appendChild(row);
        });
        if (d.tables.length > 1) {
          const row = document.createElement('li');
          row.innerHTML = '<span></span><button type="button">+ 전부</button>';
          row.querySelector('button').onclick = () => d.tables.forEach((t) => addTable(p.title, d.revid, t.idx, defaultLabel(p.title, t)));
          tl.appendChild(row);
        }
        if (!d.tables.length) tl.innerHTML = '<li><span style="color:var(--ui-faint)">표가 없다</span></li>';
        box.replaceChildren(tl);
      }).catch((e) => { box.innerHTML = `<div class="loading">못 불러옴: ${esc(e.message)}</div>`; });
    }
    ul.appendChild(li);
  }
  if (!list.length) ul.innerHTML = '<li class="loading">없음</li>';
}

function addTable(title, oldid, idx, label) {
  book.items.push({ type: 'table', title, oldid, idx, label, fit: 'split', scale: 100 });
  changed(true);
}

/* ── 싣는 차례 ── */
let dragFrom = -1;
const FIT = [['split', '나누기'], ['shrink', '줄여 맞추기'], ['spread', '펼침면']];
const START = [['', '이어서'], ['page', '새 쪽'], ['left', '왼쪽 면에서'], ['right', '오른쪽 면에서']];
function renderItems() {
  const ol = $('#items');
  ol.innerHTML = '';
  $('#itemCount').textContent = book.items.length ? `${book.items.length}개` : '자료에서 표를 더한다';
  const latest = new Map(pageList.map((p) => [p.title, p.revid]));
  const grid = book.grid !== false;
  let inSec = false;
  book.items.forEach((it, i) => {
    const li = document.createElement('li');
    if (it.type === 'divider') { li.classList.add('sec'); inSec = true; } else if (inSec) li.classList.add('in-sec');
    // 끌어서 옮기기 (번호를 잡고)
    li.draggable = true;
    li.addEventListener('dragstart', (e) => {
      if (e.target.closest('input, textarea, select')) { e.preventDefault(); return; }
      dragFrom = i;
      li.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    });
    li.addEventListener('dragend', () => li.classList.remove('dragging'));
    li.addEventListener('dragover', (e) => { if (dragFrom < 0) return; e.preventDefault(); li.classList.add('drop-before'); });
    li.addEventListener('dragleave', () => li.classList.remove('drop-before'));
    li.addEventListener('drop', (e) => {
      e.preventDefault();
      li.classList.remove('drop-before');
      if (dragFrom < 0 || dragFrom === i) return;
      const [x] = book.items.splice(dragFrom, 1);
      book.items.splice(dragFrom < i ? i - 1 : i, 0, x);
      dragFrom = -1;
      changed(true);
    });
    const body = document.createElement('div');
    body.className = 'body';
    if (it.type === 'table') {
      const old = latest.get(it.title) && latest.get(it.title) > it.oldid;
      body.innerHTML = `<input type="text" data-k="label" value="${esc(it.label)}" title="차례와 머리글에 쓰는 이름">
        <div class="meta">${esc(shortTitle(it.title))} · 판 ${it.oldid}${old ? ' <span class="old">· 더 새 판 있음</span>' : ''}</div>
        <div class="opts"><select data-k="fit">${FIT.filter(([v]) => !(grid && v === 'shrink') || it.fit === v).map(([v, t]) => `<option value="${v}"${it.fit === v ? ' selected' : ''}>${t}${grid && v === 'shrink' ? ' (격자에서는 나누기)' : ''}</option>`).join('')}</select>
        <input type="number" data-k="scale" min="40" max="150" step="5" value="${it.scale || 100}"${grid ? ' disabled title="격자에 맞출 때는 책 전체가 같은 글자 크기"' : ' title="글자 크기 (%)"'}></div>`;
    } else if (it.type === 'divider') {
      body.innerHTML = `<input type="text" data-k="text" value="${esc(it.text || '')}" placeholder="구역 이름 (중표지 제목)">
        ${it.inline ? '' : `<input type="text" data-k="sub" value="${esc(it.sub || '')}" placeholder="작은 글 (없어도 됨)">`}
        <label class="chk" title="중표지 쪽을 따로 두지 않고, 새 쪽에서 구역(찾기 표·차례의 구역)만 시작한다"><input type="checkbox" data-k="inline"${it.inline ? ' checked' : ''}>쪽 없이 구역만</label>`;
    } else {
      body.innerHTML = `<input type="text" data-k="toc" value="${esc(it.toc || '')}" placeholder="차례에 올릴 이름 (없으면 안 올림)">
        <textarea data-k="text" rows="4" placeholder="빈 줄로 문단을 나눈다. '# '는 제목, '- '는 목록">${esc(it.text || '')}</textarea>
        <label class="chk" title="쪽을 따로 쓰지 않고, 표 쪽 아래에 남는 자리에 테두리 상자(囲み記事)로 넣는다"><input type="checkbox" data-k="float"${it.float ? ' checked' : ''}>빈 곳에 끼워 넣기 (알림 상자)</label>`;
    }
    // 시작할 면과 쪽 번호 (위키 문서에는 없는 것)
    const starts = it.type === 'table' ? START : [['', '새 쪽'], ...START.slice(2)];
    if (!(it.type === 'text' && it.float)) body.insertAdjacentHTML('beforeend', `<div class="opts"><select data-k="start" title="이 항목을 어디서 시작할지">${starts.map(([v, t]) => `<option value="${v}"${(it.start || '') === v ? ' selected' : ''}>${t}</option>`).join('')}</select>
      <input type="number" data-k="folio" step="1" value="${it.folio ?? ''}" placeholder="쪽 번호" title="이 항목의 첫 쪽 번호. 비우면 앞에서 이어 센다. 왼쪽·오른쪽 면을 고르지 않았으면 이 번호의 홀짝에 맞는 면에서 시작한다"></div>`);
    body.querySelectorAll('[data-k]').forEach((el) => {
      el.addEventListener('change', () => {
        const k = el.dataset.k;
        it[k] = el.type === 'checkbox' ? el.checked
          : k === 'scale' ? Math.max(40, Math.min(150, +el.value || 100))
          : k === 'folio' ? (el.value === '' || !Number.isFinite(+el.value) ? '' : Math.trunc(+el.value)) : el.value;
        changed(k === 'float' || k === 'inline');
      });
    });
    const ctl = document.createElement('div');
    ctl.className = 'ctl';
    ctl.innerHTML = '<button type="button" data-a="up" title="위로">↑</button><button type="button" data-a="down" title="아래로">↓</button><button type="button" data-a="del" title="빼기">✕</button>';
    ctl.onclick = (e) => {
      const a = e.target.dataset.a;
      if (!a) return;
      if (a === 'up' && i > 0) [book.items[i - 1], book.items[i]] = [book.items[i], book.items[i - 1]];
      else if (a === 'down' && i < book.items.length - 1) [book.items[i + 1], book.items[i]] = [book.items[i], book.items[i + 1]];
      else if (a === 'del') book.items.splice(i, 1);
      else return;
      changed(true);
    };
    li.append(body, ctl);
    ol.appendChild(li);
  });
}

/* ── 설정 칸 ── */
const FIELDS = [
  ['#fTitle', 'title'], ['#fSubtitle', 'subtitle'], ['#fEdition', 'edition'], ['#fDate', 'date'],
  ['#fPublisher', 'publisher'], ['#fLang', 'lang'], ['#fNote', 'colophonNote'],
  ['#fSize', 'page.size'], ['#fW', 'page.w', Number], ['#fH', 'page.h', Number],
  ['#mTop', 'page.margin.top', Number], ['#mBottom', 'page.margin.bottom', Number],
  ['#mInner', 'page.margin.inner', Number], ['#mOuter', 'page.margin.outer', Number],
  ['#fFs', 'fs', Number], ['#fFonts', 'fonts'], ['#fColor', 'color'], ['#fBinding', 'binding'], ['#fFolioPos', 'folioPos'],
];
const CHECKS = [
  ['#pCover', 'parts.cover'], ['#pToc', 'parts.toc'], ['#pRunhead', 'parts.runhead'], ['#pFolio', 'parts.folio'],
  ['#pColophon', 'parts.colophon'], ['#pThumb', 'parts.thumb'], ['#pPack', 'pack'], ['#pGrid', 'grid'], ['#pFill', 'fill'], ['#pAlign', 'alignBands'], ['#pPad4', 'pad4'], ['#pMarks', 'output.marks'],
];
const getp = (o, path) => path.split('.').reduce((a, k) => a?.[k], o);
const setp = (o, path, v) => { const ks = path.split('.'); const last = ks.pop(); ks.reduce((a, k) => (a[k] ??= {}), o)[last] = v; };

function fillForm() {
  for (const [sel, path] of FIELDS) $(sel).value = getp(book, path) ?? '';
  for (const [sel, path] of CHECKS) $(sel).checked = !!getp(book, path);
  $('#fSize').closest('.form').classList.toggle('is-custom', book.page.size === 'custom');
}
function bindForm() {
  for (const [sel, path, conv] of FIELDS) {
    $(sel).addEventListener('change', (e) => {
      let v = e.target.value;
      if (conv) { v = conv(v); if (!Number.isFinite(v)) return fillForm(); }
      setp(book, path, v);
      if (path === 'page.size' && v !== 'custom') [book.page.w, book.page.h] = SIZES[v];
      fillForm();
      changed(false);
    });
  }
  for (const [sel, path] of CHECKS) $(sel).addEventListener('change', (e) => { setp(book, path, e.target.checked); changed(path === 'grid'); });
}

/* ── 그리기 ── */
let timer = 0, busy = false, again = false;
function changed(listsToo) {
  persist();
  if (listsToo) renderItems();
  clearTimeout(timer);
  timer = setTimeout(render, 450);
}

async function render() {
  if (busy) { again = true; return; }
  busy = true;
  const status = $('#status');
  try {
    const need = [...new Map(book.items.filter((it) => it.type === 'table').map((it) => [`${it.title}@${it.oldid}`, it])).values()];
    status.textContent = '자료를 불러오는 중…';
    await pool(need, 4, (it) => getDoc(it.title, it.oldid), (k, n) => { status.textContent = `자료를 불러오는 중… ${k} / ${n}`; });
    for (const el of [$('#sheets'), $('#measure')]) {
      el.classList.toggle('shaken', book.fonts === 'shaken');
      for (const f of ['antique', 'tokumin', 'shippori']) el.classList.toggle(`f-${f}`, book.fonts === f);
      el.classList.toggle('mono', book.color === 'mono');
    }
    if (book.fonts === 'shaken') await typesquare();
    await bookFonts(book.fonts);
    const r = await layoutBook(book, docs, $('#sheets'), $('#measure'), (t) => { status.textContent = `쪽을 짜는 중… ${t}`; });
    const marks = book.output.marks ? 30 : 0;
    $('#pagesize').textContent = `@page { size: ${r.size[0] + marks}mm ${r.size[1] + marks}mm; margin: 0; }`;
    status.textContent = `${r.pages}쪽 · ${r.size[0]}×${r.size[1]}mm${book.output.marks ? ' · 재단선' : ''}`;
    const w = $('#warn');
    w.hidden = !r.warnings.length;
    w.textContent = r.warnings.join(' / ');
    if (book.fonts === 'shaken' && window.Ts?.loadFont) window.Ts.loadFont();
    if (reading) showSpread(curSpread);
    fitZoom();
  } catch (e) {
    console.error(e);
    status.textContent = `그리지 못했다: ${e.message}`;
  } finally {
    busy = false;
    if (again) { again = false; render(); }
  }
}

/** 고른 글꼴 묶음만 받는다 (Google Fonts) */
const FONT_SETS = {
  antique: 'Shippori+Mincho+B1:wght@400;700&family=Zen+Kaku+Gothic+Antique:wght@400;700&family=Song+Myung',
  tokumin: 'Kaisei+Tokumin:wght@400;700&family=Shippori+Antique+B1&family=Gowun+Batang:wght@400;700',
  shippori: 'Shippori+Mincho:wght@400;700',
};
async function bookFonts(set) {
  const q = FONT_SETS[set];
  if (!q || document.querySelector(`link[data-set="${set}"]`)) return;
  const l = document.createElement('link');
  l.rel = 'stylesheet';
  l.href = `https://fonts.googleapis.com/css2?family=${q}&display=swap`;
  l.dataset.set = set;
  await new Promise((res) => { l.onload = l.onerror = res; document.head.appendChild(l); });
}

let tsLoading = null;
function typesquare() {
  if (window.Ts || tsLoading) return tsLoading || Promise.resolve();
  tsLoading = new Promise((res) => {
    const s = document.createElement('script');
    s.src = '//typesquare.com/accessor/ko/script/typesquare.js?ee85a1e0da0743cc9ca6031dd3b19c5d';
    s.charset = 'utf-8';
    s.onload = s.onerror = () => res();
    document.head.appendChild(s);
  });
  return tsLoading;
}

/* 펼쳐 보기: 마주 보는 두 쪽을 나란히 (오른쪽 철이면 오른쪽에서 왼쪽으로). 화면에만 */
const SPREAD_KEY = 'tt-print-spread';
function spreadView() {
  const on = $('#pvSpread').checked;
  $('#sheets').classList.toggle('spreads', on);
  $('#sheets').classList.toggle('rtl', on && book.binding === 'right');
  if (!reading) try { localStorage.setItem(SPREAD_KEY, on ? '1' : ''); } catch (e) { /* 저장 불가 */ }
}
try { $('#pvSpread').checked = localStorage.getItem(SPREAD_KEY) === '1'; } catch (e) { /* 없음 */ }
$('#pvSpread').addEventListener('change', () => { spreadView(); fitZoom(); });

/* 읽기: 한 번에 한 펼침면 (첫 쪽은 혼자). 왼쪽 철이면 → 가 다음, 오른쪽 철이면 ← 가 다음 */
let curSpread = 0;
const narrow = () => innerWidth < 760;   // 좁은 화면에서는 한 쪽씩
function spreadOf(i) { return narrow() ? i : i === 0 ? 0 : Math.floor((i + 1) / 2); }
function showSpread(k) {
  const sheets = [...document.querySelectorAll('#sheets .sheet')];
  if (!sheets.length) return;
  const last = spreadOf(sheets.length - 1);
  curSpread = Math.max(0, Math.min(last, k));
  const on = sheets.map((s, i) => { const c = spreadOf(i) === curSpread; s.classList.toggle('cur', c); return c ? i + 1 : 0; }).filter(Boolean);
  $('#pvPage').textContent = `${on.join('–')} / ${sheets.length}`;
}
function turn(d) { showSpread(curSpread + d); }
$('#pvPrev').onclick = () => turn(book.binding === 'right' ? 1 : -1);
$('#pvNext').onclick = () => turn(book.binding === 'right' ? -1 : 1);
addEventListener('keydown', (e) => {
  if (!reading || e.target.closest('input, textarea, select')) return;
  const rtl = book.binding === 'right';
  if (e.key === 'ArrowRight') turn(rtl ? -1 : 1);
  else if (e.key === 'ArrowLeft') turn(rtl ? 1 : -1);
  else if (e.key === 'PageDown' || e.key === ' ') turn(1);
  else if (e.key === 'PageUp') turn(-1);
  else if (e.key === 'Home') showSpread(0);
  else if (e.key === 'End') showSpread(1e9);
  else return;
  e.preventDefault();
});
$('#sheets').addEventListener('click', (e) => {   // 펼침면의 왼쪽 반을 누르면 왼쪽으로, 오른쪽 반이면 오른쪽으로 넘긴다
  if (!reading) return;
  const r = $('#sheets').getBoundingClientRect();
  const right = e.clientX > r.left + r.width / 2;
  const rtl = book.binding === 'right';
  turn(right !== rtl ? 1 : -1);
});

function fitZoom() {
  if (reading) { $('#pvSpread').checked = !narrow(); showSpread(curSpread); }
  spreadView();
  const v = $('#pvZoom').value;
  const P = book.page;
  const w = ((P.size === 'custom' ? P.w : SIZES[P.size][0]) + (book.output.marks ? 30 : 0)) * 96 / 25.4 * ($('#pvSpread').checked ? 2 : 1);
  let z = +v;
  if (v === 'fit') z = Math.min(reading ? 3 : 1, ($('.preview').clientWidth - 32) / w);
  if (v === 'fit' && reading) {   // 읽기: 펼침면이 화면 높이에 들게
    const h = ((P.size === 'custom' ? P.h : SIZES[P.size][1]) + (book.output.marks ? 30 : 0)) * 96 / 25.4;
    z = Math.min(z, (innerHeight - 49 - 40 - 28) / h);
  }
  $('#sheets').style.zoom = String(z);
}

/* ── 단추 ── */
$('#btnPrint').onclick = async () => { clearTimeout(timer); await render(); window.print(); };
$('#btnShare').onclick = async () => {
  const url = `${location.origin}${location.pathname}#read=${await packBook(book)}`;
  try { await navigator.clipboard.writeText(url); $('#status').textContent = '읽기 링크를 복사했다'; } catch (e) { prompt('읽기 링크', url); }
};
$('#btnPdf').onclick = async () => {
  const w = window.open('', '_blank');
  const url = `pdf.php?b=${await packBook(book)}`;
  if (w) w.location = url; else location.href = url;
};
$('#btnEdit').onclick = () => {
  if (!confirm('이 책을 편집기로 가져올까? 지금 편집 중이던 책은 바뀐다.')) return;
  reading = false;
  persist();
  location.href = location.pathname;
};
$('#btnSave').onclick = () => {
  const blob = new Blob([JSON.stringify(book, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${(book.title || '시각표').replace(/[\\/:*?"<>|]/g, '_')}.ttbook.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
};
$('#fileLoad').onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  try {
    const j = JSON.parse(await f.text());
    if (!(j.v >= 1 && j.v <= 3) || !Array.isArray(j.items)) throw new Error('설계도 파일이 아니다');
    book = merge(DEFAULT(), upgrade(j));
    fillForm();
    changed(true);
  } catch (err) { alert(`불러오지 못했다: ${err.message}`); }
  e.target.value = '';
};
$('#btnLatest').onclick = async () => {
  await refreshList();
  const latest = new Map(pageList.map((p) => [p.title, p.revid]));
  let n = 0;
  for (const it of book.items) {
    if (it.type === 'table' && latest.get(it.title) && latest.get(it.title) !== it.oldid) { it.oldid = latest.get(it.title); n++; }
  }
  $('#status').textContent = n ? `${n}개 표를 최신 판으로 바꿨다` : '모두 최신 판이다';
  changed(true);
};
$('#btnNew').onclick = () => {
  if (book.items.length && !confirm('지금 책을 비우고 새로 시작할까?')) return;
  book = DEFAULT();
  fillForm();
  changed(true);
};
$('#addDivider').onclick = () => { book.items.push({ type: 'divider', text: '', sub: '' }); changed(true); };
$('#addText').onclick = () => { book.items.push({ type: 'text', toc: '', text: '' }); changed(true); };
// 구역(중표지) 안의 표들을 노선·해·문서 안 차례로. 중표지와 글 쪽은 제자리
$('#sortItems').onclick = () => {
  const out = [];
  let run = [];
  const flush = () => { run.sort((a, b) => byTitle(a.title, b.title) || a.idx - b.idx); out.push(...run); run = []; };
  for (const it of book.items) {
    if (it.type === 'table') run.push(it);
    else { flush(); out.push(it); }
  }
  flush();
  book.items = out;
  changed(true);
};
// 찾은 시각표 문서의 표를 모두: 노선마다 쪽 없는 구역 하나, 노선·해 차례로
$('#addAll').onclick = async () => {
  const q = $('#srcFind').value.trim().toLowerCase();
  const list = pageList.filter((p) => p.ns === 3006 && (!q || p.title.toLowerCase().includes(q) || p.displaytitle.toLowerCase().includes(q)))
    .sort((a, b) => byTitle(a.title, b.title));
  if (!list.length) return;
  if (list.length > 5 && !confirm(`시각표 문서 ${list.length}개의 표를 모두 싣는다. 할까?`)) return;
  const status = $('#status');
  const got = await pool(list, 4, (p) => getDoc(p.title), (k, n) => { status.textContent = `문서를 받는 중… ${k} / ${n}`; });
  let line = null;
  const have = new Set(book.items.filter((it) => it.type === 'table').map((it) => `${it.title}#${it.idx}`));
  list.forEach((p, k) => {
    const d = got[k];
    if (!d || !d.tables.length) return;
    if (lineOf(p.title) !== line) {
      line = lineOf(p.title);
      book.items.push({ type: 'divider', text: line, sub: '', inline: true });
    }
    for (const t of d.tables) if (!have.has(`${p.title}#${t.idx}`)) book.items.push({ type: 'table', title: p.title, oldid: d.revid, idx: t.idx, label: defaultLabel(p.title, t), fit: 'split', scale: 100 });
  });
  changed(true);
};
$('#srcFind').addEventListener('input', renderSources);
$('#pvZoom').addEventListener('change', fitZoom);
addEventListener('resize', () => { clearTimeout(fitZoom.t); fitZoom.t = setTimeout(fitZoom, 150); });

async function refreshList() {
  pageList = (await api({ action: 'list' })).pages;
  renderSources();
  renderItems();
}

function esc(s) { return String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

/* ── 시작 ── */
bindForm();
fillForm();
renderItems();
refreshList().catch((e) => { $('#srcList').innerHTML = `<li class="loading">목록을 못 불러옴: ${esc(e.message)}</li>`; });
render();

// 시험용
window.ttprint = { get book() { return book; }, docs, render };
