/* 일로디스 — 화면. 사람은 언제나 0번 자리, 나머지는 CPU */
import * as E from './engine.js';
import * as AI from './ai.js';

const $ = (s) => document.querySelector(s);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const DELAY = new URLSearchParams(location.search).has('fast') ? 20 : 650;

const G = {
  N: 4, names: [], scores: [], round: 0, firstDealer: 0, st: null,
  mode: 'idle',        // 'take' | 'chi' | 'out' | 'busy'
  sel: null,           // 고른 폐패 id
  lastRiver: null,     // 방금 명패산에 놓인 패 id
};

/* ── 그리기 ───────────────────────────────────────────────────────── */

/* 패 앞면: 옛 서양 트럼프처럼 모서리에 수, 가운데에 문양을 수만큼. 작은 패는 수와 문양 하나만 */
const PIPS = {
  1: [[25, 35, 17]],
  2: [[25, 18], [25, 52]],
  3: [[25, 17], [25, 35], [25, 53]],
  4: [[18, 18], [32, 18], [18, 52], [32, 52]],
  5: [[18, 18], [32, 18], [25, 35], [18, 52], [32, 52]],
  6: [[18, 18], [32, 18], [18, 35], [32, 35], [18, 52], [32, 52]],
  7: [[18, 17], [32, 17], [25, 26], [18, 35], [32, 35], [18, 53], [32, 53]],
  8: [[18, 16], [32, 16], [25, 25.5], [18, 35], [32, 35], [25, 44.5], [18, 54], [32, 54]],
  9: [[17, 15], [33, 15], [17, 28], [33, 28], [25, 35], [17, 42], [33, 42], [17, 55], [33, 55]],
};
const use = (s, x, y, w, cls = '') => `<use href="#suit${s}"${cls ? ` class="${cls}"` : ''} x="${x - w / 2}" y="${y - w / 2}" width="${w}" height="${w}"/>`;
/* ◇ 의 5·9 는 가운데 문양 하나를 초록으로 (마작 녹일색의 5·9삭처럼, 적일색에 들지 않는 패) */
const oddMid = (c) => c.s === E.RED && (c.n === 5 || c.n === 9);
function faceSVG(c, sm) {
  const body = sm
    ? `<text class="num big" x="25" y="37" text-anchor="middle">${c.n}</text>${use(c.s, 25, 51, 13, oddMid(c) ? 'alt' : '')}`
    : `<g class="idx"><text class="num" x="7" y="14.5" text-anchor="middle">${c.n}</text>${use(c.s, 7, 20.5, 6)}</g>`
      + `<g class="idx" transform="rotate(180 25 35)"><text class="num" x="7" y="14.5" text-anchor="middle">${c.n}</text>${use(c.s, 7, 20.5, 6)}</g>`
      + PIPS[c.n].map(([x, y, w = 9.2]) => use(c.s, x, y, w, oddMid(c) && x === 25 && y === 35 ? 'alt' : '')).join('');
  return `<svg viewBox="0 0 50 70" aria-hidden="true"><rect class="face" x="0.6" y="0.6" width="48.8" height="68.8" rx="3"/>${body}</svg>`;
}
const BACK_SVG = '<svg viewBox="0 0 50 70" aria-hidden="true"><rect class="face" x="0.6" y="0.6" width="48.8" height="68.8" rx="3"/>'
  + '<rect class="lattice" x="4.5" y="4.5" width="41" height="61" rx="1"/><rect class="frame" x="4.5" y="4.5" width="41" height="61" rx="1"/></svg>';

function cardEl(c, { sm = false, cls = '' } = {}) {
  const el = document.createElement('span');
  el.className = `card${c.s === E.RED ? ' red' : ''}${sm ? ' sm' : ''} ${cls}`.trim();
  el.innerHTML = faceSVG(c, sm);
  el.setAttribute('role', 'img');
  el.setAttribute('aria-label', `${c.n}${E.SUITS[c.s]}`);
  el.dataset.id = c.id;
  return el;
}
function backEl(sm = true) {
  const el = document.createElement('span');
  el.className = `card back${sm ? ' sm' : ''}`;
  el.innerHTML = BACK_SVG;
  return el;
}
/* 글 속의 패: 수 + 작은 문양 그림 (● 같은 글자는 글꼴마다 크기가 들쭉날쭉해서) */
const cardText = (c) => `<span class="ct${c.s === E.RED ? ' r' : ''}">${c.n}<svg class="cs" viewBox="0 0 10 10" aria-label="${E.SUITS[c.s]}"><use href="#suit${c.s}"/></svg></span>`;
const cardsHTML = (cs, sm = true) => {
  const w = document.createElement('span');
  w.className = 'kans';
  cs.forEach((c) => w.appendChild(cardEl(c, { sm })));
  return w.outerHTML;
};

