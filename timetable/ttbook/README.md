# ttbook — 시각표 LaTeX 조판

위키 시각표(Module:Timetable)를 LuaLaTeX 로 조판해 인쇄용 PDF 를 만든다.

- 내용의 정본은 위키. 위키 문서 원문의 `{{#invoke:Timetable|main|data=…}}` 를
  위키 모듈(`src/Timetable.lua`, 위키에서 받은 사본)로 그대로 돌려 HTML 을 얻고,
  그 class·style 을 위키 CSS 와 같은 뜻으로 읽어 칸·괘선을 직접 계산한다.
- 괘선은 PDF 사각형으로 그린다(브라우저처럼 1px 로 반올림하지 않는다).
  굵기는 `book.json` 의 `rules` (mm): 가는 선 0.1 / 중간 0.25 / 굵은 0.35 / 이중선 [선, 사이].
- 글꼴은 `book.json` 의 `fonts` 에서 이름으로 지정. `fontDirs` 의 폴더들에서 찾아 파일로 TeX 에 넘긴다.
- 글자 높이 맞춤은 손으로 정하지 않는다: 조판할 때마다 글꼴에서 잰다.
  기준은 명조 한자의 잉크 중심. 한글 글꼴(한글·문장 부호)과 다른 글꼴은 그 중심과의 차이만큼 옮긴다.
  사람이 정하는 것은 맞추는 비율 `alignStrength` (기본 0.85) 뿐 — 글꼴을 바꾸면 이름만 바꾸면 된다.
- 한글 문맥의 문장 부호(괄호·줄표·낫표 등)는 한글 글꼴을 먼저 쓴다. 세로 제목의 괄호·줄표는 한글 글꼴의 가로 글자를 돌려 잉크 가운데를 열 가운데에 둔다.

## 쓰는 법

    python3 ttbook.py book.json      # → build/<name>.pdf

필요한 것: TeX Live (lualatex, fontspec, luaotfload, graphicx, xcolor, xfp), Python 3 + fontTools, 글꼴(DiaPro, 명조·고딕).

맥(Claude 작업 VM)에서는 `./run.sh book-mac.json` — 맥의 글꼴 폴더(~/Library/Fonts 등)를 그대로 쓴다.
VM 의 TeX Live 에 없는 luaotfload 등은 `texmf/` 에 넣어 두고 run.sh 가 TEXMFHOME 으로 잡는다.
