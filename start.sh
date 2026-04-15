#!/bin/bash
# 1시간마다 실행
while true; do
    python rag_autosave.py
    echo "다음 실행까지 1시간 대기..."
    sleep 3600
done