function kanEl(kan, { sm, idx, owner }) {
  const el = document.createElement('div');
  el.className = `kan${sm ? ' sm' : ' md'}${kan.length === 3 ? ' full' : ''}`;
  el.dataset.kan = idx;
  kan.forEach((c) => {
    const ce = cardEl(c, { sm });
    // 奪: 내 차례(取)에 남의 다 차지 않은 칸의 패 중 빼앗을 수 있는 것
    if (owner !== 0 && G.mode === 'take' && kan.length < 3 && stealsFor(c.id).length) {
      ce.classList.add('click');
      ce.onclick = () => askSteal(c.id);
    }
    if (c.id === G.lastRiver) ce.classList.add('new');
    el.appendChild(ce);
  });
  return el;
}

/** 음수는 긴 빼기표 − 로 */
const num = (v) => (v < 0 ? `−${-v}` : `${v}`);

/** 目次처럼: 이름 ……… 점수 */
function whoHTML(p, extra) {
  const st = G.st;
  const turn = st.turn === p && st.phase !== 'end';
  return `<div class="who${turn ? ' turn' : ''}"><span class="nm">${G.names[p]}${st.dealer === p ? '<span class="oya">親</span>' : ''}</span>`
    + `${extra ? `<span class="ex">${extra}</span>` : ''}<span class="lead"></span><span class="pt">${num(G.scores[p])}점</span></div>`;
}

/* TypeSquare 는 읽어 들인 때의 글자만 받아 오므로, 새로 그린 뒤 잠시 있다가 다시 부른다 */
let tsTimer = 0;
const tsReload = () => { clearTimeout(tsTimer); tsTimer = setTimeout(() => window.Ts && Ts.loadFont && Ts.loadFont(), 900); };

function render() {
  const st = G.st;
  if (!st) return;
  tsReload();
  $('#info').innerHTML = `제${G.round + 1}국 <span>/ ${G.N}국</span>`;

  // 상대
  const opps = $('#opps');
  opps.innerHTML = '';
  for (let p = 1; p < G.N; p++) {
    const pl = st.players[p];
    const row = document.createElement('div');
    row.className = 'opp';
    row.innerHTML = whoHTML(p, `<span data-tip="손에 든 패">폐패 ${pl.closed.length}</span>`);
    const ks = document.createElement('div');
    ks.className = 'kans';
    pl.kans.forEach((k, i) => ks.appendChild(kanEl(k, { sm: true, idx: i, owner: p })));
    row.appendChild(ks);
    opps.appendChild(row);
  }

  // 가운데
  $('#wallCnt').textContent = `${st.wall.length}장`;
  $('#riverCnt').textContent = `${st.river.length}장`;
  const top = st.river[st.river.length - 1];
  const rt = $('#riverTop');
  rt.innerHTML = '';
  if (top) rt.appendChild(cardEl(top, { cls: top.id === G.lastRiver ? 'new' : '' }));
  else { const g = backEl(false); g.classList.add('ghost'); rt.appendChild(g); }
  const canWall = G.mode === 'take' && st.wall.length > 0;
  const canRiver = G.mode === 'take' && !!top;
  $('#wall').classList.toggle('click', canWall);
  $('#river').classList.toggle('click', canRiver);
  $('#wall').disabled = !canWall;
  $('#river').disabled = !canRiver;

  // 나
  const me = st.players[0];
  $('#meName').innerHTML = whoHTML(0, '');
  const mk = $('#myKans');
  mk.innerHTML = '';
  const placeTo = G.mode === 'out' && G.sel != null ? outActsFor(G.sel).filter((a) => a.type === 'place').map((a) => a.kan) : [];
  me.kans.forEach((k, i) => {
    const el = kanEl(k, { sm: false, idx: i, owner: 0 });
    if (placeTo.includes(i)) {
      el.classList.add('target');
      el.onclick = () => doOut(outActsFor(G.sel).find((a) => a.type === 'place' && a.kan === i));
    }
    mk.appendChild(el);
  });
  const hand = $('#hand');
  hand.innerHTML = '';
  E.sortCards(me.closed).forEach((c) => {
    const el = cardEl(c);
    if (st.took && st.took.card && st.took.card.id === c.id && st.turn === 0) el.classList.add('new');
    if (G.mode === 'out') {
      el.classList.add('pick');
      if (G.sel === c.id) el.classList.add('sel');
      el.onclick = () => { G.sel = G.sel === c.id ? null : c.id; render(); };
    }
    hand.appendChild(el);
  });
  renderActs();
  renderLog();
}

