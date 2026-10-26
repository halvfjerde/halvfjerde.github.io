# 캐시된 TAGO 응답만으로 도착 시각을 다시 고른다: 시발 시각이 시각표(11월 1일 개정)와 같은 것만
import json, glob, collections, sys
need = json.load(open('/root/needall.json'))          # [열차번호, 시발역, 역, 시발 시각(분)]
want = {(n[0], n[2]): n[3] for n in need}
arr = {}
for f in glob.glob('/root/.cache/tago/GetStrt*'):
    j = json.load(open(f))
    items = j.get('response', {}).get('body', {}).get('items')
    it = items.get('item', []) if isinstance(items, dict) else []
    if isinstance(it, dict): it = [it]
    for x in it:
        no = str(x.get('trainno', '')).lstrip('0'); st = x.get('arrplacename')
        st = {'여수EXPO': '여수엑스포'}.get(st, st)
        k = (no, st)
        if k not in want: continue
        dt = str(x['depplandtime'])[8:12]; t = str(x['arrplandtime'])[8:12]
        if int(dt[:2]) * 60 + int(dt[2:]) != want[k] % 1440: continue
        arr[f'{no}@{st}'] = int(t[:2]) * 60 + int(t[2:])
json.dump(arr, open('/root/arrivals_checked.json', 'w'), ensure_ascii=False, indent=0)
print(len(arr), '/', len(want))
