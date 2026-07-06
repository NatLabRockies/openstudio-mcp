#!/bin/bash
# cleanup_script.sh - Safely clean up simulation outputs and temporary files
# Usage: ./cleanup_script.sh [--dry-run] [--keep-recent N] [--compress-results]

set -euo pipefail

PROJECT_DIR="/Users/achapin/Documents/AI/openstudio-mcp"
DRY_RUN=false
KEEP_RECENT=5
COMPRESS_RESULTS=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --keep-recent)
            KEEP_RECENT="$2"
            shift 2
            ;;
        --compress-results)
            COMPRESS_RESULTS=true
            shift
            ;;
        --help)
            echo "Usage: $0 [--dry-run] [--keep-recent N] [--compress-results]"
            echo "  --dry-run         Show what would be deleted without actually deleting"
            echo "  --keep-recent N   Keep N most recent runs (default: 5)"
            echo "  --compress-results Compress large result files instead of deleting"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

log() {
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[DRY-RUN] $1"
    else
        echo "[CLEANUP] $1"
    fi
}

run_cmd() {
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[DRY-RUN] Would run: $*"
    else
        eval "$@"
    fi
}

echo "=== Disk Cleanup Script ==="
echo "Project: $PROJECT_DIR"
echo "Mode: $([[ "$DRY_RUN" == "true" ]] && echo "DRY RUN" || echo "LIVE")"
echo "Keep recent runs: $KEEP_RECENT"
echo ""

RUNS_DIR="$PROJECT_DIR/data/runs/alex"

# 1. Find and remove old .cache directories (safe - they're regenerable)
echo "--- Cleaning cache directories ---"
find "$RUNS_DIR" -name ".cache" -type d | while read dir; do
    size=$(du -sh "$dir" 2>/dev/null | cut -f1)
    log "Removing cache: $dir ($size)"
    run_cmd rm -rf "$dir"
done

# 2. Find and remove old tmp directories (safe - they're temporary)
echo ""
echo "--- Cleaning temp directories ---"
find "$RUNS_DIR" -name "tmp" -type d | while read dir; do
    size=$(du -sh "$dir" 2>/dev/null | cut -f1)
    log "Removing temp: $dir ($size)"
    run_cmd rm -rf "$dir"
done

# 3. Find old log files (older than 30 days)
echo ""
echo "--- Cleaning old log files (>30 days) ---"
find "$PROJECT_DIR" -name "*.log" -mtime +30 -type f | while read file; do
    size=$(du -h "$file" 2>/dev/null | cut -f1)
    log "Removing old log: $file ($size)"
    run_cmd rm -f "$file"
done

# 4. Handle old simulation runs - keep N most recent
echo ""
echo "--- Managing old simulation runs ---"
if [ -d "$RUNS_DIR" ]; then
    # Get all run directories sorted by modification time (newest first) - macOS compatible
    run_dirs=()
    while IFS= read -r dir; do
        run_dirs+=("$dir")
    done < <(find "$RUNS_DIR" -maxdepth 1 -type d ! -path "$RUNS_DIR" ! -name "uploads" ! -name "examples" -print0 2>/dev/null | xargs -0 stat -f "%m %N" | sort -rn | cut -d' ' -f2-)
    
    count=0
    for dir in "${run_dirs[@]}"; do
        if [[ $count -ge $KEEP_RECENT ]]; then
            size=$(du -sh "$dir" 2>/dev/null | cut -f1)
            log "Old run (keeping $KEEP_RECENT recent): $dir ($size)"
            
            if [[ "$COMPRESS_RESULTS" == "true" ]]; then
                # Compress large output files instead of deleting
                log "  Compressing large files in $dir"
                find "$dir" -name "eplusout.sql" -o -name "eplusout.eso" -o -name "eplustbl.htm" -o -name "data_point.zip" | while read f; do
                    if [[ ! -f "$f.gz" ]]; then
                        log "  Compressing $f"
                        run_cmd gzip -9 "$f"
                    fi
                done
            else
                # Delete the entire run directory
                run_cmd rm -rf "$dir"
            fi
        else
            size=$(du -sh "$dir" 2>/dev/null | cut -f1)
            log "Keeping recent run: $dir ($size)"
        fi
        ((count++))
    done
fi

# 5. Compress large result files in kept runs
if [[ "$COMPRESS_RESULTS" == "true" ]]; then
    echo ""
    echo "--- Compressing large result files in kept runs ---"
    for dir in "${run_dirs[@]:0:$KEEP_RECENT}"; do
        find "$dir" -name "eplusout.sql" -o -name "eplusout.eso" -o -name "eplustbl.htm" -o -name "data_point.zip" | while read f; do
            if [[ -f "$f" && ! -f "$f.gz" ]]; then
                size=$(du -h "$f" 2>/dev/null | cut -f1)
                log "Compressing $f ($size)"
                run_cmd gzip -9 "$f"
            fi
        done
    done
fi

# 6. Show final disk usage
echo ""
echo "=== Final disk usage ==="
du -sh "$PROJECT_DIR" 2>/dev/null
if [ -d "$RUNS_DIR" ]; then
    du -sh "$RUNS_DIR"/* 2>/dev/null | sort -hr
fi

if [[ "$DRY_RUN" == "true" ]]; then
    echo ""
    echo "=== DRY RUN COMPLETE - No changes made ==="
    echo "Run without --dry-run to execute cleanup"
fi