function renderActs() {
  const box = $('#acts');
  box.innerHTML = '';
  const st = G.st;
  const add = (text, fn, cls = '', tip = '') => {
    const b = document.createElement('button');
    b.type = 'button';
    b.innerHTML = text;
    if (cls) b.className = cls;
    if (tip) b.dataset.tip = tip;
    b.onclick = fn;
    box.appendChild(b);
  };
  const hint = (t, tip = '') => { const s = document.createElement('span'); s.className = 'hint'; s.innerHTML = t; if (tip) s.dataset.tip = tip; box.appendChild(s); };

  if (G.mode === 'take') {
    hint('취', '패산에서 한 장 가져오거나, 점선 테두리의 남의 패를 탈한다. 탈은 패가 놓인 내 칸으로만');
  } else if (G.mode === 'chi') {
    const o = G.chiOpts[0];
    add(`치 · 화료 ${o.ev.total}점`, () => doChi(o), 'primary', o.ev.yaku.map((y) => y.name).join(' · '));
    add('넘기기', () => { G.mode = 'out'; afterTakeOut(); }, '', '치하지 않고 출로');
  } else if (G.mode === 'out') {
    if (G.sel == null) { hint('출', '폐패 한 장을 고른다'); return; }
    const acts = outActsFor(G.sel);
    const c = st.players[0].closed.find((x) => x.id === G.sel);
    for (const a of acts) {
      if (a.type === 'place') add(a.win ? `칸 ${a.kan + 1} · 화료 ${a.win.total}점` : `칸 ${a.kan + 1}`, () => doOut(a), a.win ? 'primary' : '',
        a.win ? a.win.yaku.map((y) => y.name).join(' · ') : '');
    }
    add('명패산', () => doOut(acts.find((a) => a.type === 'discard')));
    for (const a of acts) {
      if (a.type !== 'swap') continue;
      const o = st.players[0].kans[a.kan].find((x) => x.id === a.outId);
      add(`환 ${cardText(o)}`, () => doOut(a), '', `칸 ${a.kan + 1}의 ${o.n}${E.SUITS[o.s]}와 바꾼다. 빠진 패는 명패산으로`);
    }
  } else if (st && st.phase !== 'end' && st.turn !== 0) {
    hint(`${G.names[st.turn]}의 차례`);
  }
}

/* 기록: 패 이름 뒤에 조사를 붙이지 않는다 (수에 따라 을/를, 로/으로가 갈려서) */
const LOGTXT = {
  wall: () => '암패산에서 취',
  river: (e) => `명패산에서 ${cardText(e.card)} 취`,
  steal: (e) => `${G.names[e.from]}에게서 ${cardText(e.card)} 탈`,
  place: (e) => `${cardText(e.card)} → 칸 ${e.kan + 1}`,
  discard: (e) => `${cardText(e.card)} → 명패산`,
  swap: (e) => `환: 칸 ${e.kan + 1}의 ${cardText(e.out)} ↔ ${cardText(e.card)}`,
  ron: (e) => `${G.names[e.from]}에게서 ${cardText(e.card)} 영화`,
  win: (e) => `화료 ${e.total}점`,
  draw: () => '유국',
};
function renderLog() {
  const ol = $('#log');
  const items = G.st.log.slice(-40);
  ol.innerHTML = items.map((e) => `<li>${e.p != null ? `<b>${G.names[e.p]}</b> ` : ''}${(LOGTXT[e.t] || (() => e.t))(e)}</li>`).join('');
  ol.scrollTop = ol.scrollHeight;
}
const say = (t) => { $('#msg').innerHTML = t; };

