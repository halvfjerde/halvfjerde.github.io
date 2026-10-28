#!/usr/bin/env python3
"""같은 출발지에서 작은 구간의 발차 시각이 모두 큰 구간의 발차 시각과 같은 것 (같은 차일 수 있는 것).
작은 구간마다 그 시각을 모두 담는 가장 작은 큰 구간 하나에 붙인다. 큰 구간이 너무 촘촘하면(편수가 작은 구간의 3배 넘고 5편 넘게 많으면) 우연으로 보고 뺀다.
python3 coincide.py bus.json rest.json > coincide.md"""
import json, sys, collections, os
b = json.load(open(sys.argv[1]))
P = {(o['from'], x['to']): x for o in b['origins'] for x in o['dests']}
T = {k: frozenset(t[0] for t in v['times']) for k, v in P.items()}
here = os.path.dirname(os.path.abspath(__file__))
sb = json.load(open(os.path.join(here, 'same-bus.json'))); fl = json.load(open(os.path.join(here, 'force-links.json')))
ps = json.load(open(os.path.join(here, 'partial-stops.json')))
R = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else {'origins': [], 'routeOwned': []}     # rest.json: 노선표가 가진 구간, 목록에서 묶은 구간
handled = {tuple(x.split('→')) for x in R.get('routeOwned', [])}
for O in R['origins']:
    for X in O['dests']:
        if 'see' in X or 'seeFrom' in X or 'via' in X or 'board' in X or 'vnote' in X: handled.add((O['from'], X['to']))
known = [set(s) for s in fl] + [{x[0], x[1]} for x in sb['drop'] + sb['board']] + [set(x) for x in ps]
NM = {'센트럴시티(서울)': '서울호남', '광주(유·스퀘어)': '광주', '대전청사(샘머리)': '대전청사'}
nm = lambda x: NM.get(x, x)
hm = lambda m: '%d:%02d' % divmod(m, 60)
key = lambda s: (lambda m: m + (1440 if m < 240 else 0))(int(s[:-2] or 0) * 60 + int(s[-2:]))
byA = collections.defaultdict(list)
for a, d in P: byA[a].append(d)
L = ['# 출발지와 발차 시각이 모두 겹치는 구간', '',
     'TAGO 구간 자료(2026년 10월 17∼30일, 시외 포함). 같은 출발지에서, 작은 쪽 행선지의 발차 시각이 모두 큰 쪽 행선지에도 있는 것.',
     '행선지는 소요 차례(= 들르는 차례 짐작), 괄호는 편수·소요. 작은 쪽이 일부 편만이면 그 시각을 적었다.',
     '편이 한둘이면 우연일 수도 있다. 이미 노선표·same-bus·partial-stops 로 정리한 것은 끝에 이름만.', '']
cnt = ok_ = 0
OUT, DONE = [], []
for a in sorted(byA, key=nm):
    ds = byA[a]
    par = {}
    for x in ds:
        s = T[(a, x)]
        sup = [y for y in ds if y != x and s <= T[(a, y)] and (len(s) < len(T[(a, y)]) or P[(a, y)]['dur'] > P[(a, x)]['dur'] or (P[(a, y)]['dur'] == P[(a, x)]['dur'] and y > x))]
        if not sup: continue
        y = min(sup, key=lambda y: (len(T[(a, y)]), -P[(a, y)]['dur']))
        if len(T[(a, y)]) > 3 * len(s) and len(T[(a, y)]) > len(s) + 5: continue
        par[x] = y
    roots = collections.defaultdict(list)
    for x in par:
        r = x
        while r in par: r = par[r]
        roots[r].append(x)
    blk, dn = [], []
    for r, ms in sorted(roots.items(), key=lambda kv: -len(T[(a, kv[0])])):
        allx = sorted(ms + [r], key=lambda x: (P[(a, x)]['dur'], len(T[(a, x)])))
        done = all((a, x) in handled for x in allx)
        cnt += 1; ok_ += done
        chain = ' → '.join('%s(%d, %s)' % (nm(x), len(T[(a, x)]), hm(P[(a, x)]['dur'])) for x in allx)
        if done: dn.append(chain); continue
        blk.append('- ' + chain)
        blk.append('  - 발: ' + ' '.join(sorted(T[(a, r)], key=key)))
        for x in allx:
            if x != r and T[(a, x)] != T[(a, r)]: blk.append('  - %s 은 %s' % (nm(x), ' '.join(sorted(T[(a, x)], key=key))))
    if blk: OUT += ['**%s 발**' % nm(a)] + blk + ['']
    DONE += ['- %s 발: %s' % (nm(a), c) for c in dn]
L += ['## 아직 정리하지 않은 것', ''] + OUT + ['## 이미 정리한 것', ''] + DONE
print('\n'.join(L))
print('묶음', cnt, '정리함', ok_, file=sys.stderr)
