# 코레일 시각표 → 쩌모위키 시각표

매달 코레일이 내놓는 시각표 엑셀 두 개(일반열차·고속열차)를 위키 시각표 원문으로 바꾼다.

```
pip install openpyxl
python3 parse.py 일반열차.xlsx 고속열차.xlsx data.json   # 노선·방향별 표로 정리 (초는 버림)
python3 gen.py data.json out/                          # 노선마다 out/<노선>.wiki, 책 항목 out/items.json
```

- `gen.py` 의 `BOOK`(노선 순서·표), `HEADS`(노선 띠), `BRANCH`(갈래 구간)는 노선이 바뀔 때만 손본다.
- 통과(⇂)는 열차가 서는 두 역 사이의 역, 비경유(‥)는 `BRANCH`에서 그 열차가 쓰지 않는 갈래의 역.
- 오른쪽 역명은 엑셀의 한자 병기(간체·호환 한자는 정자로 고침). `--mix` 를 주면 머리 이름도 국한문혼용.