/* ── 사람의 차례 ──────────────────────────────────────────────────── */

const stealsFor = (cardId) => {
  const st = G.st;
  const kan = st.players.flatMap((pl) => pl.kans).find((k) => k.some((c) => c.id === cardId));
  if (!kan) return [];
  const card = kan.find((c) => c.id === cardId);
  // 같은 칸의 같은 패면 어느 쪽이든 같으므로 key 로 묶는다
  return (G.steals || []).filter((a) => {
    const x = st.players[a.from].kans[a.fromKan].find((c) => c.id === a.cardId);
    return st.players[a.from].kans[a.fromKan] === kan && E.key(x) === E.key(card);
  });
};

function outActsFor(id) {
  const st = G.st;
  const me = st.players[0];
  const c = me.closed.find((x) => x.id === id);
  if (!c) return [];
  // legalOuts 는 같은 패를 하나로 묶으므로, 고른 패와 같은 패의 행동을 고른 패의 id 로 바꿔 쓴다
  return G.outs.filter((a) => E.key(me.closed.find((x) => x.id === a.id)) === E.key(c)).map((a) => ({ ...a, id }));
}

function humanTake() {
  const st = G.st;
  G.steals = E.stealOptions(st, 0);
  const takes = E.legalTakes(st, 0);
  if (!takes.length) { say('취 없음'); afterTake(); return; }
  G.mode = 'take';
  say('');
  render();
}

