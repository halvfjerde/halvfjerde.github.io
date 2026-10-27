local p = {}
local EDMAP = false   -- エディタのプレビュー用: 行・列の対応を data- 属性で出す

local byte, char, sub, find, gsub, match, gmatch, format =
      string.byte, string.char, string.sub, string.find, string.gsub,
      string.match, string.gmatch, string.format
local concat, tonumber, floor, min = table.concat, tonumber, math.floor, math.min

-- TemplateStyles を使う場合はページ名（nil なら出さない）
local STYLES_PAGE = nil   -- 例: "Template:Timetable/styles.css"

--------------------------------------------------------------------------
-- UTF-8
--------------------------------------------------------------------------
local function U(cp)
  if cp < 0x80 then return char(cp)
  elseif cp < 0x800 then
    return char(0xC0 + floor(cp / 0x40), 0x80 + cp % 0x40)
  elseif cp < 0x10000 then
    return char(0xE0 + floor(cp / 0x1000), 0x80 + floor(cp / 0x40) % 0x40, 0x80 + cp % 0x40)
  end
  return char(0xF0 + floor(cp / 0x40000), 0x80 + floor(cp / 0x1000) % 0x40,
              0x80 + floor(cp / 0x40) % 0x40, 0x80 + cp % 0x40)
end

local function ulen(s)            -- 文字数（継続バイト以外を数える）
  local _, n = gsub(s, "[^\128-\191]", "")
  return n
end

--------------------------------------------------------------------------
-- 1. 記号 — すべて DiaPro が持つコードポイント
--------------------------------------------------------------------------
local G = {
  pass   = U(0x21C2),  -- v   通過（レ形）          w1400
  none   = U(0x2025),  -- x   経由しない ‥          w1600
  other  = U(0x2551),  -- i   他線区経由 ║          w1000
  term   = U(0x2594),  -- -   終着（上寄せの一本線）  w2000
  term2  = U(0x207C),  -- --  終着（上寄せの二本線）  w2000
  dia    = U(0x25C6),  -- <>  ◆                    w1000
  div    = U(0x254C),  -- DIV ╌                    w2000
  ditto  = "〃",       -- q   （着発欄・本文フォント）
  arr    = "着", dep = "發", sp = "　",
}

-- 縦組み用括弧（DiaPro: 開きは行の下端、閉じは行の上端に描画）
local function bk(cp, o)
  return '<span class="jtt-bk jtt-bk--' .. (o and "o" or "c") .. '">' .. U(cp) .. "</span>"
end
local BRACKET = {
  PAO = bk(0xFE35, true), PAC = bk(0xFE36),   -- ︵ ︶
  TNO = bk(0xFE39, true), TNC = bk(0xFE3A),   -- ︹ ︺
  SUO = bk(0xFE3B, true), SUC = bk(0xEF3C),   -- 黒レンズ 開/閉
}

-- 2 文字トークン
local PAIR = {
  ["--"] = { t = G.term2, c = true },
  [">>"] = { t = "➡",     c = true },
  ["<>"] = { t = G.dia,   c = true },
  [".."] = { t = "." },
  ["rr"] = { t = '<span class="jtt-tcy">' },
  [":."] = { t = '<span class="jtt-td">.</span>', w = 0.36 },   -- 時刻の時と分の間の点
}

-- 1 文字トークン
local SINGLE = {
  x = { t = G.none,  c = true },
  v = { t = G.pass,  c = true },
  i = { t = G.other, c = true },
  q = { t = G.ditto, c = true },
  ["-"] = { t = G.term, c = true },
  [">"] = { t = "⇨",  c = true },
  c = { t = "",       c = true },
  k = { t = '<span class="jtt-k">' },
  b = { t = '<span class="jtt-b">' },
  g = { t = '<span class="jtt-g">' },
  r = { t = '<span class="jtt-v">' },
  ["."] = { t = "</span>" },
  ["/"] = { t = "<br>" },
}

-- 3 文字（大文字）トークン
local function cen(s) return { t = s, c = true } end
local WORD = {
  ARR = { t = G.arr }, DEP = { t = G.dep }, SPA = { t = G.sp },
  DIV = cen(G.div),
  -- 矢印・接続線（DiaPro 幅 2000）
  TRD = cen(U(0x2B0E)), TRU = cen(U(0x2B0F)), TLD = cen(U(0x2B10)), TLU = cen(U(0x2B11)),
  TDL = cen(U(0x21B2)), TDR = cen(U(0x21B3)), TUL = cen(U(0x21B0)), TUR = cen(U(0x21B1)),
  MLD = cen(U(0x250F)), MRD = cen(U(0x2513)), MLU = cen(U(0x2517)), MRU = cen(U(0x251B)),
  -- 旧版の空アイコン → DiaPro の該当グリフ
  LEX = cen(U(0xE05C)),  -- L特急
  LSL = cen(U(0xE05A)),  -- 寝台特急
  XSL = cen(U(0xE05B)),  -- 寝台急行
  GRR = cen(U(0xE050)),  -- グリーン車指定席
  GRN = cen(U(0xE051)),  -- グリーン車自由席
}

-- D{名前} — DiaPro のアイコン・種別マーク（大文字小文字を区別しない）
local ICON = {}
for name, cp in pairs({
  -- 種別マーク（幅 2000 = 時刻欄 1 列ぴったり）
  kukankaisoku = 0xE040, kukai = 0xE040, jyunkaisoku = 0xE041, jyunkai = 0xE041,
  kaisoku = 0xE042, shinkaisoku = 0xE043, shinkai = 0xE043,
  tokubetsukaisoku = 0xE044, tokkai = 0xE044, tsukinkaisoku = 0xE045, tsukai = 0xE045,
  chokutsukaisoku = 0xE046, chokkai = 0xE046, kyuko = 0xE047, tokkyu = 0xE048,
  kaisokutokkyu = 0xE049, kaitoku = 0xE049, tsukintokkyu = 0xE04A, tsutoku = 0xE04A,
  -- 設備・座席（幅 1000）
  reserved = 0xE020, somereserved = 0xE021, allreserved = 0xE022,
  greenreservedold = 0xE023, allnonreserved = 0xE029,
  greenreserved = 0xE050, greennonreserved = 0xE051, premiumgreen = 0xE052,
  granclass = 0xE053, granclassb = 0xE054, doubledecker = 0xE055,
  buffet = 0xE056, dining = 0xE057, nosmoking = 0xE059,
  sleeper = 0xE030, sleepersa1 = 0xE031, sleepersa2 = 0xE032,
  sleepera = 0xE033, sleepera1 = 0xE034, sleepera2 = 0xE035,
  sleeperb = 0xE036, sleeperb1 = 0xE037, sleeperb2 = 0xE038,
  limitedsleeper = 0xE05A, expresssleeper = 0xE05B, lexpress = 0xE05C,
  sl = 0xE060, n700 = 0xE061, e5 = 0xE062, bus = 0xE063,
  midorinomadoguchi = 0xE064, bicycle = 0xE068, airport = 0x1F6E7,
  inbound = 0x21E7, outbound = 0x21E9,          -- 上り / 下り 札
  attention = 0x329F, ben = 0x5F01,             -- ㊟ / 囲み「弁」
}) do ICON[name] = U(cp) end
local ICON_WIDE = { [0xE040]=1,[0xE041]=1,[0xE042]=1,[0xE043]=1,[0xE044]=1,[0xE045]=1,
                    [0xE046]=1,[0xE047]=1,[0xE048]=1,[0xE049]=1,[0xE04A]=1 }

-- バッジ  C{}丸 BC{}丸塗 S{}角 BS{}角塗 N{}列車番号 D{}DiaPro アイコン
local BADGE = { C = "jtt-bd jtt-bd--o", BC = "jtt-bd jtt-bd--o jtt-bd--f",
                S = "jtt-bd",           BS = "jtt-bd jtt-bd--f", N = true, D = true,
                VR = true, VP = true, VK = true, VB = true, DG = true, DR = true }

--------------------------------------------------------------------------
-- 2. セル内容の変換（1 パス）＋ 行ごとの幅の見積もり
--
--  幅の単位は「基準文字サイズの em」。時刻欄の中身は 2em（DiaPro 数字 4 桁）。
--  2em を超える行（「청량리」「K8002」等）は、時刻欄では横方向に詰めて
--  列幅をそろえる（jtt-sq）。
--------------------------------------------------------------------------
local COL_W = 2.0     -- 時刻欄の中身の幅（em）
local SM    = 0.8     -- 小さく組む部分の倍率（CSS の --jtt-sm と合わせる）

local function cpw(cp)                     -- 1 文字の幅（em）
  if cp < 0x80 then
    if cp >= 48 and cp <= 57 then return 0.5 end        -- DiaPro 数字
    if cp == 46 or cp == 32 then return 0.3 end
    -- 英字は DiaPro に無く本文書体（明朝・ゴシック）で出る。プロポーショナルなので大文字は広い
    if cp >= 65 and cp <= 90 then return 0.7 end         -- A–Z
    if cp >= 97 and cp <= 122 then return 0.52 end       -- a–z
    return 0.42                                          -- 記号
  end
  if cp == 0x2025 then return 1.6 end                    -- ‥
  if cp == 0x21C2 then return 1.4 end                    -- 通過
  if (cp >= 0x2460 and cp <= 0x2473) or cp == 0x24EA
     or (cp >= 0x3251 and cp <= 0x325E) then return 1.6 end   -- 横長丸数字
  if cp == 0x2594 or cp == 0x207C or cp == 0x254C
     or (cp >= 0xE040 and cp <= 0xE04A)
     or (cp >= 0x2B0E and cp <= 0x2B11) or (cp >= 0x21B0 and cp <= 0x21B3)
     or cp == 0x250F or cp == 0x2513 or cp == 0x2517 or cp == 0x251B then return 2.0 end
  return 1.0                                             -- 漢字・かな・ハングル等
end

local function textw(str)                  -- タグを除いた文字列の幅
  str = gsub(str, "<[^>]*>", "")
  local w, i, len = 0, 1, #str
  while i <= len do
    local b = byte(str, i)
    local cp, n
    if b < 0x80 then cp, n = b, 1
    elseif b < 0xE0 then cp, n = (b % 0x20) * 0x40 + byte(str, i + 1) % 0x40, 2
    elseif b < 0xF0 then cp, n = ((b % 0x10) * 0x40 + byte(str, i + 1) % 0x40) * 0x40 + byte(str, i + 2) % 0x40, 3
    else cp, n = 0x10000, 4 end
    w = w + cpw(cp); i = i + n
  end
  return w
end

local function tokw(tok)                   -- トークンの幅（初回に計算して保持）
  local w = tok.w
  if not w then w = textw(tok.t); tok.w = w end
  return w
end

local render

local function justify(s, cell)          -- '…' 均等割付
  local chars, n, i, len = {}, 0, 1, #s
  while i <= len do
    local b = byte(s, i)
    local w = (b < 0x80 and 1) or (b < 0xE0 and 2) or (b < 0xF0 and 3) or 4
    n = n + 1; chars[n] = sub(s, i, i + w - 1); i = i + w
  end
  if n <= 1 then cell.c = true; return s, textw(s) end
  return '<span class="jtt-j"><span>' .. concat(chars, "</span><span>") .. "</span></span>", textw(s)
end

