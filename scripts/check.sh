#!/usr/bin/env bash
# cmsketch 固定验收入口：等价于在仓库根目录执行 python check/check.py
# 用法：bash scripts/check.sh [-list | --only <组名>]
set -euo pipefail

cd "$(dirname "$0")/.."

exec python check/check.py "$@"