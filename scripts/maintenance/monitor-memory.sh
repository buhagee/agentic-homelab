#!/bin/bash
#
# Memory Usage Monitor
# Logs Docker container memory usage for analysis
#
# Usage:
#   bash maintenance/monitor-memory.sh
#
# Schedule with cron:
#   */15 * * * * $HOME/projects/qacey-platform/scripts/maintenance/monitor-memory.sh
#

set -euo pipefail

LOG_DIR="/var/log/qacey"
LOG_FILE="$LOG_DIR/memory-usage.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Create log directory if it doesn't exist
sudo mkdir -p "$LOG_DIR"
sudo chown buhagiar:buhagiar "$LOG_DIR"

# Log header if file doesn't exist
if [[ ! -f "$LOG_FILE" ]]; then
    echo "timestamp,container,mem_usage_mb,mem_limit_mb,mem_percent,cpu_percent" > "$LOG_FILE"
fi

# Get stats for all containers
docker stats --no-stream --format "{{.Name}},{{.MemUsage}},{{.MemPerc}},{{.CPUPerc}}" | while IFS=',' read -r name mem_usage mem_perc cpu_perc; do
    # Parse memory usage (e.g., "123.4MiB / 512MiB" -> 123.4, 512)
    mem_used=$(echo "$mem_usage" | awk '{print $1}' | sed 's/MiB//;s/GiB/*1024/')
    mem_limit=$(echo "$mem_usage" | awk '{print $3}' | sed 's/MiB//;s/GiB/*1024/')
    
    # Convert to MB if needed (handle GiB)
    if [[ "$mem_used" == *"*"* ]]; then
        mem_used=$(echo "$mem_used" | bc)
    fi
    if [[ "$mem_limit" == *"*"* ]]; then
        mem_limit=$(echo "$mem_limit" | bc)
    fi
    
    # Remove % from percentages
    mem_perc=$(echo "$mem_perc" | sed 's/%//')
    cpu_perc=$(echo "$cpu_perc" | sed 's/%//')
    
    # Log the data
    echo "$TIMESTAMP,$name,$mem_used,$mem_limit,$mem_perc,$cpu_perc" >> "$LOG_FILE"
done

# Rotate log if it gets too large (keep last 200k lines = ~4 weeks at 15min intervals)
# 4 weeks = 28 days * 96 samples/day * ~30 containers = ~80k lines + header
if [[ $(wc -l < "$LOG_FILE") -gt 200000 ]]; then
    tail -n 100000 "$LOG_FILE" > "$LOG_FILE.tmp"
    mv "$LOG_FILE.tmp" "$LOG_FILE"
fi
