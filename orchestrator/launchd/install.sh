#!/usr/bin/env bash
# Installs launchd schedules for the job-pipeline orchestrator.
#
#   chmod +x orchestrator/launchd/install.sh   # first time only
#   ./orchestrator/launchd/install.sh
#
# Schedules installed:
#   com.jameslako.jobpipeline.discovery  - every 4h,  `orchestrator.runner discover`
#   com.jameslako.jobpipeline.daily      - 08:00 daily, track -> crm -> digest -> health
#   com.jameslako.jobpipeline.analytics  - Sun 09:00,  `orchestrator.runner analytics`
#
# The daily job chains 4 subcommands via `zsh -c` instead of pointing at
# `orchestrator.runner full`, because `full` also re-runs resolve/discover,
# which is already covered by the separate 4-hourly discovery schedule —
# chaining avoids doubling up on ATS resolution + discovery API calls.
set -euo pipefail

REPO_ROOT="/Users/jameslako/Desktop/roadmap/job-pipeline"
PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
LOG_DIR="$REPO_ROOT/logs"
AGENTS_DIR="$HOME/Library/LaunchAgents"

mkdir -p "$LOG_DIR" "$AGENTS_DIR"

write_and_check() {
    local label="$1"
    local plist_path="$AGENTS_DIR/$label.plist"
    cat > "$plist_path"
    if ! /usr/bin/python3 -c "import xml.dom.minidom, sys; xml.dom.minidom.parse(sys.argv[1])" "$plist_path"; then
        echo "ERROR: generated plist is not well-formed XML: $plist_path" >&2
        exit 1
    fi
    echo "Wrote $plist_path"
}

load_agent() {
    local label="$1"
    local plist_path="$AGENTS_DIR/$label.plist"
    launchctl unload "$plist_path" >/dev/null 2>&1 || true
    launchctl load "$plist_path"
    echo "Loaded $label"
}

# ---------- discovery: every 4 hours ----------
write_and_check "com.jameslako.jobpipeline.discovery" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jameslako.jobpipeline.discovery</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>-m</string>
        <string>orchestrator.runner</string>
        <string>discover</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$REPO_ROOT</string>
    <key>StartInterval</key>
    <integer>14400</integer>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/discovery.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/discovery.log</string>
</dict>
</plist>
PLIST

# ---------- daily: 08:00, track -> crm -> digest -> health ----------
write_and_check "com.jameslako.jobpipeline.daily" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jameslako.jobpipeline.daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>-c</string>
        <string>"$PYTHON_BIN" -m orchestrator.runner track &amp;&amp; "$PYTHON_BIN" -m orchestrator.runner crm &amp;&amp; "$PYTHON_BIN" -m orchestrator.runner digest &amp;&amp; "$PYTHON_BIN" -m orchestrator.runner health</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$REPO_ROOT</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/daily.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/daily.log</string>
</dict>
</plist>
PLIST

# ---------- analytics: weekly, Sunday 09:00 ----------
write_and_check "com.jameslako.jobpipeline.analytics" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jameslako.jobpipeline.analytics</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>-m</string>
        <string>orchestrator.runner</string>
        <string>analytics</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$REPO_ROOT</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>0</integer>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/analytics.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/analytics.log</string>
</dict>
</plist>
PLIST

load_agent "com.jameslako.jobpipeline.discovery"
load_agent "com.jameslako.jobpipeline.daily"
load_agent "com.jameslako.jobpipeline.analytics"

echo "Done. Logs will be written under $LOG_DIR."
