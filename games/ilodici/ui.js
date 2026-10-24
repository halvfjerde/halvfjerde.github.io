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

function cardEl(c, { sm = false, cls = '' } = {}) {
  const el = document.createElement('span');
  el.className = `card${c.s === E.RED ? ' red' : ''}${sm ? ' sm' : ''} ${cls}`.trim();
  el.innerHTML = `${c.n}<i>${E.SUITS[c.s]}</i>`;
  el.dataset.id = c.id;
  return el;
}
function backEl(sm = true) {
  const el = document.createElement('span');
  el.className = `card back${sm ? ' sm' : ''}`;
  return el;
}
const cardText = (c) => `<span class="${c.s === E.RED ? 'minus' : ''}">${c.n}${E.SUITS[c.s]}</span>`;
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

function render() {
  const st = G.st;
  if (!st) return;
  $('#info').textContent = `제${G.round + 1}국 / ${G.N}국 · ${G.names[st.dealer]} 친`;

  // 상대
  const opps = $('#opps');
  opps.innerHTML = '';
  for (let p = 1; p < G.N; p++) {
    const pl = st.players[p];
    const row = document.createElement('div');
    row.className = `opp${st.turn === p && st.phase !== 'end' ? ' turn' : ''}`;
    row.innerHTML = `<div class="who"><b>${G.names[p]}${st.dealer === p ? '<span class="oya">親</span>' : ''}</b><span>${G.scores[p]}점</span></div>`;
    const cn = document.createElement('span');
    cn.className = 'closedn';
    cn.appendChild(backEl());
    cn.append(`×${pl.closed.length}`);
    row.appendChild(cn);
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
  $('#me').classList.toggle('turn', st.turn === 0 && st.phase !== 'end');
  $('#meName').innerHTML = `<b>${G.names[0]}</b>${st.dealer === 0 ? '<span class="oya">親</span>' : ''} · ${G.scores[0]}점`;
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
  const add = (text, fn, cls = '') => {
    const b = document.createElement('button');
    b.type = 'button';
    b.innerHTML = text;
    if (cls) b.className = cls;
    b.onclick = fn;
    box.appendChild(b);
  };
  const hint = (t) => { const s = document.createElement('span'); s.className = 'hint'; s.innerHTML = t; box.appendChild(s); };

  if (G.mode === 'take') {
    hint('取: 암패산이나 명패산을 누르거나, 노란 테두리의 남의 개패를 눌러 奪');
  } else if (G.mode === 'chi') {
    const o = G.chiOpts[0];
    add(`置 하여 화료 (${o.ev.total}점)`, () => doChi(o), 'primary');
    add('置 하지 않고 계속', () => { G.mode = 'out'; afterTakeOut(); });
  } else if (G.mode === 'out') {
    if (G.sel == null) { hint('出: 폐패 한 장을 고른다'); return; }
    const acts = outActsFor(G.sel);
    const c = st.players[0].closed.find((x) => x.id === G.sel);
    for (const a of acts) {
      if (a.type === 'place') add(a.win ? `칸 ${a.kan + 1}에 놓고 화료 (${a.win.total}점)` : `칸 ${a.kan + 1}에 놓기`, () => doOut(a), a.win ? 'primary' : '');
    }
    add('명패산에 내놓기', () => doOut(acts.find((a) => a.type === 'discard')));
    for (const a of acts) {
      if (a.type !== 'swap') continue;
      const o = st.players[0].kans[a.kan].find((x) => x.id === a.outId);
      add(`換: 칸 ${a.kan + 1}의 ${cardText(o)} ↔ ${cardText(c)}`, () => doOut(a));
    }
  } else if (st && st.phase !== 'end' && st.turn !== 0) {
    hint(`${G.names[st.turn]}의 차례`);
  }
}

const LOGTXT = {
  wall: () => '암패산에서 取',
  river: (e) => `명패산의 ${cardText(e.card)}을 取`,
  steal: (e) => `${G.names[e.from]}의 ${cardText(e.card)}을 奪`,
  place: (e) => `${cardText(e.card)}을 칸 ${e.kan + 1}에`,
  discard: (e) => `${cardText(e.card)}을 명패산에`,
  swap: (e) => `換: 칸 ${e.kan + 1}의 ${cardText(e.out)}를 ${cardText(e.card)}로`,
  ron: (e) => `${G.names[e.from]}의 ${cardText(e.card)}으로 榮和`,
  win: (e) => `화료 (${e.total}점)`,
  draw: () => '流局',
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
  if (!takes.length) { say('가져올 패가 없어 取 를 건너뛴다.'); afterTake(); return; }
  G.mode = 'take';
  say('내 차례.');
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
  modal(`<h2>奪: ${cardText(x)}을 어디에?</h2>` + uniq.map((a, i) => {
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
  if (G.chiOpts.length) { G.mode = 'chi'; say('置 할 수 있다.'); render(); return; }
  afterTakeOut();
}

function afterTakeOut() {
  const st = G.st;
  G.outs = E.legalOuts(st, 0);
  if (!G.outs.length) { say('폐패가 없어 出 를 건너뛴다.'); G.mode = 'busy'; render(); return finishTurn(0, {}); }
  G.mode = 'out';
  G.sel = null;
  say('出: 폐패 한 장을 고른다.');
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
    modal(`<h2>榮和?</h2><p>방금 명패산에 나온 ${cardText(card)}을 가져와 置 하면 화료한다.</p>
      <div class="sets">${G.st.players[0].kans.map((k, i) => cardsHTML(k.concat(opt.add[i].map((id) => id === card.id ? card : G.st.players[0].closed.find((c) => c.id === id))))).join('')}</div>
      <p>${opt.ev.yaku.map((y) => y.name).join(' · ')} — ${opt.ev.total}점 × ${G.N - 1}</p>
      <div class="row"><button type="button" class="primary" data-y>榮和</button><button type="button" data-n>넘기기</button></div>`, (el) => {
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
  say(`${G.names[p]}의 차례…`);
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
  say(`제${G.round + 1}국. ${G.names[dealer]}이 친.`);
  step();
}

const HOW = { place: '展', steal: '奪 (展)', chi: '置', ron: '榮和' };

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
    html = `<h2>${G.names[r.p]} 화료 · ${HOW[r.how]}${r.how === 'ron' ? ` (${G.names[r.from]})` : ''}</h2>
      <div class="sets">${pl.kans.map((k) => `<span class="kan sm full">${k.map((c) => cardEl(c, { sm: true }).outerHTML).join('')}</span>`).join('')}</div>
      <table>${r.ev.yaku.map((y) => `<tr><td>${y.name} <small>${y.hanja}</small>${y.ex ? ' <small>(배타역)</small>' : ''}</td><td class="n">${y.pts}</td></tr>`).join('')}
      ${r.ev.exclusive ? '' : `<tr><td>조 (${r.ev.sets.map((t) => E.SET_NAME[t]).join(' · ')})</td><td class="n">${r.ev.setPts}</td></tr>`}
      <tr><td><b>합계</b></td><td class="n"><b>${r.ev.total}</b></td></tr></table>`;
  } else html = '<h2>流局</h2><p>아무도 화료하지 못했다. 주고받는 점수는 없다.</p>';
  html += `<table>${G.names.map((n, i) => `<tr><td>${n}</td><td class="n ${pay[i] > 0 ? 'plus' : pay[i] < 0 ? 'minus' : ''}">${pay[i] > 0 ? '+' : ''}${pay[i]}</td><td class="n">${G.scores[i]}</td></tr>`).join('')}</table>`;
  html += `<div class="row"><button type="button" class="primary" data-next>${last ? '판 결과' : '다음 국'}</button></div>`;
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
  modal(`<h2>판 결과</h2><p>${winners.join(', ')} 승리.</p>
    <table>${order.map((o, i) => `<tr><td>${i + 1}</td><td>${o.n}</td><td class="n">${o.s}</td></tr>`).join('')}</table>
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

document.querySelectorAll('#start [data-n]').forEach((b) => (b.onclick = () => startMatch(+b.dataset.n)));
$('#wall').onclick = () => G.mode === 'take' && doTake({ type: 'wall' });
$('#river').onclick = () => G.mode === 'take' && G.st.river.length && doTake({ type: 'river' });

// 시험용: 콘솔에서 상태를 볼 수 있게
window.ilodici = G;
