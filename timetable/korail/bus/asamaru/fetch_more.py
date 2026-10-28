"""앞선 날들의 TAGO 고속・시외 배차를 캐시에 받는다 (이미 받은 구간만, 같은 이름으로).
python3 fetch_more.py 20261003 … 20261016   (열쇠: /root/.config/tago.key, tago.key2 — 한도가 차면 다른 열쇠로)"""
import json, sys, os, time, glob, urllib.request, urllib.parse, concurrent.futures as cf, collections, threading
KEYS = [open('/root/.config/tago.key').read().strip(), open('/root/.config/tago.key2').read().strip()]
days = sys.argv[1:]
CB, CS = os.path.expanduser('~/.cache/tago-bus'), os.path.expanduser('~/.cache/tago-sub')
pl = json.load(open('/home/claude/korail/bus/asamaru/pairs-live.json'))
EXP = sorted({(ia[0], ib[0]) for a, b, ia, ib in pl})
SUB = sorted({tuple(os.path.basename(f)[:-5].split('-')[1:3]) for f in glob.glob(CS + '/20261029-*.json')})
dead = {'ExpBusInfo': set(), 'SuburbsBusInfo': set()}
lock = threading.Lock()
def get(job):
    api, day, a, b = job
    ck = os.path.join(CB, 'p-%s-%s-%s.json' % (day, a, b)) if api == 'ExpBusInfo' else os.path.join(CS, '%s-%s-%s.json' % (day, a, b))
    if os.path.exists(ck): return 'c'
    op = 'GetStrtpntAlocFndExpbusInfo' if api == 'ExpBusInfo' else 'GetStrtpntAlocFndSuberbsBusInfo'
    for t in range(6):
        ks = [k for k in range(2) if k not in dead[api]]
        if not ks: return 'q'
        k = ks[t % len(ks)]
        q = urllib.parse.urlencode(dict(serviceKey=KEYS[k], _type='json', numOfRows=300, pageNo=1, depTerminalId=a, arrTerminalId=b, depPlandTime=day))
        try:
            raw = urllib.request.urlopen('https://apis.data.go.kr/1613000/%s/%s?%s' % (api, op, q), timeout=13).read().decode()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                with lock: STAT['429'] += 1
                time.sleep(3 + 3 * t); continue
            time.sleep(2 + 2 * t); continue
        except Exception:
            time.sleep(0.5); continue
        if 'LIMITED' in raw:
            with lock: dead[api].add(k)
            continue
        try: bd = json.loads(raw)['response']['body']
        except Exception: time.sleep(2); continue
        it = bd.get('items') or {}
        it = it.get('item', []) if isinstance(it, dict) else []
        it = it if isinstance(it, list) else [it]
        json.dump(it, open(ck, 'w'), ensure_ascii=False); return 'ok'
    return 'f'
ONLY = os.environ.get('ONLY')                           # ExpBusInfo 또는 SuburbsBusInfo 만
if os.environ.get('NEED'):                              # 날마다 다니지 않거나 등급이 바뀌는 편이 있는 구간만 (날마다 같은 편은 볼 것 없음)
    nd_ = json.load(open(os.environ['NEED']))
    EXP = [(a, b) for k, a, b in nd_ if k == 'ExpBusInfo']; SUB = [(a, b) for k, a, b in nd_ if k == 'SuburbsBusInfo']
jobs = ([('ExpBusInfo', d, a, b) for d in days for a, b in EXP] if ONLY != 'SuburbsBusInfo' else []) + ([('SuburbsBusInfo', d, a, b) for d in days for a, b in SUB] if ONLY != 'ExpBusInfo' else [])
STAT = collections.Counter()
print('jobs', len(jobs), 'exp pairs', len(EXP), 'sub pairs', len(SUB), flush=True)
cnt = collections.Counter()
with cf.ThreadPoolExecutor(int(os.environ.get('TH', '3'))) as ex:
    for i, r in enumerate(ex.map(get, jobs)):
        cnt[r] += 1
        if i % 250 == 0: print(i, len(jobs), dict(cnt), dict(STAT), 'dead', {k: sorted(v) for k, v in dead.items()}, time.strftime('%H:%M:%S'), flush=True)
print('done', dict(cnt), 'dead', {k: sorted(v) for k, v in dead.items()}, flush=True)
