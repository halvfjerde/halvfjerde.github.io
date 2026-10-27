"""관광열차 시각(코레일 2026. 9. 1. 기준 엑셀) → tour.json (data.json 과 같은 꼴의 표, cat='tour')

python3 parse_tour.py src/tour-2026-09-01.xlsx tour.json
엑셀은 열차마다 [역명, 도착, 출발] 세 칸 덩어리. 덩어리 위에 「#2502(강릉→영주)」, 그 위에 열차 이름(운행일)
"""
import sys, json, re, datetime, openpyxl

# 열차 이름 → (표 이름, 운행일, 별명)
TRAINS = {
    '동해산타열차': ('동해산타열차', '목금토일', ''),
    '백두대간협곡열차': ('백두대간협곡열차', '목금토일월', 'V-train'),
    '남도해양열차(경전선)': ('남도해양열차(경전선)', '금토일', 'S-train'),
    '서해금빛열차': ('서해금빛열차', '목금토일월', 'G-train'),
    '정선아리랑열차': ('정선아리랑열차', '토일', 'A-train'),
    '남도해양열차(전라선)': ('남도해양열차(전라선)', '목금토일월', 'S-train'),
}

# 한 표에 싣는 열차들 (같은 길을 달리는 것끼리). 표 이름 → 열차 이름들. 책의 노선 차례대로
GROUPS = {
    '남도해양열차(전라선)': ['남도해양열차(전라선)'],
    '남도해양열차(경전선)': ['남도해양열차(경전선)'],
    '서해금빛열차': ['서해금빛열차'],
    '백두대간협곡열차・동해산타열차': ['백두대간협곡열차', '동해산타열차'],
    '정선아리랑열차': ['정선아리랑열차'],
}

def mins(v):
    if v is None or v == '': return None
    if isinstance(v, datetime.time): return v.hour * 60 + v.minute
    if isinstance(v, datetime.datetime): return v.hour * 60 + v.minute
    m = re.fullmatch(r'\s*(\d{1,2}):(\d{2})\s*', str(v))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None

def main():
    ws = openpyxl.load_workbook(sys.argv[1], data_only=True).worksheets[0]
    rows = [[c for c in r] for r in ws.iter_rows(values_only=True)]
    H, W = len(rows), max(len(r) for r in rows)
    cell = lambda r, c: rows[r][c] if r < H and c < len(rows[r]) else None
    trains = []
    for r in range(H):
        for c in range(W):
            v = cell(r, c)
            m = re.fullmatch(r'#(\d+)\((.+)\)', str(v or ''))
            if not m: continue
            no = m.group(1)
            # 열차 이름: 같은 열에서 위로 올라가며 「…열차」
            name = next((str(cell(rr, cc)) for rr in range(r - 1, -1, -1) for cc in (c, c - 3, c - 6)
                         if cc >= 0 and re.search(r'열차', str(cell(rr, cc) or '')) and not str(cell(rr, cc)).startswith('#')), None)
            key = next(k for k in TRAINS if name.startswith(k.split('(')[0]) and (('(' not in k) or k.split('(')[1].rstrip(')') in name))
            assert cell(r + 1, c) == '역명', (no, cell(r + 1, c))
            stops = []
            rr = r + 2
            while rr < H and cell(rr, c) not in (None, '') and not str(cell(rr, c)).startswith('#'):
                stops.append((str(cell(rr, c)).strip(), mins(cell(rr, c + 1)), mins(cell(rr, c + 2))))
                rr += 1
            trains.append({'key': key, 'no': no, 'stops': stops})
    tables = []
    for line, keys in GROUPS.items():
        trs = [t for t in trains if t['key'] in keys]
        for d in ('down', 'up'):
            ts = [t for t in trs if (int(t['no']) % 2 == 1) == (d == 'down')]
            if not ts: continue
            order = []                       # 역 차례: 열차마다의 차례를 이어 붙인다 (긴 열차부터)
            for t in sorted(ts, key=lambda t: -len(t['stops'])):
                names = [s for s, _, _ in t['stops']]
                for j, s in enumerate(names):
                    if s in order: continue
                    nxt = next((x for x in names[j + 1:] if x in order), None)
                    order.insert(order.index(nxt) if nxt else len(order), s)
            out = []
            for t in sorted(ts, key=lambda t: next(x for _, a, b in t['stops'] for x in (b, a) if x is not None)):
                tm = {s: (b if b is not None else a) for s, a, b in t['stops']}
                arr = {s: a for s, a, b in t['stops'] if a is not None and b is not None}
                st0, stN = t['stops'][0], t['stops'][-1]
                line_, days, nick = TRAINS[t['key']]
                out.append({'no': t['no'], 'type': nick or line_, 'name': line_, 'from': st0[0], 'fromT': st0[2], 'to': stN[0], 'toT': stN[1],
                            'note': days, 'times': [tm.get(s) for s in order], 'arr': arr})
            tables.append({'cat': 'tour', 'line': line, 'dir': d, 'stations': order, 'trains': out})
    json.dump({'source': '코레일 관광열차 시각 2026. 9. 1. 기준', 'tables': tables}, open(sys.argv[2], 'w'), ensure_ascii=False, indent=1)
    for t in tables: print(t['line'], t['dir'], len(t['stations']), [x['no'] for x in t['trains']], t['stations'])

main()