function askSteal(cardId) {
  const opts = stealsFor(cardId);
  if (!opts.length) return;
  if (opts.length === 1) { doTake(opts[0]); return; }
  const st = G.st;
  const me = st.players[0];
  const x = st.players[opts[0].from].kans[opts[0].fromKan].find((c) => c.id === cardId);
  const seen = new Set();
  const uniq = opts.filter((a) => {
    const k = a.kan + '/' + a.ids.map((id) => E.key(me.closed.find((c) => c.id === id))).sort().join(',');
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  modal(`<h2>탈 ${cardText(x)}</h2><p class="sub">놓을 칸</p>` + uniq.map((a, i) => {
    const cs = me.kans[a.kan].concat([x], a.ids.map((id) => me.closed.find((c) => c.id === id)));
    return `<button type="button" class="opt" data-i="${i}">칸 ${a.kan + 1}: ${cardsHTML(cs)}</button>`;
  }).join('') + '<div class="row"><button type="button" data-x>그만두기</button></div>', (el) => {
    el.querySelectorAll('.opt').forEach((b) => (b.onclick = () => { closeModal(); doTake(uniq[+b.dataset.i]); }));
    el.querySelector('[data-x]').onclick = closeModal;
  });
}

function doTake(a) {
  if (G.mode !== 'take') return;
  G.mode = 'busy';
  const r = E.applyTake(G.st, 0, a);
  if (r) return endRound();
  afterTake();
}

function afterTake() {
  const st = G.st;
  st.phase = 'out';
  G.chiOpts = E.chiOptions(st, 0);
  if (G.chiOpts.length) { G.mode = 'chi'; say(''); render(); return; }
  afterTakeOut();
}

function afterTakeOut() {
  const st = G.st;
  G.outs = E.legalOuts(st, 0);
  if (!G.outs.length) { say('출 없음'); G.mode = 'busy'; render(); return finishTurn(0, {}); }
  G.mode = 'out';
  G.sel = null;
  say('');
  render();
}

function doChi(o) {
  G.mode = 'busy';
  E.applyChi(G.st, 0, o);
  endRound();
}

function doOut(a) {
  if (!a || G.mode !== 'out') return;
  G.mode = 'busy';
  G.sel = null;
  const res = E.applyOut(G.st, 0, a);
  if (res.win) return endRound();
  finishTurn(0, res);
}

/* ── 차례 진행 ────────────────────────────────────────────────────── */

async function finishTurn(p, res) {
  const st = G.st;
  if (res.river) {
    G.lastRiver = res.river.id;
    render();
    if (await ronCheck(p)) return endRound();
  }
  if (E.nextTurn(st)) return endRound();
  step();
}

/** 榮和: 둔 사람의 다음 차례부터 가까운 순으로 */
async function ronCheck(from) {
  const st = G.st;
  for (const c of E.ronCandidates(st, from)) {
    if (c.p === 0) {
      const ok = await confirmRon(c.opt, st.river[st.river.length - 1]);
      if (!ok) continue;
    } else await wait(DELAY);
    E.applyRon(st, c.p, from, c.opt);
    return true;
  }
  return false;
}

function confirmRon(opt, card) {
  return new Promise((res) => {
    modal(`<h2>영화?</h2><p class="sub">${cardText(card)} · 화료할 수 있다</p>
      <div class="sets">${G.st.players[0].kans.map((k, i) => cardsHTML(k.concat(opt.add[i].map((id) => id === card.id ? card : G.st.players[0].closed.find((c) => c.id === id))))).join('')}</div>
      <p>${opt.ev.yaku.map((y) => y.name).join(' · ')} — ${opt.ev.total}점 × ${G.N - 1}</p>
      <div class="row"><button type="button" class="primary" data-y>영화</button><button type="button" data-n>넘기기</button></div>`, (el) => {
      el.querySelector('[data-y]').onclick = () => { closeModal(); res(true); };
      el.querySelector('[data-n]').onclick = () => { closeModal(); res(false); };
    });
  });
}

async function step() {
  const st = G.st;
  render();
  if (st.phase === 'end') return endRound();
  const p = st.turn;
  if (p === 0) return humanTake();
  G.mode = 'busy';
  say(`${G.names[p]}…`);
  render();
  await wait(DELAY);
  const t = AI.chooseTake(st, p);
  if (t) {
    if (E.applyTake(st, p, t)) return endRound();
  } else st.phase = 'out';
  render();
  await wait(DELAY * 0.6);
  const chi = AI.chooseChi(st, p);
  if (chi) { E.applyChi(st, p, chi); return endRound(); }
  if (!st.players[p].closed.length) return finishTurn(p, {});
  const a = AI.chooseOut(st, p);
  const res = E.applyOut(st, p, a);
  if (res.win) return endRound();
  return finishTurn(p, res);
}

/* ── 국 · 판 ──────────────────────────────────────────────────────── */

function startMatch(N) {
  G.N = N;
  G.names = ['나', ...Array.from({ length: N - 1 }, (_, i) => `CPU ${i + 1}`)];
  G.scores = Array(N).fill(0);
  G.round = 0;
  G.firstDealer = Math.floor(Math.random() * N);
  $('#start').hidden = true;
  $('#table').hidden = false;
  startRound();
}

function startRound() {
  const dealer = (G.firstDealer + G.round) % G.N;
  G.st = E.newRound(G.N, dealer);
  G.lastRiver = null;
  G.sel = null;
  say(`제${G.round + 1}국`);
  step();
}

const HOW = { place: '전', steal: '탈 (전)', chi: '치', ron: '영화' };

function endRound() {
  const st = G.st;
  G.mode = 'busy';
  const pay = E.settle(st);
  pay.forEach((v, i) => (G.scores[i] += v));
  render();
  const r = st.result;
  const last = G.round + 1 >= G.N;
  let html;
  if (r.type === 'win') {
    const pl = st.players[r.p];
    html = `<h2>${G.names[r.p]} 화료</h2><p class="sub">${HOW[r.how]}${r.how === 'ron' ? ` · ${G.names[r.from]}에게서` : ''}</p>
      <div class="sets">${pl.kans.map((k) => `<span class="kan sm full">${k.map((c) => cardEl(c, { sm: true }).outerHTML).join('')}</span>`).join('')}</div>
      <ul class="toc">${r.ev.yaku.map((y) => `<li><span>${y.name} <small>${y.hanja}</small>${y.ex ? ' <small>배타역</small>' : ''}</span><i></i><span>${y.pts}</span></li>`).join('')}
      ${r.ev.exclusive ? '' : `<li><span>조 <small>${r.ev.sets.map((t) => E.SET_NAME[t]).join(' · ')}</small></span><i></i><span>${r.ev.setPts}</span></li>`}
      <li class="sum"><span>합계</span><i></i><span>${r.ev.total}점</span></li></ul>`;
  } else html = '<h2>유국</h2>';
  html += `<ul class="toc pay">${G.names.map((n, i) => `<li><span>${n}</span><i></i><span class="${pay[i] > 0 ? 'plus' : pay[i] < 0 ? 'minus' : ''}">${pay[i] > 0 ? '+' : pay[i] < 0 ? '−' : '±'}${Math.abs(pay[i])}</span><span class="tot">${num(G.scores[i])}</span></li>`).join('')}</ul>`;
  html += `<div class="row"><button type="button" class="primary" data-next>${last ? '판 끝' : '다음 국'}</button></div>`;
  setTimeout(() => modal(html, (el) => {
    el.querySelector('[data-next]').onclick = () => {
      closeModal();
      if (last) return showFinal();
      G.round++;
      startRound();
    };
  }), 500);
}

function showFinal() {
  const order = G.names.map((n, i) => ({ n, s: G.scores[i] })).sort((a, b) => b.s - a.s);
  const top = order[0].s;
  const winners = order.filter((o) => o.s === top).map((o) => o.n);
  modal(`<h2>판 끝</h2><p class="sub">${winners.join(', ')} 승리</p>
    <ul class="toc">${order.map((o, i) => `<li><span>${i + 1}. ${o.n}</span><i></i><span>${num(o.s)}점</span></li>`).join('')}</ul>
    <div class="row"><button type="button" class="primary" data-again>한 판 더</button><button type="button" data-menu>처음으로</button></div>`, (el) => {
    el.querySelector('[data-again]').onclick = () => { closeModal(); startMatch(G.N); };
    el.querySelector('[data-menu]').onclick = () => { closeModal(); $('#table').hidden = true; $('#start').hidden = false; $('#info').textContent = ''; };
  });
}

/* ── 창 ───────────────────────────────────────────────────────────── */

function modal(html, bind) {
  $('#modalBox').innerHTML = html;
  $('#modal').hidden = false;
  bind && bind($('#modalBox'));
}
function closeModal() { $('#modal').hidden = true; }

/* ── 시작 ─────────────────────────────────────────────────────────── */

$('#wall .card').innerHTML = BACK_SVG;

/* ── 풀이(툴팁): data-tip. 마우스는 올리면, 손가락은 길게 누르면 ── */
const tipEl = document.createElement('div');
tipEl.id = 'tip';
tipEl.hidden = true;
document.body.appendChild(tipEl);
let tipTimer = 0, tipEat = false;
function showTip(el) {
  tipEl.textContent = el.dataset.tip;
  tipEl.hidden = false;
  const r = el.getBoundingClientRect(), w = tipEl.offsetWidth, h = tipEl.offsetHeight;
  const x = Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2));
  const y = r.top - h - 8 < 8 ? r.bottom + 8 : r.top - h - 8;
  tipEl.style.left = `${x}px`;
  tipEl.style.top = `${y}px`;
}
const hideTip = () => { clearTimeout(tipTimer); tipEl.hidden = true; };
document.addEventListener('pointerover', (e) => {
  const el = e.target.closest('[data-tip]');
  if (!el || e.pointerType !== 'mouse') return;
  clearTimeout(tipTimer);
  tipTimer = setTimeout(() => showTip(el), 250);
});
document.addEventListener('pointerout', (e) => { if (e.pointerType === 'mouse' && e.target.closest('[data-tip]')) hideTip(); });
document.addEventListener('pointerdown', (e) => {
  hideTip();
  const el = e.target.closest('[data-tip]');
  if (!el || e.pointerType === 'mouse') return;
  tipTimer = setTimeout(() => { showTip(el); tipEat = true; }, 450);
});
document.addEventListener('pointerup', () => clearTimeout(tipTimer));
document.addEventListener('pointercancel', () => clearTimeout(tipTimer));
// 길게 눌러 풀이를 본 뒤의 누름은 행동으로 치지 않는다
document.addEventListener('click', (e) => { if (tipEat) { tipEat = false; e.stopPropagation(); e.preventDefault(); } }, true);
document.addEventListener('scroll', hideTip, true);
document.querySelectorAll('#start [data-n]').forEach((b) => (b.onclick = () => startMatch(+b.dataset.n)));
$('#wall').onclick = () => G.mode === 'take' && doTake({ type: 'wall' });
$('#river').onclick = () => G.mode === 'take' && G.st.river.length && doTake({ type: 'river' });

// 시험용: 콘솔에서 상태를 볼 수 있게
window.ilodici = G;