-- 返り値: html, 幅(em)
-- 縦書きの注記ブロック（右から左へ読む）。括弧は DiaPro の縦組み用括弧（時刻欄 1 列の幅）を上下に置く
--   VR{…} 括弧なし / VP{…} ︵︶ / VK{…} ︹︺ / VB{…} 黒レンズ ︻…
local VBOX = { VR = false, VP = { 0xFE35, 0xFE36 }, VK = { 0xFE39, 0xFE3A }, VB = { 0xFE3B, 0xEF3C } }
-- 맨 바깥의 / 로만 나눈다（{ } の中の / はそのまま）
local function split_top(raw)
  local parts, depth, last = {}, 0, 1
  for i = 1, #raw do
    local ch = sub(raw, i, i)
    if ch == "{" then depth = depth + 1
    elseif ch == "}" then depth = depth - 1
    elseif ch == "/" and depth == 0 then parts[#parts + 1] = sub(raw, last, i - 1); last = i + 1 end
  end
  parts[#parts + 1] = sub(raw, last)
  return parts
end

local function badge(tag, raw, cell)
  if tag == "DG" or tag == "DR" then
    -- 斜線で区切った見出し（左上の「行先＼列車番号＼駅名」など）
    --   DG{右上/…/左下} は ＼ の線、DR{左上/…/右下} は ／（左右反対）。
    --   最後の線は角から角へ。それより上の線は、右（DR は左）の見出し行の境目で縁に当たる。
    --   部分ごとに受け持つ見出し行の数を「行先:1」のように書ける（既定は 1 行ずつ、最後の部分の手前が残り全部）。
    --   行の高さは表を組むときに見積もって --jtt-dgyK に入れる（render_grid）
    local parts, rows = split_top(raw), {}
    for k, part in ipairs(parts) do
      local body, nrow = match(part, "^(.-):(%d+)$")
      if body then parts[k] = body; rows[k] = tonumber(nrow) else rows[k] = 1 end
    end
    local n = #parts
    local cum, acc = {}, 0
    for k = 1, n - 2 do acc = acc + rows[k]; cum[k] = acc end
    local total = acc + (n >= 2 and rows[n - 1] or 1)
    local vars = { "--y0:0" }
    for k = 1, n - 2 do vars[#vars + 1] = format("--y%d:var(--jtt-dgy%d,%.3f)", k, k, cum[k] / total) end
    if n >= 2 then vars[#vars + 1] = format("--y%d:1", n - 1) end
    local DR = (tag == "DR")
    local o, sz, wmax, wsum = {}, {}, 0, 0
    local function place(xexpr, yexpr, inner)
      o[#o + 1] = '<span class="jtt-dgc1" style="left:calc(' .. xexpr .. ' * 100%);top:calc(' .. yexpr .. ' * 100%)">' .. inner .. "</span>"
    end
    for k, part in ipairs(parts) do
      local h, w = render(part, cell)
      if w > wmax then wmax = w end
      wsum = wsum + w
      sz[#sz + 1] = h
      local plain = gsub(h, "<[^>]*>", "")
      local chars = {}
      if not find(h, "<", 1, true) then
        for ch in gmatch(plain, "[%z\1-\127\194-\244][\128-\191]*") do chars[#chars + 1] = ch end
      else chars[1] = h end            -- 装飾付きの部分はまとめて 1 か所に
      local L = #chars
      if k < n then o[#o + 1] = format('<span style="--m:calc((var(--y%d) + var(--y%d)) / 2)">', k - 1, k) end
      for j, ch in ipairs(chars) do
        local sp = (L == 1) and 0.5 or (0.12 + (j - 0.5) / L * 0.76)
        local x, y
        if k < n then
          -- 帯の中心線: 縁の (1, m) から上の縁の (1 − m, 0) まで（線と平行）
          x = format("(1 - var(--m) * %.3f)", 1 - sp); y = format("(var(--m) * %.3f)", sp)
        else
          -- いちばん下の部分: 角から角への線より下の三角形
          x = format("%.3f", 0.5 * sp); y = format("%.3f", 0.5 + 0.5 * sp)
        end
        if DR then x = "(1 - " .. x .. ")" end
        place(x, y, ch)
      end
      if k < n then o[#o + 1] = "</span>" end
    end
    -- 線: 縁の高さ y で終わる線の位置は 100% − 50%·y（角から角が 50%）。色の位置は小さい順に
    local stops = {}
    for k = n - 1, 1, -1 do
      local pc = format("calc(100%% - var(--y%d) * 50%%)", k)
      stops[#stops + 1] = format("transparent calc(%s - .6px),var(--jtt-fg) calc(%s - .6px),var(--jtt-fg) calc(%s + .6px),transparent calc(%s + .6px)", pc, pc, pc, pc)
    end
    local dir = DR and "to top left" or "to top right"
    cell.dg = true; cell.dgcum = cum; cell.dgtotal = total
    return '<span class="jtt-dg" style="' .. concat(vars, ";") .. '"><span class="jtt-dgs" aria-hidden="true">' .. concat(sz, "<br>") .. "</span>"
      .. '<span class="jtt-dga"><span class="jtt-dgl" style="background:linear-gradient(' .. dir .. ",transparent," .. concat(stops, ",") .. ',transparent)"></span>'
      .. concat(o) .. "</span></span>", min(wmax + 1.5, COL_W)
  end
  if VBOX[tag] ~= nil then
    local h = render(raw, cell)
    local _, nbr = gsub(h, "<br>", "")
    local br = VBOX[tag]
    local o = '<span class="jtt-vbox">' .. (br and bk(br[1], true) or "")
      .. '<span class="jtt-vb">' .. h .. "</span>" .. (br and bk(br[2]) or "") .. "</span>"
    cell.c = true
    return o, math.max(nbr + 1, br and 2 or 0)
  end
  if tag == "N" then
    -- 列車番号は本文（明朝）・同じ大きさ。数字も明朝で出るので約 0.55em、英字は textw と同じ見積もり
    local h = render(raw, cell)
    local w = textw(h) + select(2, gsub(gsub(h, "<[^>]*>", ""), "%d", "")) * 0.05
    cell.c = true                                  -- 列車番号は既定で中央揃え
    return '<span class="jtt-no">' .. h .. "</span>", w
  end
  cell.c = true
  if tag == "D" then
    local key = gsub(string.lower(raw), "[%s_%-]", "")
    local g = ICON[key]
    if not g then
      return '<span class="jtt-err" title="D{} unknown">' .. raw .. "</span>", textw(raw)
    end
    return g, textw(g)
  end
  local inner, iw = render(raw, cell)
  local text  = gsub(inner, "<[^>]*>", "")
  local num   = tonumber(text)
  -- C{0..34}: DiaPro の横長丸数字（幅 1600）
  if tag == "C" and num and num >= 0 and num <= 34 and num == floor(num) then
    if num == 0 then return U(0x24EA), 1.6 end
    if num <= 20 then return U(0x2460 + num - 1), 1.6 end
    return U(0x3251 + num - 21), 1.6
  end
  local cls = BADGE[tag]
  -- 여러 줄（S{急/行}）・縦書き（S{r急行.}）の囲み: 高さを中身に合わせる。幅は いちばん長い行で決める
  local nl = select(2, gsub(inner, "<br>", "")) + 1
  local vert = find(inner, 'class="jtt-v"', 1, true) ~= nil
  local n = 0
  for line in gmatch(gsub(inner, "<br>", "\n") .. "\n", "([^\n]*)\n") do
    local u = ulen(gsub(line, "<[^>]*>", "")); if u > n then n = u end
  end
  local w
  if vert then
    cls = cls .. " jtt-bd--vt"
    w = 1.3 * SM
    return '<span class="' .. cls .. '"><span>' .. inner .. "</span></span>", w
  end
  if nl > 1 then cls = cls .. " jtt-bd--ml" end
  if num then
    -- 数字バッジ（「1.2」等）は字幅どおり。横長クラスは付けない
    cls = cls .. " jtt-bd--n"
    w = (iw + 0.4) * SM
  elseif n >= 2 then
    cls = cls .. " jtt-bd--w" .. min(n, 4)
    w = (n == 2 and 2.2 or 2.4) * SM
  else
    w = 1.3 * SM
  end
  return '<span class="' .. cls .. '"><span>' .. inner .. "</span></span>", w
end

-- lines を渡すと最上位の呼び出しとして行ごとの {first,last,w,nosq} を記録する
render = function(s, cell, lines)
  local out, n, i, len = {}, 0, 1, #s
  local cur = lines and { first = 1, w = 0 } or nil
  local w, maxw = 0, 0
  local function add(x) w = w + x; if cur then cur.w = cur.w + x end end
  local function newline(nosq_prev, excl)
    if w > maxw then maxw = w end
    w = 0
    if cur then
      cur.last = excl and (n - 1) or n; if nosq_prev then cur.nosq = true end
      lines[#lines + 1] = cur
      cur = { first = n + 1, w = 0 }
    end
  end
  while i <= len do
    local b = byte(s, i)
    if b >= 0x80 then
      local bw = (b < 0xE0 and 2) or (b < 0xF0 and 3) or 4
      local ch = sub(s, i, i + bw - 1)
      n = n + 1; out[n] = ch; add(textw(ch)); i = i + bw
    else
      local tok = PAIR[sub(s, i, i + 1)]
      if tok then
        n = n + 1; out[n] = tok.t; add(tokw(tok)); if tok.c then cell.c = true end; i = i + 2
      elseif b == 1 and find(s, "\2", i + 1, true) then    -- 時刻の区切り（timesep）
        local close = find(s, "\2", i + 1, true)
        n = n + 1; out[n] = '<span class="jtt-td">' .. gsub(gsub(sub(s, i + 1, close - 1), "&", "&amp;"), "<", "&lt;") .. "</span>"
        add(0.36); i = close + 1
      elseif b == 96 and find(s, "`", i + 1, true) then   -- `…` 記号として読まない素の文字列（英字など）
        local close = find(s, "`", i + 1, true)
        local lit = sub(s, i + 1, close - 1)
        n = n + 1; out[n] = '<span class="jtt-lit">' .. gsub(gsub(lit, "&", "&amp;"), "<", "&lt;") .. "</span>"
        add(textw(lit)); i = close + 1
      elseif b == 106 and byte(s, i + 1) == 39 and find(s, "'", i + 2, true) then
        -- j'…' 縦に均等割付（字間と同じだけ上下にも空ける）。見出しのキロ欄など
        local close = find(s, "'", i + 2, true)
        local t, cs = sub(s, i + 2, close - 1), {}
        for ch in gmatch(t, "[%z\1-\127\194-\244][\128-\191]*") do cs[#cs + 1] = "<span>" .. ch .. "</span>" end
        n = n + 1; out[n] = '<span class="jtt-vj">' .. concat(cs) .. "</span>"
        add(1); cell.c = true; i = close + 1
      elseif b == 39 then                                  -- '
        local close = find(s, "'", i + 1, true)
        if close then
          local h, jw = justify(sub(s, i + 1, close - 1), cell)
          n = n + 1; out[n] = h; add(jw); i = close + 1
        else
          n = n + 1; out[n] = "'"; add(0.3); i = i + 1
        end
      elseif b >= 65 and b <= 90 then                      -- A-Z
        local tag, body = match(s, "^(%u%u?)(%b{})", i)
        if tag and BADGE[tag] then
          local h, bw = badge(tag, sub(body, 2, -2), cell)
          n = n + 1; out[n] = h; add(bw)
          i = i + #tag + #body
        else
          local w3 = sub(s, i, i + 2)
          local br = BRACKET[w3]
          if br then
            -- 括弧は必ず 1 行を占有（前後で行を区切る）。直後の "/" は読み飛ばす
            if n > 0 then newline() end
            n = n + 1; out[n] = br
            cell.c = true; i = i + 3
            newline(true)
            if sub(s, i, i) == "/" then i = i + 1 end
          else
            local wt = WORD[w3]
            if wt then
              n = n + 1; out[n] = wt.t; add(tokw(wt)); if wt.c then cell.c = true end; i = i + 3
            else
              n = n + 1; out[n] = char(b); add(cpw(b)); i = i + 1
            end
          end
        end
      else
        local ch = char(b)
        tok = SINGLE[ch]
        if tok then
          n = n + 1; out[n] = tok.t; if tok.c then cell.c = true end
          if ch == "/" then newline(false, true)
          elseif ch == "r" then if cur then cur.nosq = true end; cell.vert = true
          else add(tokw(tok)) end
        else
          n = n + 1; out[n] = ch; add(cpw(b))
        end
        i = i + 1
      end
    end
  end
  if w > maxw then maxw = w end
  if cur then cur.last = n; lines[#lines + 1] = cur end
  return concat(out), maxw, out
end

-- 時刻欄用: 2em を超える行を jtt-sq で横に詰めた HTML（不要なら nil）
local function squeeze(out, lines)
  local changed = false
  local o = {}
  for k = 1, #out do o[k] = out[k] end
  for _, ln in ipairs(lines) do
    if not ln.nosq and ln.w > COL_W + 0.05 and ln.last >= ln.first then
      local seg = concat(o, "", ln.first, ln.last)
      local _, opens  = gsub(seg, "<span", "")
      local _, closes = gsub(seg, "</span>", "")
      if opens == closes then
        local r = floor(COL_W / ln.w * 1000) / 1000
        o[ln.first] = '<span class="jtt-sq" style="--r:' .. r .. '"><span>' .. o[ln.first]
        o[ln.last]  = o[ln.last] .. "</span></span>"
        changed = true
      end
    end
  end
  return changed and concat(o) or nil
end

--------------------------------------------------------------------------
-- 3. セル解析（属性 ; 内容）— 同一文字列はキャッシュ
--------------------------------------------------------------------------
local parsed = {}

--------------------------------------------------------------------------
-- セル属性（"属性;内容" の属性部）
--   旧形式の短縮記法: h ^N <N ~N & # !!（そのまま使える）
--   名前付き（空白区切り）:
--     罫線  bt bb bl br（上下左右） b（四辺） bx（左右） by（上下）
--           = 0 無 / 1 細 / 2 太 / 3 極太 / d 二重 / . 点線 / - 破線
--     揃え  al=l|c|r   va=t|m|b
--     文字  fw=b|n  fs=xs|sm|lg|xl|<数値em/%>  font=dia|text|sans  fc=色  ls=字間  lh=行高
--     背景  bg=色   inv（白黒反転）
--     寸法  w=幅  ht=高さ  pad=余白   rs=N cs=N（結合）
--     その他 v（縦書き） wrap（折り返し可） cls=クラス,…  css=生CSS
--------------------------------------------------------------------------
local BSTYLE = { ["0"] = "none", ["1"] = "1px solid", ["2"] = "2px solid", ["3"] = "3px solid",
                 d = "3px double", ["."] = "1px dotted", ["-"] = "1px dashed" }
local BSIDE = { bt = { "top" }, bb = { "bottom" }, bl = { "left" }, br = { "right" },
                b = { "top", "bottom", "left", "right" }, bx = { "left", "right" }, by = { "top", "bottom" } }
local FSIZE = { xs = ".65em", sm = "var(--jtt-sm)", lg = "1.2em", xl = "1.44em" }
local FONT  = { dia = '"DiaPro", var(--jtt-text)', text = "var(--jtt-text)", sans = "var(--jtt-sans)",
                diasans = '"DiaPro", var(--jtt-sans)' }
local ALIGN = { l = "left", c = "center", r = "right" }
local VALIGN = { t = "top", m = "middle", b = "bottom" }

local function unit(v)
  if match(v, "^%-?[%d.]+$") then return v .. "em" end
  return v
end

local function parse_attrs(a, c)
  local st, cls = {}, {}
  for tok in gmatch(a, "%S+") do
    local k, v = match(tok, "^([%a_%-]+)=(.*)$")
    if k then
      if BSIDE[k] then
        local b = BSTYLE[v] or v
        local col = (b == "none") and "" or " var(--jtt-fg)"
        for _, side in ipairs(BSIDE[k]) do st[#st + 1] = "border-" .. side .. ":" .. b .. col end
      elseif k == "al" then st[#st + 1] = "text-align:" .. (ALIGN[v] or v)
      elseif k == "va" then st[#st + 1] = "vertical-align:" .. (VALIGN[v] or v)
      elseif k == "fw" then st[#st + 1] = "font-weight:" .. ((v == "b" and "700") or (v == "n" and "400") or v) .. "!important"
        if v == "b" then cls[#cls + 1] = "jtt-fb" end   -- DiaPro の数字は太字を "titl" で出す（Regular しか登録しないため）
      elseif k == "fs" then st[#st + 1] = "font-size:" .. (FSIZE[v] or unit(v)) .. "!important"
      elseif k == "font" then st[#st + 1] = "font-family:" .. (FONT[v] or v) .. "!important"
      elseif k == "fc" then st[#st + 1] = "color:" .. v
      elseif k == "bg" then st[#st + 1] = "background:" .. v
      elseif k == "ls" then st[#st + 1] = "letter-spacing:" .. unit(v) .. "!important"
      elseif k == "lh" then st[#st + 1] = "line-height:" .. v
      elseif k == "w" then local u = unit(v); st[#st + 1] = "width:" .. u .. ";min-width:" .. u .. ";max-width:" .. u
      elseif k == "ht" then st[#st + 1] = "height:" .. unit(v)
      elseif k == "pad" then st[#st + 1] = "padding:" .. gsub(v, ",", " ")
      elseif k == "ml" then st[#st + 1] = "margin-left:" .. unit(v)    -- 左を空ける（上段の項目など）
      elseif k == "mr" then st[#st + 1] = "margin-right:" .. unit(v)
      elseif k == "rs" then c.rs = tonumber(v)
      elseif k == "cs" then c.cs = tonumber(v)
      elseif k == "cls" then for x in gmatch(v, "[^,]+") do cls[#cls + 1] = x end
      elseif k == "css" then st[#st + 1] = gsub(v, ",", ";")
      elseif k == "vl" then                              -- セルの中央を通る縦線（矢印の軸など）
        cls[#cls + 1] = "jtt-vl"; st[#st + 1] = "--jtt-vl:" .. (BSTYLE[v] or v)
      elseif k == "vp" then                              -- 縦線の位置 l=左端 c=中央 r=右端
        cls[#cls + 1] = "jtt-vp--" .. v
      elseif k == "ah" then                              -- 矢じり d=下向き u=上向き（大文字は塗り）
        local lv = string.lower(v)
        cls[#cls + 1] = "jtt-ah jtt-ah--" .. lv .. ((v ~= lv) and " jtt-ah--f" or "")
      end
    elseif tok == "!!" or find(tok, "!!", 1, true) then
      c.skip = true
    elseif tok == "v" then c.vwrap = true
    elseif tok == "inv" then st[#st + 1] = "color:var(--jtt-bg);background:var(--jtt-fg)"
    elseif tok == "wrap" then c.wrapc = true
    elseif match(tok, "^[h%^<~&#%d]+$") then             -- 旧形式の短縮記法
      local rs, cs, ht = match(tok, "%^(%d+)"), match(tok, "<(%d+)"), match(tok, "~(%d+)")
      if rs then c.rs = tonumber(rs) end
      if cs then c.cs = tonumber(cs) end
      if ht then c.ht = tonumber(ht) end
      if find(tok, "h", 1, true) then c.th = true end
      if find(tok, "&", 1, true) then c.line = 1
      elseif find(tok, "#", 1, true) and c.line ~= 1 then c.line = 0 end
    end
  end
  if #st > 0 then c.style = concat(st, ";") end
  if #cls > 0 then c.cls = concat(cls, " ") end
end

local function parse_cell(raw)
  local c = parsed[raw]
  if c then return c end
  c = {}
  local s = raw
  local semi = find(s, ";", 1, true)
  if semi then
    local a = sub(s, 1, semi - 1)
    s = match(sub(s, semi + 1), "^%s*(.-)%s*$")
    if find(a, "!!", 1, true) then
      c.skip = true
    else
      parse_attrs(a, c)
    end
  elseif find(s, "!!", 1, true) then
    c.skip = true
  end
  if not c.skip then
    if s == "" or not find(s, "[^%d ]") then
      c.html = s
      c.w = textw(s)
    else
      local lines = {}
      local html, mw, out = render(s, c, lines)
      c.html = html
      c.w = mw
      c.html_t = squeeze(out, lines)     -- 時刻欄で使う版（詰める行が無ければ nil）
    end
    if c.vwrap then
      c.html = '<span class="jtt-v">' .. c.html .. "</span>"
      c.html_t = nil
    end
    if c.wrapc then
      -- 表の幅を押し広げずに、他の行で決まった幅の中で折り返す
      c.html = '<div class="jtt-wr">' .. c.html .. "</div>"
      c.html_t = nil
    end
  end
  parsed[raw] = c
  return c
end

--------------------------------------------------------------------------
-- 4. CSV
--------------------------------------------------------------------------
local function parse_csv(csv)
  local rows, nr = {}, 0
  for line in gmatch(csv, "[^\r\n]+") do
    if find(line, "%S") then
      local row, nc = {}, 0
      for cell in gmatch(line .. ",", "([^,]*),") do
        nc = nc + 1; row[nc] = match(cell, "^%s*(.-)%s*$")
      end
      nr = nr + 1; rows[nr] = row
    end
  end
  return rows
end

--------------------------------------------------------------------------
-- 5. タイトル   n=上り札 k=下り札 m=上り白札 j=下り白札 u=細字 l=囲み .=閉じ >=—
--------------------------------------------------------------------------
local TITLE = {
  n = '<span class="jtt-dir jtt-dir--up">',
  k = '<span class="jtt-dir jtt-dir--down">',
  m = '<span class="jtt-dir jtt-dir--up jtt-dir--o">',     -- 속 빈(흰) 상행 표지
  j = '<span class="jtt-dir jtt-dir--down jtt-dir--o">',   -- 속 빈(흰) 하행 표지
  u = '<span class="jtt-sub">',
  l = '<span class="jtt-box">',
  ["."] = "</span>",
  [">"] = "︱",
}
-- 縦書きのタイトルでは、欧文の括弧・ダッシュは寝かせて置かれ、書体によって列の中心からずれる。
-- 縦書き用の字形（︵︶︱）に置き換えて、どの書体でも列の中心に立てる
local VERT = { ["("] = "︵", [")"] = "︶", ["（"] = "︵", ["）"] = "︶", ["—"] = "︱", ["―"] = "︱" }
local function render_title(s)
  s = gsub(s, "'''(.-)'''", "%1")       -- 太字指定は不要（タイトルは元々太字）
  s = gsub(s, "[()]", VERT)
  s = gsub(s, "（", VERT["（"]); s = gsub(s, "）", VERT["）"])
  s = gsub(s, "—", VERT["—"]); s = gsub(s, "―", VERT["―"])
  return (gsub(s, "[nkmjul%.>]", TITLE))
end

--------------------------------------------------------------------------
-- 6. 本体
--------------------------------------------------------------------------
local ROLE = { "km", "mk", "st", "ad" }   -- 左ブロック（右詰めで割り当て）
-- 組み込みの役割。これ以外の名前（cols fare st ad の fare など）は利用者が足す欄で、
-- 値は素の文字列、幅は width.名前（基準文字の倍数、既定 3.6）、見出しは label.名前
local BUILTIN_ROLE = { km = true, mk = true, st = true, ad = true, alt = true }
local DEFAULT_W = { km = 3.0, mk = 2.6, alt = 7.0, st = 6.4, ad = 1.2 }   -- CSS の --jtt-km などと同じ値

-- 한글(은바탕·은돋움)은 숫자·한자보다 낮게 앉으므로, 태그 밖 글자의 한글만 <span class="jtt-hg"> 로 감싸 CSS 로 자리를 올린다
local function hg_wrap(s)
  return (gsub(s, ">([^<]+)", function(t)
    if not find(t, "[\234-\237]") then return nil end
    t = gsub(t, "[\234-\237][\128-\191][\128-\191]", "<span class=\"jtt-hg\">%0</span>")
    t = gsub(t, "</span><span class=\"jtt%-hg\">", "")
    return ">" .. t
  end))
end

-- 表示用の 2 次元セル配列（旧 CSV と同じトークン文字列）を HTML にする共通部
local function render_grid(frame, rows, H, L, F, title, opt)
  opt = opt or {}
  local N = #rows

  local maxcols = 0
  for r = 1, N do if #rows[r] > maxcols then maxcols = #rows[r] end end

  -- 列位置 → 役割 class（足した欄は位置と幅を style で持つ）
  local poscls, roles, colsty = {}, {}, {}
  if opt.roles then
    for k = 1, L do roles[k] = opt.roles[k] end   -- 新形式: cols の実際の役割
  else
    for k = 1, min(L, 4) do roles[k] = ROLE[4 - min(L, 4) + k] end
  end
  local RR, TT = opt.R or {}, opt.T
  -- 上下併記（mid）: 駅欄（左ブロック）は 下り列車のあと a+1 … a+L。それ以外は列車
  local MD = opt.mid
  local function lidx(j)
    if MD then if j > MD.a and j <= MD.a + L then return j - MD.a end; return nil end
    if j <= L then return j end
    return nil
  end
  for j = 1, maxcols do
    local rq = TT and (j - L - TT)
    local li = lidx(j)
    if not MD and rq and rq >= 1 and RR[rq] then
      poscls[j] = "jtt-rc jtt-r-" .. RR[rq] .. ((rq == 1) and " jtt-rc1" or "")
    elseif not li then
      poscls[j] = (j == L + 1 or (MD and (j == 1 or j == MD.a + L + 1))) and "jtt-t jtt-t1" or "jtt-t"
    else
      local r = opt.roles and roles[li] or roles[li - (L - min(L, 4))]
      if r and not BUILTIN_ROLE[r] then
        poscls[j] = "jtt-cx jtt-cx-" .. r
        colsty[j] = "left:var(--jtt-o-" .. r .. ");width:var(--jtt-" .. r .. ");min-width:var(--jtt-" .. r .. ")"
      else
        poscls[j] = r and ("jtt-" .. r) or "jtt-km"
      end
    end
  end

  -- 左の欄に要る幅の見積もり（1 列だけのセル。基準文字の倍数。余白込み）
  local colneed = {}
  if opt.roles then
    local j0 = MD and MD.a or 0
    for r = 1, N do
      for j = j0 + 1, min(j0 + L, #rows[r]) do
        local c = parse_cell(rows[r][j])
        local li = j - j0
        if not c.skip and not (c.cs and c.cs > 1) and not c.th and not c.dg and c.w then
          local role = roles[li]
          local sc = (role == "mk" or role == "ad") and 0.8 or 1
          local need = c.w * sc + ((role == "ad") and 0.15 or 0.35)
          if not colneed[li] or need > colneed[li] then colneed[li] = need end
        end
      end
    end
  end

  -- sticky オフセット（CSS 変数）。estw: 表の幅の見積もり（基準文字。見出し帯を折り返すかどうかに使う）
  local vars, acc = {}, {}
  local estw = 0
  for k = 1, #roles do
    local t = roles[k]
    -- 幅: 足した欄は width.名前（既定 3.6）、組み込みの欄も width.km などで CSS の既定を上書きできる。
    -- 固定（sticky）の位置はこの幅の和で決まるので、中身が幅を超えるとスクロール時に重なる
    local w = tonumber(opt.set and opt.set["width." .. t]) or (not BUILTIN_ROLE[t] and 3.6) or nil
    -- 中身がこの幅を超える欄（「釜山ヨリ」の入ったキロ欄など）は広げる。固定の位置がずれて重ならないように
    local need = colneed[k]
    if need and need > (w or DEFAULT_W[t] or 0) + 0.05 then w = need end
    if w then vars[#vars + 1] = "--jtt-" .. t .. ":calc(" .. format("%.2f", w) .. " * var(--jtt-fs))" end
    estw = estw + (w or DEFAULT_W[t] or 3.6)
    local off = (#acc == 0 and "0px") or (#acc == 1 and acc[1]) or ("calc(" .. concat(acc, " + ") .. ")")
    vars[#vars + 1] = "--jtt-o-" .. t .. ":" .. off
    acc[#acc + 1] = "var(--jtt-" .. t .. ")"
  end

  local tdcache = {}
  local function td(c, j, extra)      -- extra: その位置だけの style（斜線見出しの線の位置など）
    local cls = poscls[j]
    local plain = not (c.cs or c.th or colsty[j] or extra)
    local bucket
    if plain then
      bucket = tdcache[cls]
      if not bucket then bucket = {}; tdcache[cls] = bucket end
      local hit = bucket[c]
      if hit then return hit end
    end
    local a = { '<td class="', cls }
    if j == 1 then a[#a + 1] = " jtt-c1" end
    if opt.roles and L > 0 then
      -- 新形式: 左ブロックの区切り線は「最後の左列」に引く（着発が最後でない並びもあるため）
      local li = lidx(j)
      if li == L then a[#a + 1] = " jtt-lend"
      elseif li and roles[li] == "ad" then a[#a + 1] = " jtt-adin" end
    end
    if c.th then a[#a + 1] = " jtt-th" end
    if c.c  then a[#a + 1] = " jtt-c"  end
    if c.dg then a[#a + 1] = " jtt-dgc" end
    if c.cls then a[#a + 1] = " " .. c.cls end
    a[#a + 1] = '"'
    if c.rs and c.rs > 1 then a[#a + 1] = ' rowspan="' .. c.rs .. '"' end
    local cs = c.cs or (c.th and (L - 1))
    if cs then
      cs = min(cs, maxcols - j + 1)
      local li = lidx(j)
      if opt.roles and li then cs = min(cs, L - li + 1) end   -- 左欄の結合は左欄の中で止める
      if cs > 1 then a[#a + 1] = ' colspan="' .. cs .. '"' end
    end
    local xs = colsty[j]
    if extra then xs = xs and (xs .. ";" .. extra) or extra end
    if c.ht or c.style or xs then
      a[#a + 1] = ' style="' .. (xs and (xs .. ((c.ht or c.style) and ";" or "")) or "") .. (c.ht and ("height:" .. c.ht .. "px" .. (c.style and ";" or "")) or "")
        .. (c.style or "") .. '"'
    end
    a[#a + 1] = ">"
    -- 横詰めは時刻欄 1 列分のセルだけ（結合セル・見出し・右欄には使わない）
    a[#a + 1] = (not lidx(j) and (MD or not TT or j <= L + TT) and not c.th and not (c.cs and c.cs > 1) and c.html_t) or c.html
    a[#a + 1] = "</td>"
    local s = concat(a)
    if plain then bucket[c] = s end
    return s
  end

  local out = {}
  if STYLES_PAGE then
    out[#out + 1] = frame:extensionTag("templatestyles", "", { src = STYLES_PAGE })
  end
  local tp = opt.top
  if tp then
    -- 枠の外の上段（左の縦書きタイトルと同じく、セルにしない）。[top] の各行が 1 段、
    -- 各項目は al=l|c|r で左・中央・右の組に入り、fs= fw= fc= bg= pad= などで自由に組める
    local sty = ""
    if tp.style and tp.style ~= "" then
      local pc = parse_cell(tp.style .. "; x")
      if pc.style then sty = ' style="' .. pc.style .. '"' end
    end
    local o = { '<div class="jtt-wrap jtt-wrap--top' .. (opt.tside and " jtt-wrap--tr" or "") .. (opt.mid and " jtt-both" or "") .. '"><div class="jtt-top"' .. sty .. '>' }
    for _, row in ipairs(tp.rows) do
      local g = { l = {}, c = {}, r = {} }
      for _, item in ipairs(row) do
        if item and item ~= "" and not find(item, "!!", 1, true) then
          local a = match(item, "^([^;]*);")
          local al = a and match(" " .. a .. " ", "%sal=(%a)") or "l"
          if not g[al] then al = "l" end
          local pc = parse_cell(item)
          local list = g[al]
          list[#list + 1] = '<span class="jtt-ti' .. (pc.cls and (" " .. pc.cls) or "") .. '"'
            .. (pc.style and (' style="' .. gsub(pc.style, "text%-align:%a+;?", "") .. '"') or "") .. '>' .. (pc.html or "") .. '</span>'
        end
      end
      o[#o + 1] = '<div class="jtt-trow"><div class="jtt-tl">' .. concat(g.l) .. '</div><div class="jtt-tm">' .. concat(g.c)
        .. '</div><div class="jtt-tr">' .. concat(g.r) .. '</div></div>'
    end
    o[#o + 1] = '</div><div class="jtt-row"><div class="jtt-title">'
    out[#out + 1] = concat(o)
  else
    out[#out + 1] = '<div class="jtt-wrap' .. (opt.tside and " jtt-wrap--tr" or "") .. (opt.mid and " jtt-both" or "") .. '"><div class="jtt-title">'
  end
  out[#out + 1] = render_title(title or "")
  out[#out + 1] = '</div><div class="jtt-frame">'

  -- 1 行目が h セル 1 個だけ → スクロールしない路線見出し帯
  local first = 1
  if N >= 1 then
    local only, cnt = nil, 0
    for j = 1, #rows[1] do
      local c = parse_cell(rows[1][j])
      if not c.skip then cnt = cnt + 1; only = c end
    end
    if cnt == 1 and only.th then
      out[#out + 1] = '<div class="jtt-head"'
        .. (only.ht and (' style="height:' .. only.ht .. 'px"') or "") .. '>'
        .. (find(only.html, "<br>", 1, true) and ('<div class="jtt-hin">' .. only.html .. '</div>') or only.html) .. '</div>'
      first = 2
    end
  end

  if opt.head then
    local hd = opt.head
    local pw = {}
    local function part(s, k)
      if not s or s == "" then pw[k] = 0; return "" end
      local pc = parse_cell("c; " .. s)
      pw[k] = pc.w or 0
      return pc.html or ""
    end
    local hl, hm, hr = part(hd.l, "l"), part(hd.c, "c"), part(hd.r, "r")
    -- 表が狭くて 1 行に収まらないときは折り返す: 上の行に左・右、下の行に中央。中央は「―」の後ろで改行する
    -- 表の幅の見積もり: 左右の欄 + 列車数 × 2.3（CSS の時刻欄の最小幅）
    local tw = estw + (opt.T or 0) * 2.3
    for _, r in ipairs(opt.R or {}) do tw = tw + (DEFAULT_W[r] or 3.6) end
    local wrap = tw > 0 and (pw.l + pw.c + pw.r + 2 + 1.8 > tw)
    if wrap then hm = gsub(hm, " ―", "\194\160―") end
    local sty = {}
    if hd.ht and hd.ht ~= "" then sty[#sty + 1] = "min-height:" .. (match(hd.ht, "^%d+$") and (hd.ht .. "px") or hd.ht) end
    if hd.style and hd.style ~= "" then
      local pc = parse_cell(hd.style .. "; x")
      if pc.style then sty[#sty + 1] = pc.style end
      local va = match(" " .. hd.style .. " ", "%sva=(%a)%s")
      if va then sty[#sty + 1] = "align-items:" .. (({ t = "flex-start", b = "flex-end" })[va] or "center") end
    end
    -- 折り返すとき、中央は左・右のうちある方の反対側に寄せる
    local side = ""
    if wrap then
      if pw.l > 0 and pw.r == 0 then side = " jtt-head--cr" elseif pw.r > 0 and pw.l == 0 then side = " jtt-head--cl" end
    end
    out[#out + 1] = '<div class="jtt-head jtt-head--x' .. (wrap and " jtt-head--wrap" or "") .. side .. '"' .. (#sty > 0 and (' style="' .. concat(sty, ";") .. '"') or "") .. '>'
      .. '<div class="jtt-hl">' .. hl .. '</div><div class="jtt-hm">' .. hm
      .. '</div><div class="jtt-hrt">' .. hr .. '</div></div>'
  end
  local dcols = ""
  if opt.cinfo then
    local cc = {}
    for j = 1, maxcols do
      local ci = opt.cinfo[j]
      cc[j] = not ci and "-" or ci.kind == "train" and ("t:" .. ci.ti) or ((ci.kind == "right" and "r:" or "l:") .. (ci.role or ""))
    end
    dcols = ' data-cols="' .. concat(cc, ",") .. '"'
  end
  out[#out + 1] = '<div class="jtt-scroll"><table class="jtt"' .. dcols .. ' style="' .. concat(vars, ";") .. '">'

  -- 行の高さの見積もり（斜線見出しの線を右の見出し行の境目に合わせるため。単位は基準文字）
  local esth = {}
  local function est_cell(c)
    local html = c.html or ""
    if html == "" then return 1.2 end
    if find(html, "jtt-v", 1, true) then
      local t = gsub(gsub(html, "<br>", "\n"), "<[^>]*>", "")
      local mx = 0
      for seg in gmatch(t .. "\n", "([^\n]*)\n") do local u = ulen(seg); if u > mx then mx = u end end
      return mx * 1.05 + 0.5
    end
    local _, nbr = gsub(html, "<br>", "")
    return (nbr + 1) * 1.25 + (find(html, "jtt-bd", 1, true) and 0.4 or 0.2)
  end
  local function row_h(r)
    if esth[r] then return esth[r] end
    local h = 1.2
    for j = 1, #rows[r] do
      local c = parse_cell(rows[r][j])
      if not lidx(j) and not c.skip and not (c.rs and c.rs > 1) then local e = est_cell(c); if e > h then h = e end end
    end
    esth[r] = h
    return h
  end
  local function dg_vars(c, r)
    local rs = c.rs or 1
    if rs < 2 or not c.dgcum or #c.dgcum == 0 then return nil end
    local hs, tot = {}, 0
    for i = 0, rs - 1 do local h = rows[r + i] and row_h(r + i) or 1.2; hs[i + 1] = h; tot = tot + h end
    local o = {}
    for k, ck in ipairs(c.dgcum) do
      local acc = 0
      for i = 1, min(ck, rs - 1) do acc = acc + hs[i] end
      o[#o + 1] = format("--jtt-dgy%d:%.3f", k, acc / tot)
    end
    return concat(o, ";")
  end

  for r = first, N do
    local row = rows[r]
    local cells, nc, line = {}, 0, nil
    for j = 1, #row do
      local c = parse_cell(row[j])
      if not c.skip then
        if c.line then line = c.line end
        nc = nc + 1; cells[nc] = td(c, j, c.dg and dg_vars(c, r) or nil)
      end
    end
    local cls
    if     r <= H         then cls = "jtt-hr"
    elseif r == H + 1     then cls = "jtt-b1"
    elseif r == N - F + 1 then cls = "jtt-f1"
    elseif r >  N - F     then cls = "jtt-fr" end
    if line == 1 then cls = (cls and cls .. " " or "") .. "jtt-ln"
    elseif line == 0 then cls = (cls and cls .. " " or "") .. "jtt-nl" end
    local rm = opt.rmeta and opt.rmeta[r]
    if rm and rm.part == "trk" then cls = (cls and cls .. " " or "") .. "jtt-trk" end   -- 番線の段
    local dm = ""
    if opt.rinfo then
      local ri = opt.rinfo[r] or { kind = "raw" }
      dm = ' data-m="' .. (ri.kind or "") .. ":" .. gsub((gsub(ri.key or "", "&", "&amp;")), '"', "&quot;") .. '"'
    end
    out[#out + 1] = cls and ('<tr class="' .. cls .. '"' .. dm .. '>') or ("<tr" .. dm .. ">")
    out[#out + 1] = concat(cells)
    out[#out + 1] = "</tr>"
  end

  out[#out + 1] = "</table></div>"
  if opt.notes then out[#out + 1] = opt.notes end
  out[#out + 1] = tp and "</div></div></div>" or "</div></div>"
  return hg_wrap(concat(out))
end

-- 旧形式: {{#invoke:Timetable|csv|header=|left=|footer=|title=|<CSV>}}
function p.csv(frame)
  local args = frame.args
  return render_grid(frame, parse_csv(args[1] or ""),
    tonumber(args.header) or 4, tonumber(args.left) or 3, tonumber(args.footer) or 1, args.title)
end

--------------------------------------------------------------------------
-- 7. 新形式（列車ごとに 1 行の専用記法）
--
--   {{#invoke:Timetable|main|data=
--   title "k下り. 函館本線 u(青森 > 函館 > 倶知安)."
--   [rows]               見出し行      キー ラベル [fmt=…]
--   [footer]             脚注行        キー ラベル [fmt=…]
--   [stations]           駅（表示行）  キロ 印 駅名 着発 ／ --- は罫線
--   [trains]             列車          見出し値… : 時刻… : 脚注値…
--   }}
--
--  詳細は Module:Timetable/doc（FORMAT.md）。
--------------------------------------------------------------------------

-- 空白区切り。"…" は空白を含む生セル（"" で " 自体）
local function tokenize(line)
  local t, i, len = {}, 1, #line
  while i <= len do
    local c = sub(line, i, i)
    if c == " " or c == "\t" then
      i = i + 1
    else
      -- 空白まで 1 トークン。途中の "…" は空白を含められる（"" で " 自体）。
      -- 引用の外の , で区切った部分（着発の「着,発」）も parts に記録する
      local buf, parts = {}, {}
      local part, pq, pplain = {}, false, false
      local function endpart()
        parts[#parts + 1] = { v = concat(part), q = pq and not pplain }
        part, pq, pplain = {}, false, false
      end
      while i <= len do
        local d = sub(line, i, i)
        if d == " " or d == "\t" then break
        elseif d == '"' then
          pq = true
          local j = i + 1
          while j <= len do
            local e = sub(line, j, j)
            if e == '"' then
              if sub(line, j + 1, j + 1) == '"' then buf[#buf + 1] = '"'; part[#part + 1] = '"'; j = j + 2 else break end
            else
              buf[#buf + 1] = e; part[#part + 1] = e; j = j + 1
            end
          end
          i = j + 1
        else
          if d == "," then endpart() else part[#part + 1] = d; pplain = true end
          buf[#buf + 1] = d; i = i + 1
        end
      end
      endpart()
      local tok = { v = concat(buf), q = (#parts == 1 and parts[1].q) or false }
      if #parts > 1 then tok.parts = parts end
      t[#t + 1] = tok
    end
  end
  return t
end

local function trim(s) return match(s, "^%s*(.-)%s*$") end

-- 時刻: 分（0〜1439）→ 表示文字列（0 時台は「015」のように 0 を付ける）
local function fmt_time(mins)
  mins = mins % 1440
  local h, mm = floor(mins / 60), mins % 60
  if h == 0 then return format("0%02d", mm) end
  return format("%d%02d", h, mm)
end

local KIND = {
  ["発"] = "DEP", ["發"] = "DEP", dep = "DEP",
  ["着"] = "ARR", arr = "ARR",
  ["〃"] = "q", q = "q",
}
-- 着発の 2 段組。値は 着行・発行の着発欄に出すトークン（韓国語の 착발 は 착／발 のまま）
-- 番線の段を足した形（着・番線・発 / 着・番線 / 番線・発）。段の数は 2 が基本で、「着,番,発」のように
-- カンマで並べれば何段でも組める
local PAIRKIND = { ["着発"] = { "ARR", "DEP" }, ["着發"] = { "ARR", "DEP" }, arrdep = { "ARR", "DEP" },
                   ["착발"] = { "착", "발" },
                   ["着番発"] = { "ARR", "番", "DEP" }, ["着番發"] = { "ARR", "番", "DEP" }, ["착번발"] = { "착", "번", "발" },
                   ["着番"] = { "ARR", "番" }, ["착번"] = { "착", "번" },
                   ["番発"] = { "番", "DEP" }, ["番發"] = { "番", "DEP" }, ["번발"] = { "번", "발" } }
-- 着・発の意味（上り表示での入れ替え・駅時刻表の着駅判定に使う）。韓国語の 발／착 は字のまま出す
local SEM = { ["発"] = "DEP", ["發"] = "DEP", dep = "DEP", ["발"] = "DEP",
              ["着"] = "ARR", arr = "ARR", ["착"] = "ARR" }
local FLIP = { ["발"] = "착", ["착"] = "발", ARR = "DEP", DEP = "ARR" }
-- 段の種類: 着 → "arr"、発（〃 も）→ "dep"、それ以外（番・番線・번선・空欄…）は番線の段 "trk"
local function partsem(v)
  if v == "ARR" or SEM[v] == "ARR" then return "arr" end
  if v == "DEP" or SEM[v] == "DEP" or v == "〃" or v == "q" then return "dep" end
  return "trk"
end

local DEFAULT_COLS = { "km", "mk", "st", "ad" }

local SPECIAL = { cls = true, style = true, tstyle = true }   -- tstyle: 列車の時刻欄（駅の行）だけの体裁

local function cells_of(tk)        -- 自由行のトークン → セル文字列
  local row = {}
  for k, t in ipairs(tk) do
    if not t.q and t.v == "_" then row[k] = ""
    elseif not t.q and t.v == "!" then row[k] = "!!;"
    else row[k] = t.v end
  end
  return row
end

local function parse_model(text)
  local m = { set = {}, setorder = {}, cols = DEFAULT_COLS, rcols = {}, rows = {}, foot = {}, st = {},
              tr = { down = {}, up = {} }, styles = {}, pre = {}, post = {}, notes = {}, grid = {},
              top = {}, raw = { styles = {}, pre = {}, post = {}, notes = {}, grid = {}, top = {} } }
  local sec, cur, pending_line, last, pending_tline
  -- 字下げして「:」で始まる行は前の行の続き（長い列車行を 見出し値 / 時刻 に分けて書ける）
  text = gsub(text, "\r?\n[ \t]+(:[^\n]*)", " %1")
  for raw in gmatch(text .. "\n", "([^\n]*)\n") do
    local l = trim(gsub(raw, "\r", ""))
    if l == "" or sub(l, 1, 1) == "#" then
      -- 空行・コメント
    elseif match(l, "^%[%s*%a+%s*%a*%s*%]$") then
      local name, arg = match(l, "^%[%s*(%a+)%s*(%a*)%s*%]")
      sec = name
      if name == "trains" then cur = m.tr[(arg == "up") and "up" or "down"]; last = nil end
    elseif not sec then                                   -- 設定
      local tk = tokenize(l)
      local vals = {}
      for k = 2, #tk do vals[#vals + 1] = tk[k].v end
      if m.set[tk[1].v] == nil then m.setorder[#m.setorder + 1] = tk[1].v end
      m.set[tk[1].v] = concat(vals, " ")
      if tk[1].v == "cols" then m.cols = vals end
      if tk[1].v == "rcols" then m.rcols = vals end
    elseif sec == "rows" or sec == "footer" then          -- 見出し・脚注の定義
      local tk = tokenize(l)
      local d = { key = tk[1].v }
      local k = 2
      if tk[2] and not tk[2].q and tk[2].v == "@raw" then
        d.raw = {}; k = 3
        while tk[k] and (tk[k].q or not (match(tk[k].v, "^fmt=") or match(tk[k].v, "^style=") or tk[k].v == "merge")) do
          d.raw[#d.raw + 1] = tk[k].v; k = k + 1
        end
      elseif tk[2] and not tk[2].q and tk[2].v == "^" then
        -- ラベル「^」: 左右の見出し名を上の行とつなげる（列車名を 種別・愛称・設備 の行に分けるとき）
        d.join = true; k = 3
      else
        d.label = tk[2] and tk[2].v or ""; k = 3
      end
      for q = k, #tk do
        if not tk[q].q then
          local f = match(tk[q].v, "^fmt=(.*)$")
          if f then d.fmt = f end
          local st = match(tk[q].v, "^style=(.*)$")
          if st then d.style = st end
          if tk[q].v == "merge" then d.merge = true end
          local rl = match(tk[q].v, "^r=(.*)$")       -- 右側駅欄に出す見出し名（別の言語・表記）
          if rl then d.rlabel = rl end
        end
      end
      local list = (sec == "rows") and m.rows or m.foot
      list[#list + 1] = d
    elseif sec == "stations" then
      if match(l, "^%-%-%-+$") then
        pending_line = true
      elseif sub(l, 1, 1) == "+" then
        -- 自由行:  + "左" : "本文"   ／  + "全幅の本文"   （style=… 可）
        local tk = tokenize(trim(sub(l, 2)))
        local s = { free = true, f = {}, line = pending_line }
        pending_line = false
        local parts, pi = { {}, {} }, 1
        for _, t in ipairs(tk) do
          local st = (not t.q) and match(t.v, "^style=(.*)$")
          if st then s.style = st
          elseif not t.q and t.v == ":" then pi = 2
          else parts[pi][#parts[pi] + 1] = t.v end
        end
        if pi == 2 then s.left, s.body = concat(parts[1], " "), concat(parts[2], " ")
        else s.body = concat(parts[1], " ") end
        m.st[#m.st + 1] = s
      else
        local tk = tokenize(l)
        local s = { f = {}, line = pending_line }
        pending_line = false
        local pos = {}
        for _, t in ipairs(tk) do
          local key, val, rrole, frole = nil, nil, nil, nil
          if not t.q then
            -- 欄ごとの体裁:  st.style="fw=b fs=lg"  r.ad.style=bl=0（右側だけ）  ad.dep.style=bt=0（発行だけ）
            frole, val = match(t.v, "^([%a%.]+)%.style=(.*)$")
            if not frole then rrole, val = match(t.v, "^r%.(%a+)=(.*)$") end
            if not frole and not rrole then val = match(t.v, "^r=(.*)$"); if val then rrole = "st" end end
            if not frole and not rrole then key, val = match(t.v, "^(%a+)=(.*)$") end
          end
          if frole then
            s.fs = s.fs or {}; s.fs[frole] = val
          elseif rrole then
            -- 右側の駅欄だけ別の値（仮名書きの駅名など）:  r=しゅんせん  r.km=81.3
            s.r = s.r or {}; s.r[rrole] = { v = val }
          elseif key and SPECIAL[key] then s[key] = val else pos[#pos + 1] = t end
        end
        for k, role in ipairs(m.cols) do s.f[role] = pos[k] or { v = "_" } end
        local extra = #m.cols   -- 右側にだけある役割の値は、cols の後ろに順に並ぶ
        for _, role in ipairs(m.rcols) do
          if not s.f[role] then extra = extra + 1; s.f[role] = pos[extra] or { v = "_" } end
        end
        local ad = s.f.ad
        if ad and not ad.q then
          if PAIRKIND[ad.v] then s.pair = true; s.pk = PAIRKIND[ad.v]
          elseif ad.parts and #ad.parts >= 2 then
            -- 「着,発」「着,〃」のように並べれば、その文字で段を組む（「着,番,発」なら 3 段）
            s.pair = true; s.pk = {}
            for k, x in ipairs(ad.parts) do s.pk[k] = (x.v == "_") and "" or x.v end
          end
        end
        m.st[#m.st + 1] = s
      end
    elseif sec == "styles" then
      m.styles[#m.styles + 1] = tokenize(l)
      m.raw.styles[#m.raw.styles + 1] = l
    elseif sec == "pre" or sec == "post" or sec == "grid" then
      local list = m[sec]
      list[#list + 1] = cells_of(tokenize(l))
      m.raw[sec][#m.raw[sec] + 1] = l
    elseif sec == "top" then
      -- 枠の外の上段: 1 行 = 1 段。項目は "属性; 内容"（al=l|c|r で左・中・右、fs= で大きさ）
      m.top[#m.top + 1] = cells_of(tokenize(l))
      m.raw.top[#m.raw.top + 1] = l
    elseif sec == "notes" then
      m.notes[#m.notes + 1] = l
      m.raw.notes[#m.raw.notes + 1] = l
    elseif sec == "trains" and cur and match(l, "^%-%-%-+%s*%S*%s*$") then
      -- --- : 次の列車の左に縦罫（既定は太線。--- d や --- 3 で種類を指定）
      local v = match(l, "^%-%-%-+%s*(%S*)")
      pending_tline = (v ~= "" and v) or "2"
    elseif sec == "trains" and cur then
      local rep = { match(l, "^@repeat%s+(%d+)%s+%+?(%-?%d+)%s*%+?(%-?%d*)") }
      if rep[1] and last then
        local n, dm, dk = tonumber(rep[1]), tonumber(rep[2]), tonumber(rep[3]) or 2
        for k = 1, n do
          local c = { attr = {}, foot = last.foot, times = last.times,
                      off = (last.off or 0) + dm * k }
          for key, v in pairs(last.attr) do
            local pre, num, post = match(v, "^(.-)(%d+)(%D*)$")
            if pre and key == "no" then
              c.attr[key] = pre .. tostring(tonumber(num) + dk * k) .. post
            else
              c.attr[key] = v
            end
          end
          cur[#cur + 1] = c
        end
      else
        local tk = tokenize(l)
        local parts, pi = { {}, {}, {} }, 1
        for _, t in ipairs(tk) do
          if not t.q and t.v == ":" then pi = pi + 1
          elseif parts[pi] then parts[pi][#parts[pi] + 1] = t end
        end
        local tr = { attr = {}, foot = {}, times = {} }
        local A, T, Fo
        if pi == 1 then A, T, Fo = {}, parts[1], {} else A, T, Fo = parts[1], parts[2], parts[3] end
        local prev = cur[#cur]
        local function assign(list, defs, into, prevmap)
          local pos = 1
          for _, t in ipairs(list) do
            local key, val = nil, nil
            if not t.q then key, val = match(t.v, "^([%w_]+)=(.*)$") end
            local isnamed = key and SPECIAL[key] or false
            if key and not isnamed then
              for _, d in ipairs(defs) do if d.key == key then isnamed = true end end
            end
            if not isnamed then
              key, val = defs[pos] and defs[pos].key, t.v
              pos = pos + 1
            end
            if key then
              if not t.q and val == "_" then val = ""
              elseif not t.q and val == "%" then val = prevmap and prevmap[key] or "" end
              into[key] = val
            end
          end
        end
        assign(A, m.rows, tr.attr, prev and prev.attr)
        assign(Fo, m.foot, tr.foot, prev and prev.foot)
        for _, t in ipairs(T) do
          local base, n = nil, nil
          if not t.q then base, n = match(t.v, "^(.+)%*(%d+)$") end
          if base then
            for _ = 1, tonumber(n) do tr.times[#tr.times + 1] = { v = base } end
          else
            tr.times[#tr.times + 1] = t
          end
        end
        tr.line = pending_tline; pending_tline = nil
        cur[#cur + 1] = tr
        last = tr
      end
    end
  end
  return m
end

-- 列車の時刻トークンを、駅（表示行）ごとのセル文字列に解決する
--   着発駅は { a = 着, d = 発 }、それ以外は { v = … }
local function resolve(train, stations)
  local off, lastm = train.off or 0, nil
  local function dec(t)
    if not t then return "" end
    if t.q then return t.v end
    local v = t.v
    if v == "_" then return "" end
    if v == "!" then return "!!;" end
    -- 「属性;時刻」— 属性を残したまま時刻を解釈する
    local attr, body = match(v, "^([^;]*;)%s*(.*)$")
    if attr then v = body else attr = "" end
    if match(v, "^%d%d$") and lastm then              -- 分だけ（時は直前から）
      local h, mm = floor(lastm / 60), tonumber(v)
      if mm < lastm % 60 then h = h + 1 end
      lastm = (h * 60 + mm) % 1440
      return attr .. fmt_time(lastm + off)
    elseif match(v, "^%d%d%d%d?$") then              -- 完全な時刻
      local n = tonumber(v)
      lastm = floor(n / 100) * 60 + n % 100
      if off == 0 then return attr .. v end
      return attr .. fmt_time(lastm + off)
    end
    return attr .. v
  end
  local out, ti = {}, 1
  for i, s in ipairs(stations) do
    if s.free then
      out[i] = {}
    else
      local t = train.times[ti]; ti = ti + 1
      if s.pair then
        -- 段ごとの値。段の数だけ書けばその順、少なければ着・発の段（番線の段を除く）に順に当てる。
        -- 1 つだけなら着・発の段すべてに同じ値（2 段の着発駅で 1 つ書いたときと同じ）
        local pk = s.pk or PAIRKIND["着発"]
        local N, pa, p = #pk, t and t.parts, {}
        for k = 1, N do p[k] = "" end
        local tix = {}
        for k = 1, N do if partsem(pk[k]) ~= "trk" then tix[#tix + 1] = k end end
        if #tix == 0 then for k = 1, N do tix[k] = k end end
        -- 番線の段の値は時刻として読まない（「12」を 12 分と取らない・直前の時刻も更新しない）
        local function decp(k, x)
          if partsem(pk[k]) ~= "trk" or not x then return dec(x) end
          if x.q then return x.v end
          if x.v == "_" then return "" elseif x.v == "!" then return "!!;" end
          return x.v
        end
        if pa and #pa >= N then
          for k = 1, N do p[k] = decp(k, pa[k]) end
        elseif pa and #pa >= 2 then
          for q, x in ipairs(pa) do if tix[q] then p[tix[q]] = decp(tix[q], x) end end
        else
          local r = dec(t)
          for _, k in ipairs(tix) do p[k] = r end
        end
        local ia, id = tix[1], tix[#tix]
        for k = 1, N do if partsem(pk[k]) == "arr" then ia = k; break end end
        for k = N, 1, -1 do if partsem(pk[k]) == "dep" then id = k; break end end
        out[i] = { p = p, a = p[ia], d = p[id] }
      else
        out[i] = { v = dec(t) }
      end
    end
  end
  return out
end

-- 着発駅の欄を 着行・発行で別の値にするとき（連絡船の乗り継ぎで「739.2,0.0」など）の 2 値。分けないなら nil
local function split2(t)
  if not t or t.q then return nil end
  if t.parts and #t.parts == 2 then return t.parts[1], t.parts[2] end
  local a, b = match(t.v or "", "^([^,]*),([^,]*)$")
  if a then return { v = a }, { v = b } end
  return nil
end
-- 段が N 個の駅で、欄の値を段ごとに N 個書いたとき（「739.2,_,0.0」）の値の並び。そうでなければ nil
local function splitN(t, N)
  if not t or t.q then return nil end
  if t.parts then
    if #t.parts ~= N then return nil end
    local o = {}
    for k, x in ipairs(t.parts) do o[k] = x end
    return o
  end
  local o = {}
  for x in gmatch((t.v or "") .. ",", "([^,]*),") do o[#o + 1] = { v = x } end
  if #o == N and N >= 2 then return o end
  return nil
end

local function flip_ad(v)
  if FLIP[v] then return FLIP[v] end
  if SEM[v] == "DEP" then return "着" elseif SEM[v] == "ARR" then return "発" end
  return v
end

-- 上り: 駅順を逆に、着↔発を入れ替え、キロ程を終点からに
local function reverse_stations(st)
  local maxkm = 0
  for _, s in ipairs(st) do
    local k = s.f.km
    if k and not k.q then
      for x in gmatch(k.v, "[^,]+") do
        if match(x, "^%d+%.?%d*$") then local n = tonumber(x); if n > maxkm then maxkm = n end end
      end
    end
  end
  local function flipkm(v)
    if match(v, "^%d+%.?%d*$") then return format("%.1f", maxkm - tonumber(v)) end
    return v
  end
  local r = {}
  for i = #st, 1, -1 do
    local s = st[i]
    local c = {}
    for k, v in pairs(s) do c[k] = v end
    c.f, c.line = {}, st[i + 1] and st[i + 1].line or false
    for k, v in pairs(s.f) do c.f[k] = v end
    local ad = s.f.ad
    if ad and not ad.q then
      if FLIP[ad.v] then c.f.ad = { v = FLIP[ad.v] }
      elseif SEM[ad.v] == "DEP" then c.f.ad = { v = "着" }
      elseif SEM[ad.v] == "ARR" then c.f.ad = { v = "発" } end
    end
    local k = s.f.km
    if k and not k.q and match(k.v, "^%d+%.?%d*$") then
      c.f.km = { v = format("%.1f", maxkm - tonumber(k.v)) }
    end
    if s.pair then
      -- 段ごとに分けた欄は、上りでは上下が逆になる。段の名前も逆順にして着↔発を入れ替える
      local pk = s.pk or PAIRKIND["着発"]
      local N = #pk
      for role, t in pairs(s.f) do
        local xs = splitN(t, N)
        if xs and role ~= "ad" and role ~= "st" then
          local vs, ps = {}, {}
          for k = N, 1, -1 do
            local x = xs[k].v
            if role == "km" then x = flipkm(x) end
            vs[#vs + 1] = x; ps[#ps + 1] = { v = x }
          end
          c.f[role] = { v = concat(vs, ","), parts = ps }
        end
      end
      c.pk = {}
      for k = N, 1, -1 do c.pk[#c.pk + 1] = flip_ad(pk[k]) end
    end
    r[#r + 1] = c
  end
  return r
end

-- セル文字列に属性を足す（"^2" や "&"）
local function addattr(cell, a)
  if a == nil or a == "" then return cell end
  if find(cell, ";", 1, true) then return a .. " " .. cell end
  return a .. "; " .. cell
end

local function fmtv(fmt, v)
  if v == nil or v == "" then return "" end
  if not fmt then return v end
  -- 値にセル属性が付いていれば（"fw=b; 88"）、属性は外に出して中身だけを包む → "fw=b; N{88}"
  local at, body = match(v, "^([^;]*);%s*(.*)$")
  if at then
    if body == "" then return v end
    return at .. "; " .. gsub(fmt, "%*", (gsub(body, "%%", "%%%%")))
  end
  return (gsub(fmt, "%*", (gsub(v, "%%", "%%%%"))))
end

-- 駅欄の各フィールド → セル文字列
local function station_cell(role, t)
  if not t then return "" end
  if t.q then return t.v end
  local v = t.v
  if v == "_" then return "" end
  if role == "km" then
    if match(v, "^%d+%.%d+$") then return (gsub(v, "%.", "..")) end
    return v
  elseif role == "st" then
    local b2 = match(v, "^%*%*(.+)$")
    if b2 then return "b'" .. b2 .. "'." end
    local b1 = match(v, "^%*(.+)$")
    if b1 then return "k'" .. b1 .. "'." end
    return "'" .. v .. "'"
  elseif role == "ad" then
    return KIND[v] or v
  elseif role == "alt" or not BUILTIN_ROLE[role] then
    -- 併記欄（ローマ字など）と利用者が足した欄（運賃など）は素の文字列として出す
    return find(v, "`", 1, true) and v or ("`" .. v .. "`")
  end
  return v
end

-- 駅欄のセル ＋ その駅・その欄の体裁（st.style= など）
-- 欄ごとの体裁を重ねる（後が勝つ）。role.style → role.arr/dep.style（着発駅の着行・発行だけ）
-- → 右側の欄なら r.role.style → r.role.arr/dep.style
local function fsattr(s, role, right, part)
  local fs = s.fs
  if not fs then return nil end
  local o = {}
  local function add(k) if fs[k] then o[#o + 1] = fs[k] end end
  add(role); if part then add(role .. "." .. part) end
  if right then add("r." .. role); if part then add("r." .. role .. "." .. part) end end
  return #o > 0 and concat(o, " ") or nil
end
local function fcell(s, role, t, right, part)
  return addattr(station_cell(role, t), fsattr(s, role, right, part))
end


-- 見出し行の左側（既定の形）
-- @raw の 1 セル: ! は結合に覆われたセル、_ は空欄（列車の時刻と同じ書き方も受け付ける）
local function rawcell(v)
  if v == nil or v == "!" or v == "!!" then return "!!;" end
  if v == "_" then return "" end
  return v
end

local function header_left(k, nH, label, cols, labels, ja)
  -- labels: 役割 → 見出し（km は kmlabel）。見出しのある欄は全見出し行を縦に通す 1 セル、
  -- 残りの欄のうち左端のひとつながりに行の名前を置く
  if type(labels) ~= "table" then labels = { km = labels } end
  local L, row = #cols, {}
  ja = ja and (" " .. ja) or ""
  local sep = {}
  for q, r in ipairs(cols) do
    if (q == 1 and r == "km" and L >= 2) or (labels[r] ~= nil and labels[r] ~= "" and r ~= "st" and r ~= "ad") then sep[q] = labels[r] or "" end
  end
  local li, q = nil, 1
  while q <= L do
    if sep[q] then
      row[q] = (k == 1) and ("^" .. nH .. "; " .. (sep[q] ~= "" and ("j'" .. sep[q] .. "'") or "")) or "!!;"
      q = q + 1
    else
      local q2 = q
      while q2 + 1 <= L and not sep[q2 + 1] do q2 = q2 + 1 end
      if not li then
        li = q
        if labels._corner then
          -- corner 設定: 行の名前の代わりに、全見出し行を通す 1 セル（斜線見出し DG{…} など）
          row[q] = (k == 1) and ("^" .. nH .. " <" .. (q2 - q + 1) .. "; " .. labels._corner) or "!!;"
        else
          row[q] = "h<" .. (q2 - q + 1) .. ja .. "; '" .. (label or "") .. "'"
        end
      else row[q] = "<" .. (q2 - q + 1) .. ";" end
      for x = q + 1, q2 do row[x] = "!!;" end
      q = q2 + 1
    end
  end
  return row, li or 1
end

local function footer_left(label, cols, ja)
  local L, row = #cols, { "h<" .. #cols .. (ja and (" " .. ja) or "") .. "; '" .. label .. "'" }
  for q = 2, L do row[q] = "!!;" end
  return row
end

-- 右側の駅欄の見出し: 左と同じ見出し行の名前を鏡写しに置く（キロ欄は外側で縦に通す）
local function header_right(k, nH, label, rc, kmlabel, ja)
  local R, row = #rc, {}
  ja = ja and (" " .. ja) or ""
  local lab = label and ("'" .. label .. "'") or ""
  local kmq = (R >= 2 and rc[R] == "km" and R) or (R >= 2 and rc[1] == "km" and 1) or nil
  if not kmq then
    row[1] = "h<" .. R .. ja .. "; " .. lab
    for q = 2, R do row[q] = "!!;" end
    return row
  end
  local kc = (k == 1) and ("^" .. nH .. "; " .. (kmlabel and kmlabel ~= "" and ("j'" .. kmlabel .. "'") or "")) or "!!;"
  if kmq == 1 then
    row[1] = kc; row[2] = "h<" .. (R - 1) .. ja .. "; " .. lab
    for q = 3, R do row[q] = "!!;" end
  else
    row[1] = "h<" .. (R - 1) .. ja .. "; " .. lab
    for q = 2, R - 1 do row[q] = "!!;" end
    row[R] = kc
  end
  return row
end

-- 表示ビュー共通: 方向に応じた駅と列車
local function select_dir(m, dir)
  if dir == "up" then return reverse_stations(m.st), m.tr.up end
  return m.st, m.tr.down
end

-- JTB 式（縦組み）: モデル → 旧形式と同じセル配列
-- 見出し・脚注の値（merge 指定なら同じ値の連続を横に結合）
local function value_cells(d, trains, getter)
  local vals = {}
  for t = 1, #trains do vals[t] = fmtv(d.fmt, getter(trains[t])[d.key]) end
  if not d.merge then return vals end
  local out, t = {}, 1
  while t <= #vals do
    local j = t
    while j < #vals and vals[j + 1] == vals[t] and vals[t] ~= "" do j = j + 1 end
    out[t] = (j > t) and addattr(vals[t], "cs=" .. (j - t + 1)) or vals[t]
    for q = t + 1, j do out[q] = "!!;" end
    t = j + 1
  end
  return out
end

local function skips(n) local r = {}; for q = 1, n do r[q] = "!!;" end; return r end
local function append(dst, src) for _, v in ipairs(src) do dst[#dst + 1] = v end; return dst end

-- JTB 式（縦組み）: モデル → セル配列＋行・列の素性（スタイル適用に使う）
local JA, RJA
local function build_grid(m, dir)
  local meta_head
  local cols, L = m.cols, #m.cols
  local rcols, R = m.rcols, #m.rcols
  local stations, trains = select_dir(m, dir)
  -- 上下併記（both）: 駅欄を真ん中に、左に下り（上から読む）、右に上り（下から読む）
  local both = m.set.both and m.set.both ~= "" and m.set.both ~= "0"
  local utr, ures, ust, stq = {}, {}, nil, nil
  if both then
    stations, trains = m.st, m.tr.down
    utr, ust = m.tr.up, reverse_stations(m.st)
    for t = 1, #utr do ures[t] = resolve(utr[t], ust) end
    rcols, R = {}, 0
    for q, role in ipairs(cols) do if role == "st" then stq = q end end
  end
  -- 上下併記の右の着発欄（駅名より右の ad）は段の名前を逆に（上りは下から読む）
  local function radv(q) return both and stq and q > stq end
  local nt = #trains
  local W = L + nt + R
  local res = {}
  for t = 1, nt do res[t] = resolve(trains[t], stations) end

  -- 見出しの項目名（列車番号・列車名・行先…）は、いちばん長い名前の字間に合わせて両端をそろえる
  local function jattr(names)
    local nmax = 0
    for _, s in ipairs(names) do if s then local n = ulen(s); if n > nmax then nmax = n end end end
    if nmax < 2 then return nil end
    return "cls=jtt-jn css=--jtt-jn:" .. nmax
  end
  local ln, rn = {}, {}
  for _, list in ipairs({ m.rows, m.foot }) do
    for _, d in ipairs(list) do
      if not d.raw then ln[#ln + 1] = d.label end
      rn[#rn + 1] = d.rlabel or (not d.raw and d.label) or nil
    end
  end
  JA, RJA = jattr(ln), jattr(rn)

  -- timesep: 時と分の間に点などを入れる（6.45 のような表記）。3〜4 桁の時刻だけが対象
  local tsep = m.set.timesep
  if tsep and tsep ~= "" then
    -- 区切りは幅を決めた箱に入れて時と分の真ん中に置く（\1…\2 を render が箱にする）
    local tok = "\1" .. tsep .. "\2"
    local function addsep(x)
      if type(x) ~= "string" then return x end
      local pre, body = match(x, "^(.*;%s*)(.-)$")
      if not pre then pre, body = "", x end
      return pre .. gsub(body, "%f[%d](%d?%d)(%d%d)%f[%D]", "%1" .. gsub(tok, "%%", "%%%%") .. "%2")
    end
    for t = 1, nt do
      for _, x in pairs(res[t]) do
        if type(x) == "table" then
          x.v, x.a, x.d = addsep(x.v), addsep(x.a), addsep(x.d)
          if x.p then for k = 1, #x.p do x.p[k] = addsep(x.p[k]) end end
        end
      end
    end
  end

  local rows, rinfo = {}, {}
  local function push(row, info) rows[#rows + 1] = row; rinfo[#rows] = info end
  local UP = {}          -- 上下併記: 行ごとの上り列車の欄
  local nS = #stations

  local nhead = 0
  local hs = m.set
  local custom = (hs.headl and hs.headl ~= "") or (hs.headr and hs.headr ~= "") or (hs.headstyle and hs.headstyle ~= "")
  if custom then
    -- 見出し帯を左・中・右の 3 区画で組む（headl / head / headr、体裁は headstyle）
    meta_head = { l = hs.headl, c = hs.head, r = hs.headr, style = hs.headstyle, ht = hs.headheight }
  elseif m.set.head and m.set.head ~= "" then
    local hh = m.set.headheight
    push({ "h" .. ((hh and hh ~= "") and ("~" .. hh) or "") .. "; " .. m.set.head }, { kind = "head" })
    nhead = 1
  end
  for k, row in ipairs(m.pre) do push(row, { kind = "pre", k = k }) end
  local nH = #m.rows
  -- 見出し名をつなげる行（label ^）の数を数えておく
  local span = {}
  for k, d in ipairs(m.rows) do
    if not d.join then
      local n, q = 1, k + 1
      while m.rows[q] and m.rows[q].join do n = n + 1; q = q + 1 end
      span[k] = n
    end
  end
  -- 欄の見出し（kmlabel・label.役割）
  local labels = { km = m.set.kmlabel or m.set["label.km"], _corner = (m.set.corner ~= "" and m.set.corner) or nil }
  for _, r in ipairs(cols) do if r ~= "km" and m.set["label." .. r] then labels[r] = m.set["label." .. r] end end
  for k, d in ipairs(m.rows) do
    local row
    if d.join then
      row = skips(L)
    else
      local li
      if d.raw then row = {}; for q = 1, L do row[q] = rawcell(d.raw[q]) end
      else row, li = header_left(k, nH, d.label, cols, labels, JA) end
      if span[k] > 1 and not d.raw and L > 0 and not labels._corner then
        row[li] = addattr(row[li], "^" .. span[k])
      end
    end
    local vals = value_cells(d, trains, function(tr) return tr.attr end)
    if d.join and vals[1] then vals[1] = addattr(vals[1], "#") end   -- つなげた行の間は既定で罫なし（style=bt=1 で引ける）
    append(row, vals)
    if R > 0 then
      if m.set.rlabel and m.set.rlabel ~= "" then
        -- rlabel 指定: 右側見出しを 1 つのセルにまとめる
        if k == 1 then
          append(row, { "^" .. nH .. " <" .. R .. "; " .. m.set.rlabel }); append(row, skips(R - 1))
        else append(row, skips(R)) end
      else
        if d.join then
          append(row, skips(R))
        else
          local rr = header_right(k, nH, d.rlabel or (not d.raw and d.label) or nil, rcols, m.set.kmlabel, RJA)
          if span[k] > 1 then
            local li = (R >= 2 and rcols[1] == "km") and 2 or 1
            rr[li] = addattr(rr[li], "^" .. span[k])
          end
          append(row, rr)
        end
      end
    end
    push(row, { kind = "hdr", key = d.key, style = d.style })
    if both then
      local uv = value_cells(d, utr, function(tr) return tr.attr end)
      if d.join and uv[1] then uv[1] = addattr(uv[1], "#") end
      UP[#rows] = uv
    end
  end
  for i, s in ipairs(stations) do
    local info = { kind = "body", si = i, st = s }
    if s.free then
      local row
      if s.left then
        row = { "<" .. L .. "; " .. s.left }; append(row, skips(L - 1))
        append(row, { "<" .. (nt + R) .. " wrap al=l; " .. (s.body or "") }); append(row, skips(nt + R - 1))
      else
        row = { "<" .. W .. " wrap al=l; " .. (s.body or "") }; append(row, skips(W - 1))
      end
      if s.line then row[1] = addattr(row[1], "&") end
      info.free = true
      push(row, info)
    elseif s.pair then
      -- 着発駅: 段（着・発、番線を足せば 着・番線・発 など）ごとに 1 行
      local pk = s.pk or PAIRKIND["着発"]
      local N = #pk
      local rr, sem = {}, {}
      for k = 1, N do rr[k] = {}; sem[k] = partsem(pk[k]) end
      -- 2 段のときの体裁キーは位置で arr / dep（「着,〃」のような駅も従来どおり）
      local function pname(k)
        if N == 2 and sem[k] ~= "trk" then return (k == 1) and "arr" or "dep" end
        return sem[k]
      end
      -- 欄の値を段の数だけ「,」で並べれば段ごとのセル、1 つなら全段を結合
      local function spread(role, t, right, into)
        local xs
        if role ~= "st" then xs = splitN(t, N) end      -- 駅名は分けない（常に全段を結合）
        if xs then
          for k = 1, N do into[k] = fcell(s, role, xs[k], right, pname(k)) end
        else
          into[1] = addattr(fcell(s, role, t, right), "^" .. N)
          for k = 2, N do into[k] = "!!;" end
        end
      end
      for q, role in ipairs(cols) do
        if role == "ad" then
          for k = 1, N do
            local kk = radv(q) and (N + 1 - k) or k
            local c = fcell(s, "ad", { v = pk[kk] }, false, pname(kk))   -- ad.style の属性が付いていても壊さない
            if k > 1 or s.line then c = addattr(c, "&") end
            rr[k][q] = c
          end
        else
          local tmp = {}
          spread(role, s.f[role], false, tmp)
          for k = 1, N do rr[k][q] = tmp[k] end
        end
      end
      for t = 1, nt do
        local x = res[t][i]
        for k = 1, N do rr[k][L + t] = x.p and x.p[k] or ((k == 1) and x.a or x.d) end
      end
      for q, role in ipairs(rcols) do
        if role == "ad" then
          -- 右側の着発欄も左と同じ段組み
          for k = 1, N do rr[k][L + nt + q] = fcell(s, "ad", { v = pk[k] }, true, pname(k)) end
        else
          local tmp = {}
          spread(role, s.r and s.r[role] or s.f[role], true, tmp)
          for k = 1, N do rr[k][L + nt + q] = tmp[k] end
        end
      end
      for k = 1, N do
        push(rr[k], { kind = "body", si = i, st = s, part = pname(k), pi = k })
        if both then
          local u, kk = {}, N + 1 - k            -- 上りは下の段が着、上の段が発
          for t = 1, #utr do local x = ures[t][nS + 1 - i]; u[t] = x.p and x.p[kk] or ((kk == 1) and x.a or x.d) end
          UP[#rows] = u
        end
      end
    else
      local r = {}
      for q, role in ipairs(cols) do
        local f = s.f[role]
        if role == "ad" and radv(q) and f and not f.q then
          local v = f.v
          if SEM[v] == "DEP" then f = { v = "着" } elseif SEM[v] == "ARR" then f = { v = "発" } elseif FLIP[v] then f = { v = FLIP[v] } end
        end
        r[q] = fcell(s, role, f)
      end
      if s.line and L > 0 then r[L] = addattr(r[L], "&") end
      for t = 1, nt do r[L + t] = res[t][i].v end
      for q, role in ipairs(rcols) do r[L + nt + q] = fcell(s, role, s.r and s.r[role] or s.f[role], true) end
      push(r, info)
      if both then
        local u = {}
        for t = 1, #utr do u[t] = ures[t][nS + 1 - i].v end
        UP[#rows] = u
      end
    end
  end
  for k, d in ipairs(m.foot) do
    local row = d.raw and {} or footer_left(d.label, cols, JA)
    if d.raw then for q = 1, L do row[q] = rawcell(d.raw[q]) end end
    append(row, value_cells(d, trains, function(tr) return tr.foot end))
    if R > 0 then
      local fl = d.rlabel or (not d.raw and d.label)
      append(row, { "h<" .. R .. (RJA and (" " .. RJA) or "") .. "; " .. (fl and ("'" .. fl .. "'") or "") })
      append(row, skips(R - 1))
    end
    push(row, { kind = "foot", key = d.key, style = d.style })
    if both then UP[#rows] = value_cells(d, utr, function(tr) return tr.foot end) end
  end
  for k, row in ipairs(m.post) do push(row, { kind = "post", k = k }) end

  local cinfo = {}
  if both then
    -- 列を 下り | 駅欄 | 上り に並べ替える
    for r = 1, #rows do
      if UP[r] then
        local row, new = rows[r], {}
        for j = L + 1, L + nt do new[#new + 1] = row[j] end
        for j = 1, L do new[#new + 1] = row[j] end
        append(new, UP[r])
        rows[r] = new
      end
    end
    for t = 1, nt do cinfo[t] = { kind = "train", ti = t, tr = trains[t] } end
    for q, role in ipairs(cols) do cinfo[nt + q] = { kind = "left", role = role } end
    for t = 1, #utr do cinfo[nt + L + t] = { kind = "train", ti = nt + t, tr = utr[t] } end
    return rows, nhead + #m.pre + nH, L, #m.foot + #m.post,
      { rows = rinfo, cols = cinfo, R = {}, T = nt + #utr, roles = cols, head = meta_head, mid = { a = nt, L = L, U = #utr } }
  end
  for q, role in ipairs(cols) do cinfo[q] = { kind = "left", role = role } end
  for t = 1, nt do
    cinfo[L + t] = { kind = "train", ti = t, tr = trains[t] }
  end
  for q, role in ipairs(rcols) do cinfo[L + nt + q] = { kind = "right", role = role } end

  return rows, nhead + #m.pre + nH, L, #m.foot + #m.post, { rows = rinfo, cols = cinfo, R = rcols, T = nt, roles = cols, head = meta_head }
end

-- セル文字列から時刻（分）を取り出す。時刻でなければ nil
local function cell_time(v)
  if not v or find(v, "/", 1, true) then return nil end
  v = gsub(v, "^[^;]*;%s*", "")
  local n = match(v, "^%D*(%d%d?%d%d)%D*$")
  if not n then return nil end
  n = tonumber(n)
  return floor(n / 100) * 60 + n % 100
end

local function first_char(s)
  if s == "" then return "" end
  local b = byte(s)
  return sub(s, 1, (b >= 0xF0 and 4) or (b >= 0xE0 and 3) or (b >= 0xC0 and 2) or 1)
end

-- DiaPro の私用領域グリフ（種別マーク等）か
local function isdia(ch)
  local b = byte(ch or "")
  return b == 0xEE or b == 0xEF        -- U+E000–U+FFFF の 3 バイト形の先頭
end

local function plain(html) return trim(gsub(gsub(html, "<[^>]*>", ""), "&nbsp;", " ")) end
-- 駅時刻表の種別マーク: DiaPro のマークはそのまま、文字なら頭文字を角囲み
local function typemark(typ)
  local fc = first_char(typ)
  if isdia(fc) then return '<span class="jtt-dmk">' .. fc .. "</span>" end
  return parse_cell("S{" .. fc .. "}").html
end
local function nospace(s) return (gsub(gsub(s, "　", ""), "%s", "")) end

local function station_name(s)
  local t = s.f.st
  if not t then return "" end
  return nospace(plain(parse_cell(station_cell("st", t)).html))
end

local function wrap(frame, title, inner)
  local out = {}
  if STYLES_PAGE then
    out[#out + 1] = frame:extensionTag("templatestyles", "", { src = STYLES_PAGE })
  end
  out[#out + 1] = '<div class="jtt-wrap"><div class="jtt-title">' .. render_title(title or "")
    .. '</div><div class="jtt-frame">' .. inner .. "</div></div>"
  return concat(out)
end

-- 駅時刻表（時 × 分）
local function view_board(frame, m, dir, args)
  local stations, trains = select_dir(m, dir)
  local want = nospace(args.station or m.set.station or "")
  local si
  for i, s in ipairs(stations) do
    if station_name(s) == want then si = i; break end
  end
  if not si then
    return '<span class="jtt-err">station "' .. want .. '" not found</span>'
  end
  local tkey, dkey = args.type or m.set.type or "name", args.dest or m.set.dest
  local ent, tcount, dcount = {}, {}, {}
  for _, tr in ipairs(trains) do
    local r = resolve(tr, stations)
    local cell = stations[si].pair and r[si].d or r[si].v
    local ad = stations[si].f.ad
    local isarr = ad and not ad.q and SEM[ad.v] == "ARR"
    local tm = (not isarr) and cell_time(cell)
    if tm then
      -- 行先: 指定キーがあればそれ、無ければ時刻のある最後の駅
      local dest
      if dkey then
        local raw = tr.foot[dkey] or tr.attr[dkey] or ""
        dest = nospace(plain(parse_cell((match(raw, "^([^/]*)") or raw)).html))
      end
      if not dest or dest == "" then
        for k = #stations, si + 1, -1 do
          local x = r[k]
          if cell_time(x.v or x.a) then dest = station_name(stations[k]); break end
        end
      end
      if dest and dest ~= "" then
        local typ = plain(parse_cell(fmtv(nil, tr.attr[tkey] or "")).html)
        ent[#ent + 1] = { t = tm, typ = typ, dest = dest }
        tcount[typ] = (tcount[typ] or 0) + 1
        dcount[dest] = (dcount[dest] or 0) + 1
      end
    end
  end
  local function most(c) local b, n = nil, -1; for k, v in pairs(c) do if v > n then b, n = k, v end end; return b end
  local mt, md = most(tcount), most(dcount)
  table.sort(ent, function(a, b) return ((a.t - 180) % 1440) < ((b.t - 180) % 1440) end)
  local hours, order = {}, {}
  for _, e in ipairs(ent) do
    local h = floor(e.t / 60)
    if not hours[h] then hours[h] = {}; order[#order + 1] = h end
    local mark = (e.typ ~= mt and e.typ ~= "") and typemark(e.typ) or ""
    local dsub = (e.dest ~= md) and ('<span class="jtt-bdst">' .. e.dest .. "</span>") or ""
    hours[h][#hours[h] + 1] = '<span class="jtt-bmin"><span class="jtt-bmk">' .. mark .. "</span>"
      .. format("%02d", e.t % 60) .. dsub .. "</span>"
  end
  local o = { '<div class="jtt-head"><span class="jtt-b">' .. station_name(stations[si])
    .. "</span>　" .. (md and (md .. "方面") or "") .. '</div><div class="jtt-scroll"><table class="jtt jtt-board">' }
  for _, h in ipairs(order) do
    o[#o + 1] = '<tr><td class="jtt-bh">' .. h .. '</td><td class="jtt-bm">'
      .. concat(hours[h]) .. "</td></tr>"
  end
  o[#o + 1] = "</table></div>"
  -- 凡例
  local leg = {}
  for k in pairs(tcount) do
    if k ~= mt and k ~= "" then
      local fc = first_char(k)
      leg[#leg + 1] = typemark(k) .. (isdia(fc) and "" or k)
    end
  end
  table.sort(leg)
  if #leg > 0 or md then
    o[#o + 1] = '<div class="jtt-legend">' .. (mt and (mt .. "（無印）") or "") .. "　" .. concat(leg, "　")
      .. (md and ("　行先表示の無いものは " .. md .. " 行") or "") .. "</div>"
  end
  return wrap(frame, args.title or m.set.title, concat(o))
end

-- 横組み一覧（列車が行・駅が列）
local function view_list(frame, m, dir, args)
  local stations, trains = select_dir(m, dir)
  local o = { '<div class="jtt-scroll"><table class="jtt jtt-list"><tr class="jtt-hr">' }
  for _, d in ipairs(m.rows) do
    o[#o + 1] = '<td class="jtt-th jtt-lh">' .. parse_cell("'" .. (d.label or d.key) .. "'").html .. "</td>"
  end
  for i, s in ipairs(stations) do
    if not s.free then
      o[#o + 1] = '<td class="jtt-th jtt-ls' .. (i == 1 and " jtt-t1" or "") .. '"><span class="jtt-v">'
        .. station_name(s) .. "</span></td>"
    end
  end
  o[#o + 1] = "</tr>"
  for _, tr in ipairs(trains) do
    local r = resolve(tr, stations)
    o[#o + 1] = "<tr>"
    for _, d in ipairs(m.rows) do
      o[#o + 1] = '<td class="jtt-lh">' .. parse_cell(fmtv(d.fmt, tr.attr[d.key])).html .. "</td>"
    end
    for i, s in ipairs(stations) do if not s.free then
      local v = s.pair and ((r[i].d ~= "" and r[i].d) or r[i].a) or r[i].v
      if find(v, "!!", 1, true) then v = "" end
      local c = parse_cell(v)
      o[#o + 1] = '<td class="jtt-t' .. (c.c and " jtt-c" or "") .. '">' .. (c.html_t or c.html or "") .. "</td>"
    end end
    o[#o + 1] = "</tr>"
  end
  o[#o + 1] = "</table></div>"
  return wrap(frame, args.title or m.set.title, concat(o))
end


--------------------------------------------------------------------------
-- スタイル規則（[styles] 節・駅/列車/行定義の style=）
--   row:選択子  col:選択子  cell:行/列   all     （選択子は , で複数）
--   行: 駅名  #N  #N-M（駅の番号）  .クラス  arr dep free hdr body foot pre post  @N（表の行番号）
--   列: 列車番号  #N  #N-M（列車の番号）  .クラス  left right trains km mk st ad  @N（表の列番号）
--------------------------------------------------------------------------
local function in_range(sel, n)
  if not n then return false end
  local a, b = match(sel, "^(%d+)%-(%d+)$")
  if a then return n >= tonumber(a) and n <= tonumber(b) end
  return tonumber(sel) == n
end

local function has_cls(list, c)
  if not list then return false end
  for x in gmatch(list, "[^,%s]+") do if x == c then return true end end
  return false
end

local function row_match(sel, info, r)
  if sel == "all" or sel == "*" then return info.kind ~= "head" end
  local p1 = sub(sel, 1, 1)
  if p1 == "@" then return in_range(sub(sel, 2), r) end
  if p1 == "#" then return info.kind == "body" and in_range(sub(sel, 2), info.si) end
  if p1 == "." then return info.st and has_cls(info.st.cls, sub(sel, 2)) end
  if sel == "arr" or sel == "dep" or sel == "trk" then return info.part == sel end   -- trk: 番線の段
  if sel == "free" then return info.free == true end
  if sel == "hdr" or sel == "body" or sel == "foot" or sel == "pre" or sel == "post" then return info.kind == sel end
  if info.kind == "body" and info.st and not info.free then
    if station_name(info.st) == nospace(sel) then return true end
  end
  return (info.kind == "hdr" or info.kind == "foot") and info.key == sel
end

local function col_match(sel, info, j)
  if sel == "all" or sel == "*" then return true end
  if not info then return false end
  local p1 = sub(sel, 1, 1)
  if p1 == "@" then return in_range(sub(sel, 2), j) end
  if p1 == "#" then return info.kind == "train" and in_range(sub(sel, 2), info.ti) end
  if p1 == "." then return info.kind == "train" and has_cls(info.tr.attr.cls, sub(sel, 2)) end
  if sel == "left" or sel == "right" then return info.kind == sel end
  if sel == "trains" then return info.kind == "train" end
  if sel == "km" or sel == "mk" or sel == "st" or sel == "ad" or sel == "alt" then return info.role == sel end
  if info.role and info.role == sel and (info.kind == "left" or info.kind == "right") then return true end
  return info.kind == "train" and info.tr.attr.no == sel
end

local function apply_styles(m, rows, meta)
  local rules = {}
  for _, tk in ipairs(m.styles) do
    local rs, cs, at = {}, {}, {}
    for _, t in ipairs(tk) do
      local kind, val = match(t.v, "^(%a+):(.+)$")
      if not t.q and kind == "row" then for x in gmatch(val, "[^,]+") do rs[#rs + 1] = x end
      elseif not t.q and kind == "col" then for x in gmatch(val, "[^,]+") do cs[#cs + 1] = x end
      elseif not t.q and kind == "cell" then
        local a, b = match(val, "^(.-)/(.+)$")
        rs[#rs + 1] = a; cs[#cs + 1] = b
      elseif not t.q and t.v == "all" then rs[#rs + 1] = "all"
      else at[#at + 1] = t.v end
    end
    rules[#rules + 1] = { rows = rs, cols = cs, attrs = concat(at, " ") }
  end
  -- 行・列・行定義に付けた style=
  for r, info in ipairs(meta.rows) do
    local st = (info.st and info.st.style) or info.style
    if st then rules[#rules + 1] = { rows = { "@" .. r }, cols = info.style and { "trains" } or {}, attrs = st } end
  end
  for j, info in ipairs(meta.cols) do
    if info.kind == "train" and info.tr.attr.tstyle then   -- 時刻欄だけ（列車番号などの見出しは除く）
      rules[#rules + 1] = { rows = { "body" }, cols = { "@" .. j }, attrs = info.tr.attr.tstyle }
    end
    if info.kind == "train" and info.tr.attr.style then
      rules[#rules + 1] = { rows = {}, cols = { "@" .. j }, attrs = info.tr.attr.style }
    end
  end
  if #rules == 0 then return end
  for r, row in ipairs(rows) do
    local info = meta.rows[r] or { kind = "raw" }
    if info.kind ~= "head" then
      for _, rule in ipairs(rules) do
        local rok = #rule.rows == 0
        for _, sel in ipairs(rule.rows) do if row_match(sel, info, r) then rok = true; break end end
        if rok then
          for j, v in ipairs(row) do
            local cok = #rule.cols == 0
            for _, sel in ipairs(rule.cols) do if col_match(sel, meta.cols[j], j) then cok = true; break end end
            if cok and not find(v, "!!", 1, true) then row[j] = addattr(v, rule.attrs) end
          end
        end
      end
    end
  end
end

local function notes_html(m)
  if #m.notes == 0 then return nil end
  local o = { '<div class="jtt-notes">' }
  for _, l in ipairs(m.notes) do o[#o + 1] = "<div>" .. parse_cell(l).html .. "</div>" end
  o[#o + 1] = "</div>"
  return concat(o)
end

p.views = {
  jtb = function(frame, m, dir, args)
    local rows, H, L, F, meta
    if #m.grid > 0 and #m.st == 0 then
      -- [grid] だけの自由表
      rows, H, L, F = m.grid, tonumber(m.set.header) or 0, tonumber(m.set.left) or 0, tonumber(m.set.footer) or 0
      meta = { rows = {}, cols = {} }
      for r = 1, #rows do meta.rows[r] = { kind = "raw" } end
      for j = 1, 512 do meta.cols[j] = { kind = (j <= L) and "left" or "raw" } end
    else
      rows, H, L, F, meta = build_grid(m, dir)
      -- colsep: 駅欄の列と列の間の縦罫。値は罫線の種類（1 2 3 d . -）
      --   colsep 1            … 左右とも、すべての列の間
      --   colsep st=1 r.alt=d … 列ごと（その列の左側の線。右側の駅欄は r. を付ける）
      local sep = m.set.colsep
      if sep and sep ~= "" then
        local all = (not find(sep, "=", 1, true)) and match(sep, "^%s*(%S+)") or nil
        local per = {}
        for k, v in gmatch(sep, "([%w%.]+)=(%S+)") do per[k] = v end
        local rfirst = L + (meta.T or 0) + 1
        local function want(j)
          local ci = meta.cols[j]
          if not ci or not ci.role then return nil end
          if ci.kind == "left" then return per[ci.role] or (j > 1 and all) or nil end
          if ci.kind == "right" then return per["r." .. ci.role] or (j > rfirst and all) or nil end
        end
        for r = 1, #rows do
          local ri = meta.rows[r]
          if ri and (ri.kind == "hdr" or ri.kind == "body" or ri.kind == "foot") then
            local row = rows[r]
            for j = 1, #row do
              local v = want(j)
              if v and v ~= "0" and row[j] and not find(row[j], "!!", 1, true) then
                row[j] = addattr(row[j], "bl=" .. v)
              end
            end
          end
        end
      end
    end
    -- 列車の左の縦罫（[trains] の --- 行）
    if meta.T and not meta.mid then
      for t = 1, meta.T do
        local ci = meta.cols[L + t]
        local lv = ci and ci.tr and ci.tr.line
        if lv and lv ~= "0" then
          for r = 1, #rows do
            local ri = meta.rows[r]
            local cell = rows[r][L + t]
            if ri and (ri.kind == "hdr" or ri.kind == "body" or ri.kind == "foot") and cell and not find(cell, "!!", 1, true) then
              rows[r][L + t] = addattr(cell, "bl=" .. lv)
            end
          end
        end
      end
    end
    apply_styles(m, rows, meta)
    return render_grid(frame, rows, H, L, F, args.title or m.set.title,
      { R = meta.R, T = meta.T, mid = meta.mid, notes = notes_html(m), roles = meta.roles, head = meta.head,
        rinfo = EDMAP and meta.rows or nil, cinfo = EDMAP and meta.cols or nil, set = m.set, rmeta = meta.rows,
        tside = (m.set.titleside == "r" or m.set.titleside == "right") or nil,
        top = (#m.top > 0 and { rows = m.top, style = m.set.topstyle })
              or ((m.set.top or m.set.topl or m.set.topr) and { style = m.set.topstyle, rows = { {
                   m.set.topl and ("al=l; " .. m.set.topl) or "", m.set.top and ("al=c; " .. m.set.top) or "",
                   m.set.topr and ("al=r; " .. m.set.topr) or "" } } })
              or nil })
  end,
  board = view_board,
  list  = view_list,
}

-- 新形式: {{#invoke:Timetable|main|data=…|view=jtb/board/list|dir=down/up|station=…}}
function p.main(frame)
  local args = frame.args
  local m = parse_model(args.data or args[1] or "")
  local dir = args.dir or m.set.dir or "down"
  -- 方向別の設定（title.up / head.up など）で上書き
  for k, v in pairs(m.set) do
    local base, d = match(k, "^(.-)%.(%a+)$")
    if base and d == dir then m.set[base] = v end
  end
  local view = args.view or m.set.view or "jtb"
  local f = p.views[view]
  if not f then return '<span class="jtt-err">unknown view: ' .. view .. "</span>" end
  return f(frame, m, dir, args)
end

--------------------------------------------------------------------------
-- 8. 旧 CSV → 新形式 変換
--    {{#invoke:Timetable|convert|header=|left=|footer=|title=|<CSV>}}
--    → 新形式のテキストを <pre> で出す（コピーして貼り替える）
--------------------------------------------------------------------------
local function split_attr(cell)
  local a, rest = match(cell, "^([^;]*);%s*(.*)$")
  if a then return trim(a), rest end
  return "", cell
end

-- 新形式のトークンとして安全な形にする（必要なら "…"）
local function enc(v)
  if v == "" then return "_" end
  if find(v, '[%s"=]') or v == "_" or v == "!" or v == "%" or v == ":" or v == "---"
     or match(v, "%*%d+$") or match(v, "^[#%[@]") or match(v, "^%d%d$") or find(v, ",", 1, true) then
    return '"' .. gsub(v, '"', '""') .. '"'
  end
  return v
end

local function dispw(s)              -- 等幅で揃えるための表示幅（全角 2）
  local w, i = 0, 1
  while i <= #s do
    local b = byte(s, i)
    if b < 0x80 then w = w + 1; i = i + 1
    elseif b < 0xE0 then w = w + 1; i = i + 2
    elseif b < 0xF0 then w = w + 2; i = i + 3
    else w = w + 2; i = i + 4 end
  end
  return w
end

local function pad(s, w) return s .. string.rep(" ", math.max(0, w - dispw(s))) end

function p.legacy_to_text(rows, H, L, F, title)
  local N = #rows
  local cols = {}
  for k = 1, min(L, 4) do cols[k] = DEFAULT_COLS[4 - min(L, 4) + k] end
  local maxc = 0
  for r = 1, N do if #rows[r] > maxc then maxc = #rows[r] end end
  local nt = maxc - L
  local function cell(r, j) return trim((rows[r] and rows[r][j]) or "") end
  local function isskip(v) return find(v, "!!", 1, true) ~= nil end
  local adq; for q, role in ipairs(cols) do if role == "ad" then adq = q end end

  local o = { "{{#invoke:Timetable|main|data=",
              "# 旧 CSV から変換（header=" .. H .. " left=" .. L .. " footer=" .. F .. "）" }
  o[#o + 1] = "title " .. '"' .. gsub(title or "", '"', '""') .. '"'
  if L ~= 4 then o[#o + 1] = "cols " .. concat(cols, " ") end

  -- 1 行目の路線見出し帯
  local r0 = 1
  do
    local cnt, only = 0, nil
    for j = 1, #(rows[1] or {}) do
      local v = cell(1, j)
      if not isskip(v) then cnt = cnt + 1; only = v end
    end
    if cnt == 1 then
      local a, content = split_attr(only)
      if find(a, "h", 1, true) then
        o[#o + 1] = "head " .. '"' .. gsub(content, '"', '""') .. '"'
        local ht = match(a, "~(%d+)")
        if ht then o[#o + 1] = "headheight " .. ht end
        r0 = 2
      end
    end
  end

  -- 見出し行
  local used = {}
  local function keyfor(label, fallback)
    local l = gsub(nospace(label or ""), "'", "")
    local k = ({ ["列車番号"] = "no", ["열차번호"] = "no", ["列車名"] = "name", ["열차명"] = "name",
                 ["注意"] = "note", ["주의"] = "note", ["行先"] = "to", ["행선"] = "to", ["행선지"] = "to",
                 ["次頁"] = "next", ["다음"] = "next", ["備考"] = "remark", ["비고"] = "remark" })[l] or fallback
    local base, n = k, 1
    while used[k] do n = n + 1; k = base .. n end
    used[k] = true
    return k
  end
  local function infer_fmt(vals)
    local allN, allQ, any = true, true, false
    for _, v in ipairs(vals) do
      if v ~= "" then
        any = true
        if not match(v, "^N{[^{}]*}$") then allN = false end
        if not match(v, "^'[^']*'$") then allQ = false end
      end
    end
    if any and allN then return "N{*}", function(v) return match(v, "^N{(.*)}$") or v end end
    if any and allQ then return "'*'", function(v) return match(v, "^'(.*)'$") or v end end
    return nil, function(v) return v end
  end

  local hdefs, kmlabel = {}, nil
  local nH = H - r0 + 1
  for r = r0, H do
    local k = r - r0 + 1
    local left = {}
    for q = 1, L do left[q] = cell(r, q) end
    local label
    for q = 1, L do
      local a, c = split_attr(left[q])
      if a == "h" or a == ("h<" .. L) then label = match(c, "^'(.*)'$") end
    end
    local def = { raw = left }
    if label then
      local kl = (k == 1 and cols[1] == "km") and match(left[1], "^%^" .. nH .. ";%s*r(.-)%.$") or nil
      local exp = header_left(k, nH, label, cols, kl or kmlabel)
      local same = true
      for q = 1, L do
        local e, l = gsub(exp[q], "%s", ""), gsub(left[q], "%s", "")
        -- 「h」だけの見出し（右端まで自動で結合）と、幅を明示した「h<N」は同じもの
        if e ~= l and gsub(e, "^h<" .. (L - q + 1), "h") ~= gsub(l, "^h<" .. (L - q + 1), "h") then same = false end
      end
      if same then def = { label = label }; if kl then kmlabel = kl end end
    end
    def.key = keyfor(label, "h" .. k)
    local vals = {}
    for t = 1, nt do vals[t] = cell(r, L + t) end
    def.fmt, def.strip = infer_fmt(vals)
    def.vals = vals
    hdefs[#hdefs + 1] = def
  end
  local fdefs = {}
  for r = N - F + 1, N do
    local left = {}
    for q = 1, L do left[q] = cell(r, q) end
    local a1, c1 = split_attr(left[1])
    local label = (a1 == "h<" .. L) and match(c1, "^'(.*)'$") or nil
    local def = { raw = left }
    if label then
      local exp, same = footer_left(label, cols), true
      for q = 1, L do
        local e, l = gsub(exp[q], "%s", ""), gsub(left[q], "%s", "")
        -- 「h」だけの見出し（右端まで自動で結合）と、幅を明示した「h<N」は同じもの
        if e ~= l and gsub(e, "^h<" .. (L - q + 1), "h") ~= gsub(l, "^h<" .. (L - q + 1), "h") then same = false end
      end
      if same then def = { label = label } end
    end
    if not label then
      local _, c = split_attr(left[1])
      for q = 1, L do local _, cc = split_attr(left[q]); if match(cc, "^'(.*)'$") then c = cc end end
      label = match(c, "^'(.*)'$")
    end
    def.key = keyfor(label, "f" .. (r - (N - F)))
    local vals = {}
    for t = 1, nt do vals[t] = cell(r, L + t) end
    def.fmt, def.strip = infer_fmt(vals)
    def.vals = vals
    fdefs[#fdefs + 1] = def
  end
  if kmlabel then o[#o + 1] = "kmlabel " .. kmlabel end

  local function defline(d)
    local s = d.key
    if d.label then s = s .. " " .. enc(d.label)
    else
      local raws = {}
      for q = 1, L do raws[q] = '"' .. gsub(d.raw[q], '"', '""') .. '"' end
      s = s .. " @raw " .. concat(raws, " ")
    end
    if d.fmt then s = s .. " fmt=" .. d.fmt end
    return s
  end
  if #hdefs > 0 then
    o[#o + 1] = ""; o[#o + 1] = "[rows]"
    for _, d in ipairs(hdefs) do o[#o + 1] = defline(d) end
  end
  if #fdefs > 0 then
    o[#o + 1] = ""; o[#o + 1] = "[footer]"
    for _, d in ipairs(fdefs) do o[#o + 1] = defline(d) end
  end

  -- 駅（表示行）
  local st, cols_t = {}, {}       -- st[k] = {fields…, line, pair}, cols_t[t][k] = {a,d} or {v}
  for t = 1, nt do cols_t[t] = {} end
  local r = H + 1
  local function norm_field(role, v)
    local a, c = split_attr(v)
    if a ~= "" then return '"' .. gsub(v, '"', '""') .. '"' end
    if role == "km" then
      if c == "" then return "_" end
      if match(c, "^%d+%.%.%d+$") then return (gsub(c, "%.%.", ".")) end
      return enc(c)
    elseif role == "mk" then
      if c == "" or c == "SPA" then return "_" end
      return enc(c)
    elseif role == "st" then
      local x = match(c, "^'([^']*)'$")
      local pre = ""
      if not x then x = match(c, "^k'([^']*)'%.$"); pre = "*" end
      if not x then x = match(c, "^b'([^']*)'%.$"); pre = "**" end
      if x and x ~= "" and not find(x, '[%s"=*]') and not match(x, "^[_!%%:#%[@]") then return pre .. x end
      return '"' .. gsub(c, '"', '""') .. '"'
    elseif role == "ad" then
      if c == "" then return "_" end
      local k = ({ DEP = "発", ARR = "着", q = "〃" })[c]
      return k or enc(c)
    end
    return enc(c)
  end
  local needq = function(v) return enc(v) ~= v and v ~= "" end
  while r <= N - F do
    local pair = false
    if adq and r + 1 <= N - F then
      local a1, c1 = split_attr(cell(r, adq))
      local a2, c2 = split_attr(cell(r + 1, adq))
      pair = c1 == "ARR" and (a1 == "" or a1 == "&") and c2 == "DEP" and a2 == "&"
      for q, role in ipairs(cols) do
        if role ~= "ad" then
          local a = split_attr(cell(r, q))
          if a ~= "^2" or not isskip(cell(r + 1, q)) then pair = false end
        end
      end
      if pair then
        for t = 1, nt do
          local x, y = cell(r, L + t), cell(r + 1, L + t)
          if x ~= y and (needq(x) or needq(y)) then pair = false end
        end
      end
    end
    local s = { f = {} }
    if pair then
      local a1 = split_attr(cell(r, adq))
      s.line = (a1 == "&")
      for q, role in ipairs(cols) do
        if role == "ad" then s.f[q] = "着発"
        else local _, c = split_attr(cell(r, q)); s.f[q] = norm_field(role, c) end
      end
      for t = 1, nt do cols_t[t][#st + 1] = { a = cell(r, L + t), d = cell(r + 1, L + t) } end
      r = r + 2
    else
      for q, role in ipairs(cols) do
        local v = cell(r, q)
        if role == "ad" then
          local a, c = split_attr(v)
          if a == "&" and (c == "DEP" or c == "ARR" or c == "q" or c == "") then
            s.line = true; v = c
          end
        end
        s.f[q] = norm_field(role, v)
      end
      for t = 1, nt do cols_t[t][#st + 1] = { v = cell(r, L + t) } end
      r = r + 1
    end
    st[#st + 1] = s
  end

  -- 駅欄（桁をそろえて出力）
  local wcol = {}
  for _, s in ipairs(st) do
    for q = 1, L do local w = dispw(s.f[q]); if w > (wcol[q] or 0) then wcol[q] = w end end
  end
  o[#o + 1] = ""; o[#o + 1] = "[stations]"
  do
    local nm, h = { km = "キロ", mk = "印", st = "駅名", ad = "着発" }, {}
    for q, role in ipairs(cols) do h[q] = nm[role] end
    o[#o + 1] = "# " .. concat(h, " / ")
  end
  for _, s in ipairs(st) do
    if s.line then o[#o + 1] = "---" end
    local f = {}
    for q = 1, L do f[q] = (q < L) and pad(s.f[q], wcol[q]) or s.f[q] end
    o[#o + 1] = concat(f, " ")
  end

  -- 列車
  local names = {}
  for _, s in ipairs(st) do
    local stq
    for q, role in ipairs(cols) do if role == "st" then stq = q end end
    local n = stq and gsub(gsub(s.f[stq], '^"', ""), "^%*+", "") or "?"
    names[#names + 1] = n
  end
  o[#o + 1] = ""; o[#o + 1] = "[trains]"
  local hl = {}
  for _, d in ipairs(hdefs) do hl[#hl + 1] = d.label or d.key end
  local fl = {}
  for _, d in ipairs(fdefs) do fl[#fl + 1] = d.label or d.key end
  o[#o + 1] = "# " .. concat(hl, " ") .. " : " .. concat(names, " ")
    .. (#fl > 0 and (" : " .. concat(fl, " ")) or "")
  local prevA, prevF = {}, {}
  for t = 1, nt do
    local A = {}
    for k, d in ipairs(hdefs) do
      local v = d.strip(d.vals[t])
      if v ~= "" and v == prevA[k] then A[k] = "%" else A[k] = enc(v) end
      prevA[k] = v
    end
    local Fo = {}
    for k, d in ipairs(fdefs) do
      local v = d.strip(d.vals[t])
      if v ~= "" and v == prevF[k] then Fo[k] = "%" else Fo[k] = enc(v) end
      prevF[k] = v
    end
    -- 時刻（分だけで書ける所は分だけ）
    local lastm
    local function enct(v)
      if v == "" then return "_" end
      if isskip(v) then return "!" end
      if match(v, "^%d%d%d%d?$") then
        local n = tonumber(v)
        local h, mm = floor(n / 100), n % 100
        local cur = h * 60 + mm
        local outv = v
        if lastm and floor(lastm / 60) == h and mm >= lastm % 60 and fmt_time(cur) == v then
          outv = format("%02d", mm)
        end
        lastm = cur
        return outv
      end
      return enc(v)
    end
    local T = {}
    for k = 1, #st do
      local c = cols_t[t][k]
      if c.v then T[#T + 1] = enct(c.v)
      elseif c.a == c.d then
        local x = enct(c.a); T[#T + 1] = x
      else
        local x = enct(c.a); local y = enct(c.d)
        T[#T + 1] = x .. "," .. y
      end
    end
    while #T > 0 and T[#T] == "_" do T[#T] = nil end
    -- 同じ値の連続を T*N に
    local C, k = {}, 1
    while k <= #T do
      local j = k
      while T[j + 1] == T[k] do j = j + 1 end
      local n = j - k + 1
      if n >= 3 then C[#C + 1] = T[k] .. "*" .. n
      else for _ = 1, n do C[#C + 1] = T[k] end end
      k = j + 1
    end
    while #Fo > 0 and Fo[#Fo] == "_" do Fo[#Fo] = nil end
    local line = concat(A, " ") .. " : " .. concat(C, " ")
    if #Fo > 0 then line = line .. " : " .. concat(Fo, " ") end
    o[#o + 1] = line
  end
  o[#o + 1] = "}}"
  return concat(o, "\n")
end

function p.convert(frame)
  local args = frame.args
  local text = p.legacy_to_text(parse_csv(args[1] or ""),
    tonumber(args.header) or 4, tonumber(args.left) or 3, tonumber(args.footer) or 1, args.title)
  return "<pre>" .. mw.text.nowiki(text) .. "</pre>"
end

p._parse_model, p._build_grid, p._parse_csv = parse_model, build_grid, parse_csv

--------------------------------------------------------------------------
-- 9. 編集器用（ブラウザ版エディタが Fengari 経由で呼ぶ）
--------------------------------------------------------------------------
local function json(v)
  local tv = type(v)
  if tv == "string" then
    return '"' .. gsub(v, '[%c"\\]', function(ch)
      local m2 = { ['"'] = '\\"', ["\\"] = "\\\\", ["\n"] = "\\n", ["\r"] = "\\r", ["\t"] = "\\t" }
      return m2[ch] or format("\\u%04x", byte(ch))
    end) .. '"'
  elseif tv == "number" or tv == "boolean" then
    return tostring(v)
  elseif tv == "table" then
    local n = #v
    local isarr = n > 0 or next(v) == nil
    if isarr then
      for k in pairs(v) do if type(k) ~= "number" then isarr = false; break end end
    end
    local o = {}
    if isarr then
      for k = 1, n do o[k] = json(v[k]) end
      return "[" .. concat(o, ",") .. "]"
    end
    for k, x in pairs(v) do
      if type(x) ~= "function" then o[#o + 1] = json(tostring(k)) .. ":" .. json(x) end
    end
    return "{" .. concat(o, ",") .. "}"
  end
  return "null"
end

-- 新形式テキスト → 編集用モデル（JSON）。時刻は駅（下り順）ごとのセル文字列に解決済み
function p.model_json(text)
  local m = parse_model(text or "")
  local set = {}
  for _, k in ipairs(m.setorder) do set[#set + 1] = { k, m.set[k] } end
  local function defs(list)
    local o = {}
    for _, d in ipairs(list) do
      o[#o + 1] = { key = d.key, label = d.label, rlabel = d.rlabel, raw = d.raw, fmt = d.fmt, merge = d.merge or false, style = d.style, join = d.join or false }
    end
    return o
  end
  local st = {}
  for i, s in ipairs(m.st) do
    local f = {}
    for k, t in pairs(s.f) do f[k] = { v = t.v, q = t.q or false } end
    local rr
    if s.r then rr = {}; for k, t in pairs(s.r) do rr[k] = t.v end end
    st[i] = { f = f, r = rr, line = s.line or false, pair = s.pair or false, free = s.free or false,
              left = s.left, body = s.body, cls = s.cls, style = s.style, fs = s.fs, pk = s.pair and s.pk or nil }
  end
  local function trains(list, dir)
    local stations = (dir == "up") and reverse_stations(m.st) or m.st
    local N, o = #m.st, {}
    for _, tr in ipairs(list) do
      local r = resolve(tr, stations)
      local cells = {}
      for k = 1, N do
        local di = (dir == "up") and (N - k + 1) or k     -- 下り順の駅番号
        local x = r[k]
        local spk = stations[k].pk
        local plain2 = x.p and #x.p == 2 and spk and partsem(spk[1]) ~= "trk" and partsem(spk[2]) ~= "trk"
        if x.p and not plain2 then cells[di] = { p = x.p }    -- 番線の段がある駅は段ごとの並び（表示順）
        elseif x.p then cells[di] = { a = x.p[1], d = x.p[2] }   -- 2 段は表示順（「發,着」の駅も上の段が a）
        elseif x.a then cells[di] = { a = x.a, d = x.d } elseif x.v then cells[di] = { v = x.v } else cells[di] = {} end
      end
      o[#o + 1] = { attr = tr.attr, foot = tr.foot, cells = cells, line = tr.line }
    end
    return o
  end
  return json({ set = set, cols = m.cols, rcols = m.rcols, rows = defs(m.rows), foot = defs(m.foot),
                st = st, down = trains(m.tr.down, "down"), up = trains(m.tr.up, "up"), raw = m.raw })
end

-- 見出し行・脚注行の左側セル（エディタで「左のセルを直接組む」ときの初期値。表示と同じものを返す）
function p.left_cells_json(text)
  local m = parse_model(text or "")
  local rows, _, L, _, meta = build_grid(m, "down")
  local o = { rows = {}, foot = {} }
  for r, row in ipairs(rows) do
    local ri = meta.rows[r]
    if ri and (ri.kind == "hdr" or ri.kind == "foot") then
      local cells = {}
      for q = 1, L do cells[q] = row[q] or "!!;" end
      local list = (ri.kind == "hdr") and o.rows or o.foot
      list[#list + 1] = { key = ri.key, cells = cells }
    end
  end
  return json(o)
end

-- 旧 CSV → 新形式テキスト（エディタの取り込み用）
function p.legacy_text(csv, H, L, F, title)
  return p.legacy_to_text(parse_csv(csv or ""), tonumber(H) or 4, tonumber(L) or 3, tonumber(F) or 1, title)
end

-- セル 1 個の表示用 HTML（エディタの表に使う）
function p.cell_json(raw)
  local c = parse_cell(raw or "")
  return json({ h = c.skip and "" or (c.html_t or c.html or ""), c = c.c or false, skip = c.skip or false,
                th = c.th or false, rs = c.rs, cs = c.cs, style = c.style, cls = c.cls })
end

-- 複数セルを一度に（"\1" 区切り）。エディタの表の表示用
function p.cells_json(blob)
  local o = {}
  for raw in gmatch((blob or "") .. "\1", "([^\1]*)\1") do
    local c = parse_cell(raw)
    o[#o + 1] = json({ h = c.skip and "" or (c.html or ""), c = c.c or false, skip = c.skip or false,
                       rs = c.rs, cs = c.cs, style = c.style, cls = c.cls })
  end
  return "[" .. concat(o, ",") .. "]"
end

-- 新形式テキストを描画（エディタのプレビュー）
function p.render_text(text, view, dir, station)
  EDMAP = true
  local ok, res = pcall(p.main, { args = { data = text, view = (view ~= "" and view) or nil, dir = (dir ~= "" and dir) or nil,
                           station = (station ~= "" and station) or nil } })
  EDMAP = false
  if not ok then error(res, 0) end
  return res
end


-- テスト用に内部関数を公開
p._render = function(s) local c, lines = {}, {}; local h, w, out = render(s, c, lines); return h, c, w, squeeze(out, lines) end

return p