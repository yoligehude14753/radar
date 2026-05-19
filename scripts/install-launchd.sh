#!/usr/bin/env bash
# 安装 macOS launchd 自动启动服务
# 用法: bash scripts/install-launchd.sh

set -euo pipefail

PLIST_SRC="$(cd "$(dirname "$0")/.." && pwd)/launchd/com.radar.ai.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.radar.ai.plist"
RADAR_BIN="$(which radar 2>/dev/null || echo '')"

if [ -z "$RADAR_BIN" ]; then
    echo "❌ 找不到 radar 命令，请先安装：pip install -e ."
    exit 1
fi

# 替换 plist 中的占位符
WORK_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USERNAME="$(whoami)"

sed \
    -e "s|/opt/homebrew/bin/radar|$RADAR_BIN|g" \
    -e "s|/Users/REPLACE_WITH_USERNAME/radar|$WORK_DIR|g" \
    "$PLIST_SRC" > "$PLIST_DEST"

echo "✅ plist 已写入: $PLIST_DEST"

# 卸载旧版本（如果存在）
launchctl unload "$PLIST_DEST" 2>/dev/null || true

# 加载新版本
launchctl load -w "$PLIST_DEST"

echo "✅ Radar 已注册为 launchd 服务，将在登录后自动启动"
echo "   查看状态: launchctl list | grep radar"
echo "   查看日志: tail -f /tmp/radar.stdout.log"
echo "   卸载服务: bash scripts/uninstall-launchd.sh"
