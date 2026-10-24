/*
 * 일로디스 — CPU
 * 단순한 손익 계산: 쓸모 있는 패는 모으고 쓸모없는 패를 버린다.
 * 첫 칸은 하나씩 놓아 채우고(置 하려면 다 찬 칸이 하나 있어야 하므로), 그 뒤로는 되도록 폐패에 모아 두었다가
 * 置 로 한꺼번에 내려놓는다 (다 차지 않은 칸은 奪 당할 수 있으므로).
 */
import { canBeSet, setType, key, stealOptions, chiOptions, legalOuts, RED } from './engine.js';

const fullCount = (pl) => pl.kans.filter((k) => k.length === 3).length;

/** 패 한 장이 지금 손에서 얼마나 쓸모 있는가 */
export function usefulness(c, closed, kans) {
  const rest = closed.filter((x) => x.id !== c.id);
  let s = 0;
  for (const d of rest) {
    if (key(d) === key(c)) s += 2.2;
    else if (d.n === c.n) s += 1.1;                                  // 제조 재료
    else if (d.s === c.s && Math.abs(d.n - c.n) === 1) s += 1.4;     // 연조 재료
    else if (d.s === c.s && Math.abs(d.n - c.n) === 2) s += 0.9;
  }
  // 이미 조가 되는 세 장
  for (let i = 0; i < rest.length; i++)
    for (let j = i + 1; j < rest.length; j++)
      if (setType([c, rest[i], rest[j]])) { s += 4; i = rest.length; break; }
  for (const kan of kans) {
    if (kan.length === 0 || kan.length === 3) continue;
    if (canBeSet(kan.concat([c]))) s += kan.length === 2 ? 5 : 3;
  }
  if (c.s === RED) s += 0.8;                  // 적조를 노린다
  if (c.n === 1 || c.n === 9) s += 0.2;       // 대단
  return s;
}

const handValue = (closed, kans) => closed.reduce((a, c) => a + usefulness(c, closed, kans), 0);

/** 取: 奪 로 칸이 차면 그것, 명패산 맨 위가 쓸모 있으면 그것, 아니면 암패산 */
export function chooseTake(st, p) {
  const me = st.players[p];
  const steals = stealOptions(st, p);
  if (steals.length) {
    // 마지막 칸을 채우면 탈화로 화료. 그렇지 않아도 칸 하나가 바로 차므로 대체로 이득
    const win = steals.find(() => fullCount(me) === 2);
    if (win) return win;
    const best = steals
      .map((a) => ({ a, v: (st.players[a.from].kans[a.fromKan].find((c) => c.id === a.cardId).s === RED ? 1 : 0) - a.ids.length * 0.3 }))
      .sort((x, y) => y.v - x.v)[0].a;
    if (fullCount(me) === 0 || Math.random() < 0.8) return best;
  }
  const top = st.river[st.river.length - 1];
  if (top) {
    // 이 패를 가져와 置 로 화료할 수 있으면
    me.closed.push(top);
    const canChi = chiOptions(st, p).length > 0;
    const gain = usefulness(top, me.closed, me.kans);
    me.closed.pop();
    if (canChi) return { type: 'river' };
    if (!st.wall.length || gain >= 4) return { type: 'river' };
  }
  if (st.wall.length) return { type: 'wall' };
  if (top) return { type: 'river' };
  return steals[0] || null;
}

/** 取 한 직후: 置 로 화료할 수 있으면 가장 높은 것 */
export function chooseChi(st, p) {
  const opts = chiOptions(st, p);
  return opts[0] || null;
}

/** 出 */
export function chooseOut(st, p) {
  const me = st.players[p];
  const acts = legalOuts(st, p);
  if (!acts.length) return null;
  const card = (id) => me.closed.find((c) => c.id === id);

  // 1. 놓아서 화료
  const wins = acts.filter((a) => a.win).sort((x, y) => y.win.total - x.win.total);
  if (wins.length) return wins[0];

  const places = acts.filter((a) => a.type === 'place');
  const prog = me.kans.map((k, i) => ({ k, i })).filter(({ k }) => k.length > 0 && k.length < 3);

  // 2. 채우던 칸이 있으면 이어서 채운다 (채울 수 있는 패 중 다른 데 덜 쓰이는 것)
  if (prog.length) {
    const cands = places.filter((a) => prog.some(({ i }) => i === a.kan));
    if (cands.length) {
      const pick = cands
        .map((a) => {
          const c = card(a.id);
          const completes = me.kans[a.kan].length === 2;
          return { a, v: (completes ? 10 : 0) - usefulness(c, me.closed, me.kans.map((k, i) => (i === a.kan ? [] : k))) * 0.3 };
        })
        .sort((x, y) => y.v - x.v)[0];
      if (pick) return pick.a;
    }
  }

  // 3. 다 찬 칸이 아직 없으면, 폐패에 이미 있는 조(없으면 짝)로 첫 칸을 시작한다
  if (!fullCount(me) && !prog.length) {
    const cs = me.closed;
    let best = null;
    for (let i = 0; i < cs.length; i++)
      for (let j = i + 1; j < cs.length; j++)
        for (let k = j + 1; k < cs.length; k++) {
          const t = setType([cs[i], cs[j], cs[k]]);
          if (!t) continue;
          const v = (t === 'same' ? 3 : t === 'suits' ? 2 : 1) + ([cs[i], cs[j], cs[k]].every((c) => c.s === RED) ? 4 : 0);
          if (!best || v > best.v) best = { v, c: cs[i] };
        }
    if (!best && st.turns >= st.N * 3) {
      for (let i = 0; i < cs.length; i++)
        for (let j = i + 1; j < cs.length; j++)
          if (canBeSet([cs[i], cs[j]]) && (key(cs[i]) === key(cs[j]) || cs[i].s === RED)) { best = { c: cs[i] }; break; }
    }
    if (best) {
      const empty = me.kans.findIndex((k) => !k.length);
      const a = places.find((x) => x.kan === empty && key(card(x.id)) === key(best.c));
      if (a) return a;
    }
  }

  // 4. 가장 쓸모없는 패를 버린다
  const discards = acts.filter((a) => a.type === 'discard');
  const worst = discards
    .map((a) => ({ a, v: usefulness(card(a.id), me.closed, me.kans) + Math.random() * 0.1 }))
    .sort((x, y) => x.v - y.v)[0];
  return worst ? worst.a : acts[0];
}

export { handValue };
