<?php
/*
 * 시각표 책 PDF: 읽기 링크와 같은 설계도(#read= 뒤 글자)를 받아, 서버의 판 고정 Chrome(/opt/ttpdf)으로 PDF 를 만든다.
 *   ?b=<설계도>
 * 같은 설계도·같은 인쇄기 판이면 만들어 둔 것을 그대로 낸다. 한 번에 하나씩만 만든다.
 */
set_time_limit(320);
$b = (string)($_GET['b'] ?? '');
if (!preg_match('/^[A-Za-z0-9_-]{8,200000}$/', $b)) { http_response_code(400); exit('bad book'); }

$dir = sys_get_temp_dir() . '/ttprint';
if (!is_dir($dir)) @mkdir($dir, 0700, true);
// 인쇄기(이 폴더의 파일)가 바뀌면 다시 만든다
$ver = '';
foreach (['layout.js', 'app.js', 'print.css', 'index.html'] as $f) $ver .= @filemtime(__DIR__ . '/' . $f) . ',';
$key = sha1($b . '|' . $ver . '|chrome-156.0.8078.47');
$pdf = "$dir/pdf-$key.pdf";

if (!is_file($pdf)) {
    $lock = fopen("$dir/pdf.lock", 'c');
    flock($lock, LOCK_EX);
    if (!is_file($pdf)) {
        $tmp = "$dir/.pdf-$key-" . getmypid() . '.pdf';
        $cmd = 'HOME=' . escapeshellarg(sys_get_temp_dir()) . ' timeout 300 node /opt/ttpdf/render.js ' . escapeshellarg($b) . ' ' . escapeshellarg($tmp) . ' 2>&1';
        exec($cmd, $out, $rc);
        if ($rc !== 0 || !is_file($tmp)) {
            flock($lock, LOCK_UN);
            http_response_code(500);
            header('Content-Type: text/plain; charset=utf-8');
            exit("PDF 를 만들지 못했다\n" . implode("\n", array_slice($out, -5)));
        }
        rename($tmp, $pdf);
    }
    flock($lock, LOCK_UN);
}
header('Content-Type: application/pdf');
header('Content-Disposition: inline; filename="timetable-' . substr($key, 0, 8) . '.pdf"');
header('Content-Length: ' . filesize($pdf));
header('Cache-Control: public, max-age=86400');
readfile($pdf);
