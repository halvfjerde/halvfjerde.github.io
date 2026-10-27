"""scan-<출발>.json (스캔 결과)을 bus.py 의 받은 것 자리에 옮긴다: python3 seed.py 날짜 terminals.json scan-*.json"""
import json, sys, os
day, tfile = sys.argv[1], sys.argv[2]
CACHE = os.path.expanduser('~/.cache/tago-bus'); os.makedirs(CACHE, exist_ok=True)
ids = [t['terminalId'] for t in json.load(open(tfile))['exp']]
for f in sys.argv[3:]:
    dep = os.path.basename(f)[5:-5]
    d = json.load(open(f))
    n = 0
    for arr in ids:
        if arr == dep: continue
        v = d.get(arr, [])
        if v == 'ERR': continue
        kw = dict(arrTerminalId=arr, depPlandTime=day, depTerminalId=dep, numOfRows=1000)
        ck = os.path.join(CACHE, 'GetStrtpntAlocFndExpbusInfo-' + '-'.join('%s=%s' % (k, v_) for k, v_ in sorted(kw.items())))
        json.dump({'response': {'body': {'items': {'item': v} if v else ''}}}, open(ck, 'w'), ensure_ascii=False); n += 1
    print(dep, n)
