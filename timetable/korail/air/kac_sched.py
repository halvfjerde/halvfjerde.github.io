#!/usr/bin/env python3
"""공항공사 누리집에서 받은 국내선 운항 스케줄(SCHEDULE_DOM_*.xlsx, 공항마다) → 한 달의 편·날짜 (fetch.py 꼴: flights-YYYYMM.json)
출발 행은 그 공항에서 떠나는 편. 인천(공항공사 밖)에서 떠나는 편은 도착 행에서 얻는다"""
import sys, glob, json, datetime, calendar, openpyxl, re
ym = sys.argv[1]; y, m = int(ym[:4]), int(ym[4:])
N = calendar.monthrange(y, m)[1]
EN = {'GIMPO': '김포', 'GIMHAE': '김해', 'JEJU': '제주', 'CHEONGJU': '청주', 'DAEGU': '대구', 'YANGYANG': '양양', 'GWANGJU': '광주',
      'ULSAN': '울산', 'YEOSU': '여수', 'POHANG GYEONGJU': '포항', 'SACHEON': '사천', 'GUNSAN': '군산', 'WONJU': '원주', 'INCHEON': '인천', 'MUAN': '무안'}
out, unknown, seen = [], set(), set()
for f in sorted(glob.glob(sys.argv[2] + '/*SCHEDULE_DOM_*.xlsx')):
    ws = openpyxl.load_workbook(f, read_only=True).worksheets[0]
    for r in list(ws.iter_rows(values_only=True))[2:]:
        if not r or not r[2]: continue
        kind, al, no, ap, sec, dt, at = r[:7]
        flags = r[7:14]; per = r[14]
        if kind == '出発': dep, arr = ap, sec
        elif kind == '到着' and sec == 'INCHEON': dep, arr = sec, ap            # 인천발은 도착 행에서
        else: continue
        for x in (dep, arr):
            if x not in EN: unknown.add(x)
        a_, b_ = re.findall(r'(\d{4})\.(\d{2})\.(\d{2})', per)
        d0 = datetime.date(*map(int, a_)); d1 = datetime.date(*map(int, b_))
        for day in range(1, N + 1):
            dd = datetime.date(y, m, day)
            if d0 <= dd <= d1 and flags[dd.weekday()] == 'Y':
                k = (dep, arr, no, day, dt)
                if k in seen: continue
                seen.add(k)
                out.append({'dep': EN.get(dep, dep), 'arr': EN.get(arr, arr), 'day': '%s%02d' % (ym, day), 'no': no, 'air': al,
                            't': dt.replace(':', ''), 'a': at.replace(':', '')})
print('rows', len(out), 'unknown', unknown, file=sys.stderr)
aps = sorted({x['dep'] for x in out} | {x['arr'] for x in out})
json.dump({'airports': {a: a for a in aps}, 'month': ym, 'flights': out}, sys.stdout, ensure_ascii=False)
