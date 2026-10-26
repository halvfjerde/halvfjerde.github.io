#!/bin/bash
# 위키에서 시각표 문서 원문을 받아 pages/ 에 둔다: ./fetch.sh [노선 …]  (없으면 목차의 모든 노선)
cd "$(dirname "$0")"
CFG=../config
P="연습장:시각표 2026년 11월호"
lines="$*"
if [ -z "$lines" ]; then
  lines=$(ssh -F $CFG halvkr "cd /var/www/html && php maintenance/run.php getText '$P'" 2>/dev/null | sed -n 's/^\* \[\[[^|]*|\([^]]*\)\]\]$/\1/p')
fi
mkdir -p pages
for n in $lines; do
  ssh -F $CFG halvkr "cd /var/www/html && php maintenance/run.php getText '$P/$n'" > "pages/$n.txt" 2>/dev/null && echo "$n $(wc -c < "pages/$n.txt")"
done
