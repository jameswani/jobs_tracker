#!/usr/bin/env bash
# Unloads and removes the job-pipeline launchd schedules installed by install.sh.
#
#   chmod +x orchestrator/launchd/uninstall.sh   # first time only
#   ./orchestrator/launchd/uninstall.sh
set -euo pipefail

AGENTS_DIR="$HOME/Library/LaunchAgents"
LABELS=(
    "com.jameslako.jobpipeline.discovery"
    "com.jameslako.jobpipeline.daily"
    "com.jameslako.jobpipeline.analytics"
)

for label in "${LABELS[@]}"; do
    plist_path="$AGENTS_DIR/$label.plist"
    launchctl unload "$plist_path" >/dev/null 2>&1 || true
    if [ -f "$plist_path" ]; then
        rm "$plist_path"
        echo "Removed $plist_path"
    else
        echo "Not installed: $plist_path"
    fi
done

echo "Done."
