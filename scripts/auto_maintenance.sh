#!/bin/bash
# auto_maintenance.sh - Automated disk cleanup and maintenance script
# Can be run via cron/launchd for regular maintenance
#
# Usage:
#   ./auto_maintenance.sh              # Run with default settings
#   ./auto_maintenance.sh --schedule   # Show cron/launchd setup instructions
#   ./auto_maintenance.sh --help       # Show help
#
# Recommended schedule:
#   - Daily:  cleanup caches/temp files (keep 5 recent runs)
#   - Weekly: compress old results, remove runs > 30 days

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="/Users/achapin/Documents/AI/openstudio-mcp"
LOG_FILE="/var/log/openstudio_maintenance.log"

# Default settings
KEEP_RECENT_DAILY=5
KEEP_RECENT_WEEKLY=3
MAX_RUN_AGE_DAYS=30
COMPRESS_OLD_RESULTS=true
DRY_RUN=false
MODE="daily"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --daily)
            MODE="daily"
            shift
            ;;
        --weekly)
            MODE="weekly"
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --keep-recent)
            KEEP_RECENT_DAILY="$2"
            shift 2
            ;;
        --schedule)
            MODE="schedule"
            shift
            ;;
        --help)
            echo "Usage: $0 [--daily|--weekly] [--dry-run] [--keep-recent N] [--schedule] [--help]"
            echo ""
            echo "Modes:"
            echo "  --daily    Run daily maintenance (default): clean cache/temp, keep 5 recent runs"
            echo "  --weekly   Run weekly maintenance: compress results, remove runs > 30 days"
            echo "  --schedule Show cron/launchd setup instructions"
            echo ""
            echo "Options:"
            echo "  --dry-run       Show what would be done without making changes"
            echo "  --keep-recent N Number of recent runs to keep (daily mode)"
            echo "  --schedule      Show scheduling setup instructions"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "$msg"
    if [[ -w "$(dirname "$LOG_FILE")" ]] || [[ "$LOG_FILE" == "/dev/stdout" ]]; then
        echo "$msg" >> "$LOG_FILE" 2>/dev/null || true
    fi
}

run_cmd() {
    if [[ "$DRY_RUN" == "true" ]]; then
        log "[DRY-RUN] Would run: $*"
    else
        eval "$@"
    fi
}

# Show scheduling instructions
if [[ "$MODE" == "schedule" ]]; then
    cat << 'EOF'
=== Scheduling Instructions ===

macOS (launchd) - RECOMMENDED:
Create ~/Library/LaunchAgents/com.openstudio.maintenance.plist:
EOF
    cat << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.openstudio.maintenance</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/achapin/Documents/AI/openstudio-mcp/scripts/auto_maintenance.sh</string>
        <string>--daily</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/var/log/openstudio_maintenance.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/openstudio_maintenance_error.log</string>
</dict>
</plist>
PLIST
    cat << 'EOF'

Then load it:
  launchctl load ~/Library/LaunchAgents/com.openstudio.maintenance.plist
  launchctl start com.openstudio.maintenance

For weekly (Sunday 4 AM), add a second plist with --weekly flag.

---

Linux/macOS (cron):
  # Daily at 3 AM
  0 3 * * * /Users/achapin/Documents/AI/openstudio-mcp/scripts/auto_maintenance.sh --daily >> /var/log/openstudio_maintenance.log 2>&1
  
  # Weekly on Sunday at 4 AM
  0 4 * * 0 /Users/achapin/Documents/AI/openstudio-mcp/scripts/auto_maintenance.sh --weekly >> /var/log/openstudio_maintenance.log 2>&1

---

Manual run:
  ./auto_maintenance.sh --daily --dry-run    # Preview daily cleanup
  ./auto_maintenance.sh --weekly --dry-run   # Preview weekly cleanup
EOF
    exit 0
fi

log "=== OpenStudio Maintenance Started (mode: $MODE) ==="

RUNS_DIR="$PROJECT_DIR/data/runs/alex"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || LOG_FILE="/dev/stdout"

