#!/bin/bash
# Mac(Claude 작업 VM)에서 시각표 PDF 를 만든다: ./run.sh [book.json]
cd "$(dirname "$0")"
export TEXMFHOME="$PWD/texmf" TEXMFVAR="$PWD/texmf-var"
python3 ttbook.py "${1:-book.json}"
