<?php
/*
 * 시각표 인쇄(t.halv.kr/print)용 읽기 전용 API.
 * 같은 서버의 미디어위키 뒷단(127.0.0.1:3001, Anubis 앞)에 묻는다. 모듈:Timetable 을 쓰는 문서만 돌려준다.
 *
 *   ?action=list                  모듈:Timetable 을 쓰는 문서 목록 (최신 판 번호·시각)
 *   ?action=page&title=…[&oldid=…] 문서를 파싱한 HTML (oldid 를 주면 그 판으로 고정)
 *   ?action=css                   위키 Common.css 가운데 시각표(jtt-)에 해당하는 규칙과 DiaPro 글꼴 선언
 *
 * GitHub Pages(halv.kr/timetable/print/)에서는 PHP 가 돌지 않으므로 t.halv.kr 에서만 쓴다.
 */
const BACKEND = 'http://127.0.0.1:3001/api.php';
const WIKI_HOST = 'w.halv.kr';
const MODULE = '모듈:Timetable';

function mw(array $q) {
    $q += ['format' => 'json', 'formatversion' => 2];
    $ch = curl_init(BACKEND . '?' . http_build_query($q));
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER => ['Host: ' . WIKI_HOST, 'X-Forwarded-Proto: https'],
        CURLOPT_TIMEOUT => 30,
    ]);
    $body = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    if ($body === false || $code !== 200) fail(502, 'wiki backend error');
    $j = json_decode($body, true);
    if (!is_array($j)) fail(502, 'wiki backend returned non-JSON');
    if (isset($j['error'])) fail(400, $j['error']['info'] ?? 'wiki error');
    return $j;
}

function fail(int $code, string $msg) {
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode(['error' => $msg], JSON_UNESCAPED_UNICODE);
    exit;
}

function out($data, string $cache = 'no-store') {
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: ' . $cache);
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

/** 모듈:Timetable 을 쓰는 문서들: [title => [ns, pageid, revid, timestamp, displaytitle]] */
function timetable_pages(): array {
    $pages = [];
    $cont = [];
    do {
        $j = mw([
            'action' => 'query', 'generator' => 'embeddedin', 'geititle' => MODULE, 'geilimit' => 'max',
            'prop' => 'revisions|info', 'rvprop' => 'ids|timestamp', 'inprop' => 'displaytitle',
        ] + $cont);
        foreach ($j['query']['pages'] ?? [] as $p) {
            $rev = $p['revisions'][0] ?? [];
            $pages[$p['title']] = [
                'title' => $p['title'], 'ns' => $p['ns'], 'pageid' => $p['pageid'],
                'revid' => $rev['revid'] ?? null, 'timestamp' => $rev['timestamp'] ?? null,
                'displaytitle' => strip_tags($p['displaytitle'] ?? $p['title']),
            ];
        }
        $cont = $j['continue'] ?? [];
    } while ($cont);
    return $pages;
}

/** CSS 를 최상위 규칙 단위로 나눈다 (주석·문자열 안의 괄호는 건너뛴다) */
function css_blocks(string $css): array {
    $out = [];
    $n = strlen($css);
    $start = 0; $depth = 0; $i = 0;
    while ($i < $n) {
        $c = $css[$i];
        if ($c === '/' && $i + 1 < $n && $css[$i + 1] === '*') {
            $e = strpos($css, '*/', $i + 2);
            $i = $e === false ? $n : $e + 2;
            continue;
        }
        if ($c === '"' || $c === "'") {
            $j = $i + 1;
            while ($j < $n && $css[$j] !== $c) { if ($css[$j] === '\\') $j++; $j++; }
            $i = $j + 1;
            continue;
        }
        if ($c === '{') $depth++;
        elseif ($c === '}') {
            $depth--;
            if ($depth === 0) { $out[] = substr($css, $start, $i + 1 - $start); $start = $i + 1; }
        } elseif ($c === ';' && $depth === 0) {
            $out[] = substr($css, $start, $i + 1 - $start); $start = $i + 1;   // @import 같은 한 줄 규칙
        }
        $i++;
    }
    return $out;
}

/** 시각표에 해당하는 규칙만 남긴다. @media·@supports 는 안을 다시 걸러 낸다 */
function jtt_css(string $css): string {
    $keep = [];
    foreach (css_blocks($css) as $b) {
        $code = trim(preg_replace('~/\*.*?\*/~s', '', $b));
        if ($code === '') continue;
        $brace = strpos($code, '{');
        $prelude = $brace === false ? $code : trim(substr($code, 0, $brace));
        if (preg_match('/^@(media|supports|layer|container)\b/i', $prelude)) {
            $inner = jtt_css(substr($code, $brace + 1, -1));
            if ($inner !== '') $keep[] = $prelude . " {\n" . $inner . "\n}";
        } elseif (stripos($prelude, '@font-face') === 0) {
            if (stripos($code, 'DiaPro') !== false) $keep[] = $code;
        } elseif (stripos($code, 'jtt') !== false) {
            $keep[] = $code;
        }
    }
    return implode("\n", $keep);
}

$action = $_GET['action'] ?? '';

if ($action === 'list') {
    out(['pages' => array_values(timetable_pages())]);
}

if ($action === 'page') {
    $title = trim((string)($_GET['title'] ?? ''));
    $oldid = isset($_GET['oldid']) && ctype_digit((string)$_GET['oldid']) ? (int)$_GET['oldid'] : 0;
    $pages = timetable_pages();
    if (!isset($pages[$title])) fail(404, 'not a timetable page');
    $q = ['action' => 'parse', 'prop' => 'text|revid|displaytitle', 'disableeditsection' => 1, 'disablelimitreport' => 1];
    if ($oldid) $q['oldid'] = $oldid; else $q['page'] = $title;
    $p = mw($q)['parse'];
    if ($p['title'] !== $title) fail(400, 'oldid does not belong to this page');
    $r = mw(['action' => 'query', 'revids' => $p['revid'], 'prop' => 'revisions', 'rvprop' => 'ids|timestamp']);
    $ts = $r['query']['pages'][0]['revisions'][0]['timestamp'] ?? null;
    out([
        'title' => $title, 'ns' => $pages[$title]['ns'],
        'displaytitle' => strip_tags($p['displaytitle'] ?? $title),
        'revid' => $p['revid'], 'timestamp' => $ts,
        'latest' => $pages[$title]['revid'],
        'html' => $p['text'],
    ], $oldid ? 'public, max-age=31536000, immutable' : 'no-store');
}

if ($action === 'css') {
    $j = mw(['action' => 'query', 'prop' => 'revisions', 'titles' => 'MediaWiki:Common.css', 'rvprop' => 'content', 'rvslots' => 'main']);
    $css = $j['query']['pages'][0]['revisions'][0]['slots']['main']['content'] ?? '';
    header('Content-Type: text/css; charset=utf-8');
    header('Cache-Control: public, max-age=300');
    echo "/* 쩌모위키 MediaWiki:Common.css 에서 시각표 부분만 */\n" . jtt_css($css) . "\n";
    exit;
}

fail(400, 'unknown action');