# ===========================================
# DAILY MAINTENANCE
# ===========================================
if [[ "$MODE" == "daily" ]]; then
    log "Running daily cleanup (keep $KEEP_RECENT_DAILY recent runs)..."
    
    # Clean cache directories
    find "$RUNS_DIR" -name ".cache" -type d 2>/dev/null | while read dir; do
        size=$(du -sh "$dir" 2>/dev/null | cut -f1)
        log "Removing cache: $dir ($size)"
        run_cmd rm -rf "$dir"
    done
    
    # Clean temp directories
    find "$RUNS_DIR" -name "tmp" -type d 2>/dev/null | while read dir; do
        size=$(du -sh "$dir" 2>/dev/null | cut -f1)
        log "Removing temp: $dir ($size)"
        run_cmd rm -rf "$dir"
    done
    
    # Clean old logs (>7 days)
    find "$PROJECT_DIR" -name "*.log" -mtime +7 -type f 2>/dev/null | while read file; do
        size=$(du -h "$file" 2>/dev/null | cut -f1)
        log "Removing old log: $file ($size)"
        run_cmd rm -f "$file"
    done
    
    # Keep N most recent runs
    run_dirs=()
    while IFS= read -r dir; do
        run_dirs+=("$dir")
    done < <(find "$RUNS_DIR" -maxdepth 1 -type d ! -path "$RUNS_DIR" ! -name "uploads" ! -name "examples" -print0 2>/dev/null | xargs -0 stat -f "%m %N" | sort -rn | cut -d' ' -f2-)
    
    count=0
    for dir in "${run_dirs[@]}"; do
        if [[ $count -ge $KEEP_RECENT_DAILY ]]; then
            size=$(du -sh "$dir" 2>/dev/null | cut -f1)
            log "Removing old run (daily): $dir ($size)"
            run_cmd rm -rf "$dir"
        else
            size=$(du -sh "$dir" 2>/dev/null | cut -f1)
            log "Keeping recent run: $dir ($size)"
        fi
        ((count++))
    done
fi

# ===========================================
# WEEKLY MAINTENANCE
# ===========================================
if [[ "$MODE" == "weekly" ]]; then
    log "Running weekly maintenance..."
    
    # Remove runs older than MAX_RUN_AGE_DAYS
    find "$RUNS_DIR" -maxdepth 1 -type d ! -path "$RUNS_DIR" ! -name "uploads" ! -name "examples" -mtime +$MAX_RUN_AGE_DAYS 2>/dev/null | while read dir; do
        size=$(du -sh "$dir" 2>/dev/null | cut -f1)
        log "Removing run older than $MAX_RUN_AGE_DAYS days: $dir ($size)"
        run_cmd rm -rf "$dir"
    done
    
    # Compress large result files in kept runs
    if [[ "$COMPRESS_OLD_RESULTS" == "true" ]]; then
        log "Compressing large result files..."
        find "$RUNS_DIR" -maxdepth 1 -type d ! -path "$RUNS_DIR" ! -name "uploads" ! -name "examples" 2>/dev/null | while read dir; do
            for f in "$dir"/eplusout.sql "$dir"/eplusout.eso "$dir"/eplustbl.htm "$dir"/data_point.zip; do
                if [[ -f "$f" && ! -f "$f.gz" ]]; then
                    size=$(du -h "$f" 2>/dev/null | cut -f1)
                    log "Compressing: $f ($size)"
                    run_cmd gzip -9 "$f"
                fi
            done
        done
    fi
    
    # Keep only N most recent runs
    run_dirs=()
    while IFS= read -r dir; do
        run_dirs+=("$dir")
    done < <(find "$RUNS_DIR" -maxdepth 1 -type d ! -path "$RUNS_DIR" ! -name "uploads" ! -name "examples" -print0 2>/dev/null | xargs -0 stat -f "%m %N" | sort -rn | cut -d' ' -f2-)
    
    count=0
    for dir in "${run_dirs[@]}"; do
        if [[ $count -ge $KEEP_RECENT_WEEKLY ]]; then
            size=$(du -sh "$dir" 2>/dev/null | cut -f1)
            log "Removing old run (weekly): $dir ($size)"
            run_cmd rm -rf "$dir"
        else
            size=$(du -sh "$dir" 2>/dev/null | cut -f1)
            log "Keeping recent run: $dir ($size)"
        fi
        ((count++))
    done
fi

# ===========================================
# SUMMARY
# ===========================================
log "=== Maintenance Complete ==="
if [[ -d "$PROJECT_DIR" ]]; then
    total_size=$(du -sh "$PROJECT_DIR" 2>/dev/null | cut -f1)
    log "Project total size: $total_size"
fi
if [[ -d "$RUNS_DIR" ]]; then
    runs_size=$(du -sh "$RUNS_DIR" 2>/dev/null | cut -f1)
    log "Runs directory size: $runs_size"
    du -sh "$RUNS_DIR"/* 2>/dev/null | sort -hr | while read line; do
        log "  $line"
    done
fi

if [[ "$DRY_RUN" == "true" ]]; then
    log "=== DRY RUN COMPLETE - No changes made ==="
fi