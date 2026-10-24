/*
 * 일로디스 (ilódici) — 규칙 엔진
 * 기준: 쩌모위키 「게임:일로디스」. 화면과 떨어진 순수 함수 모음이라 온라인 대전에도 그대로 쓸 수 있다.
 *
 * 패: { id, s, n }  s = 0(+) 1(●) 2(◇, 빨강), n = 1–9. 81장 = 3문양 × 9 × 3벌.
 * 칸: 개패 배열(최대 3장). 3장이 차면 조.
 */

export const SUITS = ['+', '●', '◇'];
export const RED = 2;
export const SET_NAME = { same: '동조', suits: '제조', run: '연조' };
export const SET_PTS = { same: 4, suits: 2, run: 1 };

/* ── 패 ───────────────────────────────────────────────────────────── */

export function makeDeck() {
  const d = [];
  let id = 0;
  for (let copy = 0; copy < 3; copy++)
    for (let s = 0; s < 3; s++)
      for (let n = 1; n <= 9; n++) d.push({ id: id++, s, n });
  return d;
}

export const key = (c) => c.s * 10 + c.n;
export const label = (c) => `${c.n}${SUITS[c.s]}`;
export const sortCards = (a) => a.slice().sort((x, y) => x.s - y.s || x.n - y.n || x.id - y.id);

