# ttbook — 시각표 LaTeX 조판

위키 시각표(Module:Timetable)를 LuaLaTeX 로 조판해 인쇄용 PDF 를 만든다.

- 내용의 정본은 위키. 위키 문서 원문의 `{{#invoke:Timetable|main|data=…}}` 를
  위키 모듈(`src/Timetable.lua`, 위키에서 받은 사본)로 그대로 돌려 HTML 을 얻고,
  그 class·style 을 위키 CSS 와 같은 뜻으로 읽어 칸·괘선을 직접 계산한다.
- 괘선은 PDF 사각형으로 그린다(브라우저처럼 1px 로 반올림하지 않는다).
  굵기는 `book.json` 의 `rules` (mm): 가는 선 0.1 / 중간 0.25 / 굵은 0.35 / 이중선 [선, 사이].
- 글꼴은 `book.json` 의 `fonts` 에서 이름으로 지정 (시스템에 설치된 글꼴).

## 쓰는 법

    python3 ttbook.py book.json      # → build/<name>.pdf

필요한 것: TeX Live (lualatex, fontspec, graphicx, xcolor), Python 3, 글꼴(DiaPro, 명조·고딕).
