"""asamaru 사이트맵의 고속버스 구간(출발·도착 이름) → TAGO 고속버스 터미널 ID 들. python3 match.py → pairs-ids.json"""
import json, re, collections
pairs = json.load(open('pairs.json'))['pairs']
ex = json.load(open('terminals.json'))['exp']
SUF = ['여객자동차터미널', '종합버스터미널', '공용버스터미널', '고속버스터미널', '시외버스터미널', '버스여객터미널', '고속시외버스터미널', '시외고속버스터미널',
       '버스종합터미널', '버스공용터미널', '버스터미널', '종합터미널', '시외터미널', '공용터미널', '공영버스터미널', '공영터미널', '문화터미널', '고속버스정류장', '시외버스정류장',
       '고속버스승강장', '고속버스승차장', '고속버스환승정류장', '고속버스환승정류소', '시외버스정류소', '시외버스공용터미널', '시외버스공용정류장', '고속시외버스정류소', '고속시외버스정류장', '시외종합터미널',
       '고속직행버스정류장', '버스공동정류장', '버스공동정류소', '공동정류소', '환승센터', '환승정류장', '버스정류장', '버스정류소', '임시정류소', '정류소', '정류장', '승강장', '승차장', '터미널', '휴게소', '입구']
ALIAS = {'서울고속버스터미널': '서울경부', '인천공항2터미널': '인천공항T2', '인천공항터미널': '인천공항T1', '부산서부버스터미널': '부산사상', '중마버스터미널': '동광양',
         '신복환승센터': '울산신복', '신갈고속시외버스정류소': '용인신갈', '청주여객북부정류소': '청주북부', '고양종합터미널': '고양백석', '공도정류소': '안성공도',
         '문막정류소': '원주문막', '기흥역시외버스정류소': '용인기흥역', '개양고속버스정류장': '진주개양', '안면버스터미널': '안면도', '진주혁신도시터미널': '진주혁신',
         '한국교통대정류소': '교통대', '호남제일문정류소': '호남제일', '대야공용버스터미널': '군산대야', '장유정류소': '김해장유', '장유고속버스환승정류장': '김해장유',
         '센트럴시티터미널': '센트럴시티(서울)', '동서울종합터미널': '동서울', '부산종합버스터미널': '부산', '동대구고속버스터미널': '동대구', '대전복합터미널': '대전복합'}
def norm(n):
    n = re.sub(r'\(.*?\)', '', n)
    n = re.sub(r'-.*?(방향|방면).*$', '', n)          # 「정안휴게소-천안방향-…」→ 정안
    n = re.sub(r'(ic|IC)$', '', n)
    for s in sorted(SUF, key=len, reverse=True): n = n.replace(s, '')
    return n.replace('-', '').replace(' ', '').replace('·', '')
tago = collections.defaultdict(list)
for t in ex:
    if re.search(r'구간|수수료|통합단말|공항왕복|모바일', t['terminalNm']): continue
    tago[t['terminalNm']].append(t['terminalId'])
tn = {norm(k): k for k in tago}
def ids(name):
    if name in ALIAS: return tago.get(ALIAS[name], [])
    n = norm(name)
    if n in tn: return tago[tn[n]]
    c = [k for k in tn if len(k) >= 2 and (n.startswith(k) or k.startswith(n))]
    if len(c) == 1: return tago[tn[c[0]]]
    return []
out, miss = [], collections.Counter()
for a, b in pairs:
    ia, ib = ids(a), ids(b)
    if ia and ib: out.append((a, b, ia, ib))
    else:
        if not ia: miss[a] += 1
        if not ib: miss[b] += 1
print('pairs', len(pairs), 'mapped', len(out), 'calls', sum(len(x[2]) * len(x[3]) for x in out))
print('unmapped top', miss.most_common(40))
json.dump(out, open('pairs-ids.json', 'w'), ensure_ascii=False)