export function shuffle(a, rnd = Math.random) {
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/* ── 조 ───────────────────────────────────────────────────────────── */

/** 3장의 조 종류: 'same'(동조) | 'suits'(제조) | 'run'(연조) | null */
export function setType(cs) {
  if (cs.length !== 3) return null;
  const [a, b, c] = cs.slice().sort((x, y) => x.n - y.n);
  if (a.s === b.s && b.s === c.s) {
    if (a.n === b.n && b.n === c.n) return 'same';
    if (b.n === a.n + 1 && c.n === b.n + 1) return 'run';
    return null;
  }
  if (a.n === b.n && b.n === c.n && new Set([a.s, b.s, c.s]).size === 3) return 'suits';
  return null;
}

/** 이 패들에 더해 조를 이룰 수 있는가 (칸에 놓을 수 있는 조건) */
export function canBeSet(cs) {
  if (cs.length <= 1) return true;
  if (cs.length === 3) return !!setType(cs);
  if (cs.length > 3) return false;
  const [a, b] = cs;
  if (a.s === b.s && a.n === b.n) return true;              // 동조
  if (a.n === b.n) return true;                              // 제조
  if (a.s === b.s && Math.abs(a.n - b.n) <= 2) return true; // 연조
  return false;
}

/* ── 역과 점수 ────────────────────────────────────────────────────── */

/**
 * sets: 조 3개(각 3장). ctx: { how: 'place'|'steal'|'chi'|'ron', placed: 置로 한 번에 놓은 장수, tenhou }
 * 돌려줌: { yaku: [{ name, pts, ex }], exclusive, setPts, total }  — 역이 없으면 yaku 가 빈 배열
 */
export function evaluate(sets, ctx = {}) {
  const types = sets.map(setType);
  const all = sets.flat();
  const isRed = (st) => st.every((c) => c.s === RED);
  const sameRun = (a, b) => setType(a) === 'run' && setType(b) === 'run'
    && a[0].s === b[0].s && Math.min(...a.map((c) => c.n)) === Math.min(...b.map((c) => c.n));
  const runStart = (st) => Math.min(...st.map((c) => c.n));
  const oneSuit = all.every((c) => c.s === all[0].s);

  const normal = [];
  const ex = [];
  sets.forEach((st, i) => {
    if (isRed(st) && (types[i] === 'same' || types[i] === 'run')) normal.push({ name: '적조', hanja: '赤組', pts: 1 });
  });
  if (ctx.how === 'steal') normal.push({ name: '탈화', hanja: '奪和', pts: 1 });
  if ((ctx.how === 'chi' || ctx.how === 'ron') && ctx.placed === 6) normal.push({ name: '치화', hanja: '置和', pts: 1 });
  if (types.every((t) => t === 'same' || t === 'suits')) normal.push({ name: '무련', hanja: '冇連', pts: 3 });
  if (sets.every((st) => st.some((c) => c.n === 1 || c.n === 9))) normal.push({ name: '대단', hanja: '帯端', pts: 3 });
  const pairs = [[0, 1], [0, 2], [1, 2]].filter(([i, j]) => sameRun(sets[i], sets[j])).length;
  if (pairs >= 1 && pairs < 3) normal.push({ name: '배구', hanja: '盃口', pts: 6 });
  if (oneSuit) normal.push({ name: '일색', hanja: '一色', pts: 12 });

  const allRed = all.every((c) => c.s === RED);
  if (allRed) ex.push({ name: '적일색', hanja: '赤一色', pts: 24 });
  if (oneSuit && types.every((t) => t === 'run')
      && sets.map(runStart).sort((a, b) => a - b).join() === '1,4,7') ex.push({ name: '일기통관', hanja: '一氣通貫', pts: 24 });
  if (allRed && all.every((c) => [1, 2, 3, 4, 6, 7, 8].includes(c.n))) ex.push({ name: '순적일색', hanja: '純赤一色', pts: 36 });
  if (types.every((t) => t === 'same')) ex.push({ name: '삼동', hanja: '三同', pts: 48 });
  if (types.every((t) => t === 'same') && oneSuit) ex.push({ name: '일색삼동', hanja: '一色三同', pts: 96 });
  if (ctx.tenhou) ex.push({ name: '천화', hanja: '天和', pts: 96 });
  if (pairs === 3) ex.push({ name: '연삼동', hanja: '連三同', pts: 120 });
  if (pairs === 3 && runStart(sets[0]) === 1) ex.push({ name: '상연삼동', hanja: '上連三同', pts: 168 });

  const setPts = types.reduce((a, t) => a + (SET_PTS[t] || 0), 0);
  if (ex.length) {
    // 배타역은 겹치지 않는다: 가장 높은 것 하나만, 조 점수도 더하지 않는다 (일반 역도 버린다)
    const best = ex.reduce((a, b) => (b.pts > a.pts ? b : a));
    return { yaku: [{ ...best, ex: true }], exclusive: true, setPts: 0, total: best.pts, sets: types };
  }
  const yp = normal.reduce((a, y) => a + y.pts, 0);
  return { yaku: normal, exclusive: false, setPts: normal.length ? setPts : 0, total: normal.length ? yp + setPts : 0, sets: types };
}

/* ── 조합 찾기 ────────────────────────────────────────────────────── */

/** cards 에서 k장을 고르는 조합 (같은 패(문양·수) 조합은 한 번만) */
function* combos(cards, k, start = 0, pick = []) {
  if (pick.length === k) { yield pick.slice(); return; }
  const seen = new Set();
  for (let i = start; i < cards.length; i++) {
    const kk = key(cards[i]);
    if (seen.has(kk)) continue;
    seen.add(kk);
    pick.push(cards[i]);
    yield* combos(cards, k, i + 1, pick);
    pick.pop();
  }
}

/**
 * 다 차지 않은 칸들을 closed 의 패로 모두 채워 조로 만드는 방법들.
 * 돌려줌: [{ add: [[...],[...],[...]] (칸마다 더할 패), count }]
 */
export function fillAll(kans, closed, limit = 200) {
  const out = [];
  const idx = [0, 1, 2].filter((i) => kans[i].length < 3);
  const rec = (k, rest, add) => {
    if (out.length >= limit) return;
    if (k === idx.length) { out.push({ add: add.map((a) => a.slice()), count: add.reduce((s, a) => s + a.length, 0) }); return; }
    const i = idx[k], need = 3 - kans[i].length;
    const sorted = sortCards(rest);
    for (const c of combos(sorted, need)) {
      if (!setType(kans[i].concat(c))) continue;
      const ids = new Set(c.map((x) => x.id));
      add[i] = c;
      rec(k + 1, rest.filter((x) => !ids.has(x.id)), add);
      add[i] = [];
    }
  };
  rec(0, closed, [[], [], []]);
  return out;
}

/* ── 국 ───────────────────────────────────────────────────────────── */

export function newRound(N, dealer, rnd = Math.random) {
  const deck = shuffle(makeDeck(), rnd);
  const players = [];
  for (let p = 0; p < N; p++) {
    const hand = deck.splice(0, 9);
    players.push({ closed: hand, kans: [[], [], []], dealt: hand.map((c) => c.id) });
  }
  return {
    N, dealer, turn: dealer, phase: 'take', wall: deck, river: [],
    players, turns: 0, lastDrawer: null, took: null, result: null, log: [],
  };
}

const fullCount = (pl) => pl.kans.filter((k) => k.length === 3).length;
const others = (st, p) => Array.from({ length: st.N - 1 }, (_, i) => (p + 1 + i) % st.N);

/** 取 할 수 있는 것들 */
export function legalTakes(st, p) {
  const acts = [];
  if (st.wall.length) acts.push({ type: 'wall' });
  if (st.river.length) acts.push({ type: 'river' });
  acts.push(...stealOptions(st, p));
  return acts;
}

/** 奪: 남의 다 차지 않은 칸의 개패 한 장 + 내 폐패로 내 칸 하나를 바로 조로 채운다 */
export function stealOptions(st, p) {
  const me = st.players[p];
  const acts = [];
  for (const q of others(st, p)) {
    st.players[q].kans.forEach((kan, qk) => {
      if (kan.length === 0 || kan.length === 3) return;
      const seen = new Set();
      for (const x of kan) {
        if (seen.has(key(x))) continue;
        seen.add(key(x));
        me.kans.forEach((mk, k) => {
          if (mk.length === 3) return;
          const need = 3 - mk.length - 1;
          if (need < 0) return;
          for (const c of combos(sortCards(me.closed), need)) {
            if (setType(mk.concat([x], c))) acts.push({ type: 'steal', from: q, fromKan: qk, cardId: x.id, kan: k, ids: c.map((y) => y.id) });
          }
        });
      }
    });
  }
  return acts;
}

const take = (arr, id) => { const i = arr.findIndex((c) => c.id === id); return i < 0 ? null : arr.splice(i, 1)[0]; };

/** 取 를 적용. 奪 로 마지막 칸이 차면 바로 화료 */
export function applyTake(st, p, a) {
  const me = st.players[p];
  let card = null;
  if (a.type === 'wall') {
    card = st.wall.pop();
    me.closed.push(card);
    if (!st.wall.length) st.lastDrawer = p;
    st.log.push({ p, t: 'wall' });
  } else if (a.type === 'river') {
    card = st.river.pop();
    me.closed.push(card);
    st.log.push({ p, t: 'river', card });
  } else if (a.type === 'steal') {
    card = take(st.players[a.from].kans[a.fromKan], a.cardId);
    const cs = a.ids.map((id) => take(me.closed, id));
    me.kans[a.kan].push(card, ...cs);
    st.log.push({ p, t: 'steal', card, from: a.from });
    if (fullCount(me) === 3) return win(st, p, { how: 'steal' });
  }
  st.took = { type: a.type, card };
  st.phase = 'out';
  return null;
}

/** 置: 取 한 직후, 조가 다 찬 칸이 있고 나머지 빈자리를 폐패로 한꺼번에 채워 화료할 수 있는 방법(가장 높은 점수 순) */
export function chiOptions(st, p, how = 'chi') {
  const me = st.players[p];
  const tenhou = how === 'chi' && p === st.dealer && st.turns === 0 && fullCount(me) === 0 && me.kans.every((k) => !k.length);
  if (!fullCount(me) && !tenhou) return [];
  const pool = tenhou ? me.closed.filter((c) => me.dealt.includes(c.id)) : me.closed;
  const opts = [];
  for (const f of fillAll(me.kans, pool)) {
    const sets = me.kans.map((k, i) => k.concat(f.add[i]));
    const ev = evaluate(sets, { how, placed: f.count, tenhou });
    if (ev.yaku.length) opts.push({ add: f.add.map((a) => a.map((c) => c.id)), count: f.count, ev });
  }
  return opts.sort((a, b) => b.ev.total - a.ev.total);
}

export function applyChi(st, p, opt, how = 'chi') {
  const me = st.players[p];
  opt.add.forEach((ids, i) => ids.forEach((id) => me.kans[i].push(take(me.closed, id))));
  return win(st, p, { how, placed: opt.count, ev: opt.ev });
}

/** 出 할 수 있는 것들 (폐패가 없으면 빈 배열 → 건너뜀) */
export function legalOuts(st, p) {
  const me = st.players[p];
  const acts = [];
  const full = fullCount(me);
  for (const c of me.closed) {
    acts.push({ type: 'discard', id: c.id });
    me.kans.forEach((kan, k) => {
      if (kan.length === 3) return;
      // 칸에 놓기
      const nk = kan.concat([c]);
      if (canBeSet(nk)) {
        if (nk.length === 3 && full === 2) {
          // 마지막 칸을 채우는 패는 그것으로 화료할 수 있을 때만
          const ev = evaluate(me.kans.map((x, i) => (i === k ? nk : x)), { how: 'place' });
          if (ev.yaku.length) acts.push({ type: 'place', id: c.id, kan: k, win: ev });
        } else acts.push({ type: 'place', id: c.id, kan: k });
      }
      // 換: 이 칸의 개패 한 장과 맞바꾸고, 빠진 패는 명패산으로
      kan.forEach((o) => {
        if (key(o) === key(c)) return;
        if (canBeSet(kan.filter((x) => x.id !== o.id).concat([c]))) acts.push({ type: 'swap', id: c.id, kan: k, outId: o.id });
      });
    });
  }
  // 같은 패(문양·수)에 대한 같은 행동은 하나만
  const seen = new Set();
  return acts.filter((a) => {
    const c = me.closed.find((x) => x.id === a.id);
    const o = a.outId != null ? me.kans[a.kan].find((x) => x.id === a.outId) : null;
    const k = [a.type, key(c), a.kan, o ? key(o) : ''].join('/');
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

/** 出 를 적용. 명패산에 패가 놓이면 { river: card } 를 돌려준다 (榮和 확인용) */
export function applyOut(st, p, a) {
  const me = st.players[p];
  if (a.type === 'place') {
    const c = take(me.closed, a.id);
    me.kans[a.kan].push(c);
    st.log.push({ p, t: 'place', card: c, kan: a.kan });
    if (fullCount(me) === 3) return { win: win(st, p, { how: 'place' }) };
    return {};
  }
  if (a.type === 'discard') {
    const c = take(me.closed, a.id);
    st.river.push(c);
    st.log.push({ p, t: 'discard', card: c });
    return { river: c };
  }
  if (a.type === 'swap') {
    const c = take(me.closed, a.id);
    const o = take(me.kans[a.kan], a.outId);
    me.kans[a.kan].push(c);
    st.river.push(o);
    st.log.push({ p, t: 'swap', card: c, out: o, kan: a.kan });
    return { river: o };
  }
  return {};
}

/** 榮和: 명패산에 놓인 패를 取 하면 置 하여 화료할 수 있는 사람 (둔 사람의 다음 차례부터 가까운 순) */
export function ronCandidates(st, from) {
  const card = st.river[st.river.length - 1];
  const out = [];
  for (const q of others(st, from)) {
    const pl = st.players[q];
    if (!fullCount(pl)) continue;
    pl.closed.push(card);
    const opts = chiOptions(st, q, 'ron').filter((o) => o.add.some((ids) => ids.includes(card.id)));
    pl.closed.pop();
    if (opts.length) out.push({ p: q, opt: opts[0] });
  }
  return out;
}

export function applyRon(st, q, from, opt) {
  const card = st.river.pop();
  st.players[q].closed.push(card);
  st.log.push({ p: q, t: 'ron', card, from });
  const r = applyChi(st, q, opt, 'ron');
  r.from = from;
  return r;
}

function win(st, p, { how, placed = 0, ev }) {
  const me = st.players[p];
  ev = ev || evaluate(me.kans, { how, placed });
  st.phase = 'end';
  st.result = { type: 'win', p, how, ev, pay: null };
  st.log.push({ p, t: 'win', how, total: ev.total });
  return st.result;
}

/** 점수 주고받기: 화료한 사람에게 나머지가 점수만큼, 榮和 이면 둔 사람이 혼자 × (인원 − 1) */
export function settle(st) {
  const r = st.result;
  const pay = Array(st.N).fill(0);
  if (r && r.type === 'win') {
    const t = r.ev.total;
    if (r.how === 'ron') { pay[r.from] -= t * (st.N - 1); pay[r.p] += t * (st.N - 1); }
    else for (let q = 0; q < st.N; q++) if (q !== r.p) { pay[q] -= t; pay[r.p] += t; }
  }
  if (r) r.pay = pay;
  return pay;
}

/** 차례 넘기기. 암패산의 마지막 패를 가져간 사람의 차례가 다시 오면 流局 */
export function nextTurn(st) {
  st.turn = (st.turn + 1) % st.N;
  st.turns++;
  st.took = null;
  if (!st.wall.length && st.lastDrawer === st.turn) {
    st.phase = 'end';
    st.result = { type: 'draw' };
    st.log.push({ t: 'draw' });
    return st.result;
  }
  st.phase = 'take';
  return null;
}
