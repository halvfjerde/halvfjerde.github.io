#!/usr/bin/env python3
"""인천국제공항공사 항공기 운항 현황(D-3∼D+6)에서 이레치 여객편을 받는다: python3 fetch_icn.py 20261028 > icn.json"""
import json, sys, os, time, datetime, urllib.request, urllib.parse
KEY = open('/root/.config/tago.key').read().strip()
BASE = 'https://apis.data.go.kr/B551177/statusOfAllFltDeOdp/'
d0 = datetime.datetime.strptime(sys.argv[1], '%Y%m%d')
out = []
for k in range(7):
    day = (d0 + datetime.timedelta(days=k)).strftime('%Y%m%d')
    for op, io in (('getFltDeparturesDeOdp', 'dep'), ('getFltArrivalsDeOdp', 'arr')):
        page = 1
        while True:
            q = urllib.parse.urlencode(dict(serviceKey=KEY, type='json', numOfRows=1000, pageNo=page, searchDate=day))
            for t in range(4):
                try: j = json.loads(urllib.request.urlopen(BASE + op + '?' + q, timeout=60).read().decode()); break
                except Exception as e: err = e; time.sleep(2 + 3 * t)
            else: raise SystemExit('받기 실패 %s %s %s' % (op, day, err))
            b = j['response']['body']; its = b.get('items') or []
            for it in its: it['_io'] = io; it['_day'] = day
            out += its
            print(op, day, page, len(its), b.get('totalCount'), file=sys.stderr)
            if page * 1000 >= (b.get('totalCount') or 0): break
            page += 1
json.dump(out, sys.stdout, ensure_ascii=False)
