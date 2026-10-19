#!/usr/bin/env bash
# Creates every topic in topics.txt. Safe to rerun (existing topics are skipped).
set -euo pipefail
KT=/opt/kafka/bin/kafka-topics.sh

grep -v '^\s*#' /init/topics.txt | grep -v '^\s*$' | while read -r topic partitions cleanup _; do
  "$KT" --bootstrap-server kafka:9092 --create --if-not-exists \
        --topic "$topic" --partitions "$partitions" --replication-factor 1 \
        --config "cleanup.policy=$cleanup"
done
"$KT" --bootstrap-server kafka:9092 --list
