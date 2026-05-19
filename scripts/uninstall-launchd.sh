#!/usr/bin/env bash
# 卸载 macOS launchd 自动启动服务

set -euo pipefail

PLIST_DEST="$HOME/Library/LaunchAgents/com.radar.ai.plist"

if [ ! -f "$PLIST_DEST" ]; then
    echo "⚠️  服务未安装（找不到 $PLIST_DEST）"
    exit 0
fi

launchctl unload -w "$PLIST_DEST" 2>/dev/null || true
rm -f "$PLIST_DEST"
echo "✅ Radar launchd 服务已卸载"
