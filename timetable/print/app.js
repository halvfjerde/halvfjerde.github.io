/* 시각표 인쇄 — 고르기·설정·미리보기 */
import { layoutBook, extractTables, defaultLabel, shortTitle, SIZES } from './layout.js?v=3';

const $ = (s) => document.querySelector(s);
const KEY = 'tt-print-book-v1';
const API = 'api.php';

const today = () => { const d = new Date(); return `${d.getFullYear()}. ${d.getMonth() + 1}. ${d.getDate()}.`; };
const DEFAULT = () => ({
  v: 1, title: '시각표', subtitle: '', edition: '', date: today(), publisher: '', lang: 'ko', colophonNote: '',
  page: { size: 'B5', w: 182, h: 257, margin: { top: 14, bottom: 14, inner: 16, outer: 12 } },
  fs: 8, fonts: 'free', color: 'color',
  parts: { cover: true, toc: true, runhead: true, folio: true, colophon: true },
  pack: true, grid: true, alignBands: false, pad4: false, output: { marks: false },
  items: [],
});

/* ── 상태 ── */
let book = load() || DEFAULT();
const docs = new Map();          // 'title@revid' → { title, revid, timestamp, latest, tables }
let pageList = [];               // 위키의 시각표 문서들
const open = new Set();          // 펼친 문서

function load() {
  try { const j = JSON.parse(localStorage.getItem(KEY) || 'null'); return j && j.v === 1 ? merge(DEFAULT(), j) : null; } catch (e) { return null; }
}
function persist() { try { localStorage.setItem(KEY, JSON.stringify(book)); } catch (e) { /* 저장 불가 */ } }
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

async function getDoc(title, oldid) {
  const key = `${title}@${oldid || 'latest'}`;
  if (docs.has(key)) return docs.get(key);
  const j = await api(oldid ? { action: 'page', title, oldid } : { action: 'page', title });
  const d = { title: j.title, revid: j.revid, timestamp: j.timestamp, latest: j.latest, tables: extractTables(j.html) };
  docs.set(`${title}@${j.revid}`, d);
  if (!oldid) docs.set(key, d);
  return d;
}

