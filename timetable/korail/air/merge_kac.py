#!/usr/bin/env python3
"""공항공사 스케줄(주) + TAGO(공항공사에 편명이 아예 없는 편만, 그리고 요금) → flights-merged-YYYYMM.json"""
import json, sys, collections
k = json.load(open(sys.argv[1])); t = json.load(open(sys.argv[2]))
aps = t['airports']
sh = lambda n: n.replace('국제공항', '').replace('공항', '').replace('포항경주', '포항')
kno = {f['no'] for f in k['flights']}
fare = {}
for f in t['flights']:
    if f.get('c'): fare[(sh(aps[f['dep']]), sh(aps[f['arr']]), f['no'], f['day'])] = f['c']
out = []
for f in k['flights']:
    out.append(dict(f, c=fare.get((f['dep'], f['arr'], f['no'], f['day']))))
add = 0
for f in t['flights']:
    if f['no'] in kno: continue
    out.append(dict(f, dep=sh(aps[f['dep']]), arr=sh(aps[f['arr']]))); add += 1
names = sorted({x['dep'] for x in out} | {x['arr'] for x in out})
print('kac', len(k['flights']), 'tago-only added', add, file=sys.stderr)
json.dump({'airports': {a: a for a in names}, 'month': k['month'], 'flights': out}, sys.stdout, ensure_ascii=False)
