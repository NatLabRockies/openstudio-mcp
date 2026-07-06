#!/bin/bash
# cleanup_analysis.sh - Analyze disk usage and identify cleanup candidates
# Run this first to see what can be safely cleaned

set -euo pipefail

PROJECT_DIR="/Users/achapin/Documents/AI/openstudio-mcp"
echo "=== Disk Cleanup Analysis ==="
echo "Project directory: $PROJECT_DIR"
echo ""

echo "--- Overall project size ---"
du -sh "$PROJECT_DIR" 2>/dev/null

echo ""
echo "--- Top directories by size ---"
du -sh "$PROJECT_DIR"/* 2>/dev/null | sort -hr

echo ""
echo "--- Simulation runs breakdown ---"
if [ -d "$PROJECT_DIR/data/runs" ]; then
    du -sh "$PROJECT_DIR/data/runs"/* 2>/dev/null | sort -hr
fi

echo ""
echo "--- Cache directories (safe to clean) ---"
find "$PROJECT_DIR/data/runs" -name ".cache" -type d 2>/dev/null | while read dir; do
    size=$(du -sh "$dir" 2>/dev/null | cut -f1)
    echo "$dir: $size"
done

echo ""
echo "--- Temp directories (safe to clean) ---"
find "$PROJECT_DIR/data/runs" -name "tmp" -type d 2>/dev/null | while read dir; do
    size=$(du -sh "$dir" 2>/dev/null | cut -f1)
    echo "$dir: $size"
done

echo ""
echo "--- Log files older than 7 days ---"
find "$PROJECT_DIR" -name "*.log" -mtime +7 -type f 2>/dev/null | while read f; do
    size=$(du -h "$f" 2>/dev/null | cut -f1)
    echo "$f: $size"
done

echo ""
echo "=== Summary ==="
TOTAL_CACHE=$(find "$PROJECT_DIR/data/runs" -name ".cache" -type d -exec du -ch {} + 2>/dev/null | tail -1 | cut -f1)
TOTAL_TMP=$(find "$PROJECT_DIR/data/runs" -name "tmp" -type d -exec du -ch {} + 2>/dev/null | tail -1 | cut -f1)
OLD_LOGS=$(find "$PROJECT_DIR" -name "*.log" -mtime +7 -type f -exec du -ch {} + 2>/dev/null | tail -1 | cut -f1)
echo "Cache directories: ${TOTAL_CACHE:-0}"
echo "Temp directories: ${TOTAL_TMP:-0}"
echo "Old logs: ${OLD_LOGS:-0}"