/* ── 자료 목록 ── */
const NS_ORDER = { 3006: 0 };
function renderSources() {
  const q = $('#srcFind').value.trim().toLowerCase();
  const ul = $('#srcList');
  ul.innerHTML = '';
  const list = pageList
    .filter((p) => !q || p.title.toLowerCase().includes(q) || p.displaytitle.toLowerCase().includes(q))
    .sort((a, b) => (NS_ORDER[a.ns] ?? 9) - (NS_ORDER[b.ns] ?? 9) || a.title.localeCompare(b.title, 'ko'));
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
const FIT = [['split', '나누기'], ['shrink', '줄여 맞추기'], ['spread', '펼침면']];
function renderItems() {
  const ol = $('#items');
  ol.innerHTML = '';
  $('#itemCount').textContent = book.items.length ? `${book.items.length}개` : '자료에서 표를 더한다';
  const latest = new Map(pageList.map((p) => [p.title, p.revid]));
  const grid = book.grid !== false;
  book.items.forEach((it, i) => {
    const li = document.createElement('li');
    const body = document.createElement('div');
    body.className = 'body';
    if (it.type === 'table') {
      const old = latest.get(it.title) && latest.get(it.title) > it.oldid;
      body.innerHTML = `<input type="text" data-k="label" value="${esc(it.label)}" title="차례와 머리글에 쓰는 이름">
        <div class="meta">${esc(shortTitle(it.title))} · 판 ${it.oldid}${old ? ' <span class="old">· 더 새 판 있음</span>' : ''}</div>
        <div class="opts"><select data-k="fit">${FIT.filter(([v]) => !(grid && v === 'shrink') || it.fit === v).map(([v, t]) => `<option value="${v}"${it.fit === v ? ' selected' : ''}>${t}${grid && v === 'shrink' ? ' (격자에서는 나누기)' : ''}</option>`).join('')}</select>
        <input type="number" data-k="scale" min="40" max="150" step="5" value="${it.scale || 100}"${grid ? ' disabled title="격자에 맞출 때는 책 전체가 같은 글자 크기"' : ' title="글자 크기 (%)"'}></div>`;
    } else if (it.type === 'divider') {
      body.innerHTML = `<input type="text" data-k="text" value="${esc(it.text || '')}" placeholder="중표지 제목">
        <input type="text" data-k="sub" value="${esc(it.sub || '')}" placeholder="작은 글 (없어도 됨)">`;
    } else {
      body.innerHTML = `<input type="text" data-k="toc" value="${esc(it.toc || '')}" placeholder="차례에 올릴 이름 (없으면 안 올림)">
        <textarea data-k="text" rows="4" placeholder="빈 줄로 문단을 나눈다. '# '는 제목, '- '는 목록">${esc(it.text || '')}</textarea>`;
    }
    body.querySelectorAll('[data-k]').forEach((el) => {
      el.addEventListener('change', () => {
        const k = el.dataset.k;
        it[k] = k === 'scale' ? Math.max(40, Math.min(150, +el.value || 100)) : el.value;
        changed(false);
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
  ['#fFs', 'fs', Number], ['#fFonts', 'fonts'], ['#fColor', 'color'],
];
const CHECKS = [
  ['#pCover', 'parts.cover'], ['#pToc', 'parts.toc'], ['#pRunhead', 'parts.runhead'], ['#pFolio', 'parts.folio'],
  ['#pColophon', 'parts.colophon'], ['#pPack', 'pack'], ['#pGrid', 'grid'], ['#pAlign', 'alignBands'], ['#pPad4', 'pad4'], ['#pMarks', 'output.marks'],
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
    const need = book.items.filter((it) => it.type === 'table');
    status.textContent = '자료를 불러오는 중…';
    await Promise.all(need.map((it) => getDoc(it.title, it.oldid).catch((e) => { console.warn(e); })));
    for (const el of [$('#sheets'), $('#measure')]) {
      el.classList.toggle('shaken', book.fonts === 'shaken');
      el.classList.toggle('mono', book.color === 'mono');
    }
    if (book.fonts === 'shaken') await typesquare();
    const r = await layoutBook(book, docs, $('#sheets'), $('#measure'), (t) => { status.textContent = `쪽을 짜는 중… ${t}`; });
    const marks = book.output.marks ? 30 : 0;
    $('#pagesize').textContent = `@page { size: ${r.size[0] + marks}mm ${r.size[1] + marks}mm; margin: 0; }`;
    status.textContent = `${r.pages}쪽 · ${r.size[0]}×${r.size[1]}mm${book.output.marks ? ' · 재단선' : ''}`;
    const w = $('#warn');
    w.hidden = !r.warnings.length;
    w.textContent = r.warnings.join(' / ');
    if (book.fonts === 'shaken' && window.Ts?.loadFont) window.Ts.loadFont();
    fitZoom();
  } catch (e) {
    console.error(e);
    status.textContent = `그리지 못했다: ${e.message}`;
  } finally {
    busy = false;
    if (again) { again = false; render(); }
  }
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

function fitZoom() {
  const v = $('#pvZoom').value;
  const P = book.page;
  const w = ((P.size === 'custom' ? P.w : SIZES[P.size][0]) + (book.output.marks ? 30 : 0)) * 96 / 25.4;
  let z = +v;
  if (v === 'fit') z = Math.min(1, ($('.preview').clientWidth - 32) / w);
  $('#sheets').style.zoom = String(z);
}

/* ── 단추 ── */
$('#btnPrint').onclick = async () => { clearTimeout(timer); await render(); window.print(); };
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
    if (j.v !== 1 || !Array.isArray(j.items)) throw new Error('설계도 파일이 아니다');
    book = merge(DEFAULT(), j);
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
