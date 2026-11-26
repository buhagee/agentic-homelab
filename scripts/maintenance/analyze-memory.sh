#!/bin/bash
#
# Memory Usage Analyzer
# Analyzes collected memory usage data
#
# Usage:
#   bash maintenance/analyze-memory.sh [days]
#   bash maintenance/analyze-memory.sh 7    # Last 7 days
#   bash maintenance/analyze-memory.sh 30   # Last 30 days (default)
#

set -euo pipefail

LOG_FILE="/var/log/qacey/memory-usage.log"
DAYS=${1:-30}

if [[ ! -f "$LOG_FILE" ]]; then
    echo "No memory usage data found at $LOG_FILE"
    echo "Run monitor-memory.sh first to collect data"
    exit 1
fi

echo "========================================"
echo "  Memory Usage Analysis (Last $DAYS days)"
echo "========================================"
echo ""

# Calculate date threshold
THRESHOLD=$(date -d "$DAYS days ago" '+%Y-%m-%d')

# Analyze each container
echo "Container Statistics:"
echo "--------------------"
echo ""

tail -n +2 "$LOG_FILE" | awk -F',' -v threshold="$THRESHOLD" '
$1 >= threshold {
    container = $2
    mem_used = $3
    mem_limit = $4
    mem_perc = $5
    
    # Track stats per container
    sum[container] += mem_used
    max_used[container] = (mem_used > max_used[container]) ? mem_used : max_used[container]
    min_used[container] = (min_used[container] == 0 || mem_used < min_used[container]) ? mem_used : min_used[container]
    limit[container] = mem_limit
    count[container]++
}
END {
    for (c in sum) {
        avg = sum[c] / count[c]
        avg_util = (avg / limit[c]) * 100
        peak_util = (max_used[c] / limit[c]) * 100
        printf "%-30s | Avg: %6.0f MB | Peak: %6.0f MB | Limit: %6.0f MB | Avg: %5.1f%% | Peak: %5.1f%%\n", 
               c, avg, max_used[c], limit[c], avg_util, peak_util
    }
}' | sort -t'|' -k5 -rn

echo ""
echo "========================================"
echo "  Recommendations"
echo "========================================"
echo ""

# Find containers hitting their limits (peak > 90%)
echo "⚠️  CRITICAL - Hitting memory limits (peak > 90%):"
tail -n +2 "$LOG_FILE" | awk -F',' -v threshold="$THRESHOLD" '
$1 >= threshold {
    container = $2
    mem_used = $3
    mem_limit = $4
    
    max_used[container] = (mem_used > max_used[container]) ? mem_used : max_used[container]
    limit[container] = mem_limit
    count[container]++
}
END {
    found = 0
    for (c in max_used) {
        peak_util = (max_used[c] / limit[c]) * 100
        if (peak_util > 90) {
            found = 1
            recommended = max_used[c] * 1.3
            increase = recommended - limit[c]
            printf "  %-30s | Current: %4.0f MB | Peak: %4.0f MB (%.1f%%) | Recommended: %4.0f MB | Add: %4.0f MB\n", 
                   c, limit[c], max_used[c], peak_util, recommended, increase
        }
    }
    if (found == 0) {
        print "  None - all containers have headroom"
    }
}' | sort -t'|' -k3 -rn

echo ""
echo "Under-allocated (peak > 80% of limit):"
tail -n +2 "$LOG_FILE" | awk -F',' -v threshold="$THRESHOLD" '
$1 >= threshold {
    container = $2
    mem_used = $3
    mem_limit = $4
    
    max_used[container] = (mem_used > max_used[container]) ? mem_used : max_used[container]
    limit[container] = mem_limit
    count[container]++
}
END {
    found = 0
    for (c in max_used) {
        peak_util = (max_used[c] / limit[c]) * 100
        if (peak_util > 80 && peak_util <= 90) {
            found = 1
            recommended = max_used[c] * 1.25
            increase = recommended - limit[c]
            printf "  %-30s | Current: %4.0f MB | Peak: %4.0f MB (%.1f%%) | Recommended: %4.0f MB | Add: %4.0f MB\n", 
                   c, limit[c], max_used[c], peak_util, recommended, increase
        }
    }
    if (found == 0) {
        print "  None"
    }
}' | sort -t'|' -k3 -rn

echo ""
echo "Over-allocated (avg < 40% AND peak < 60%):"
tail -n +2 "$LOG_FILE" | awk -F',' -v threshold="$THRESHOLD" '
$1 >= threshold {
    container = $2
    mem_used = $3
    mem_limit = $4
    
    sum[container] += mem_used
    max_used[container] = (mem_used > max_used[container]) ? mem_used : max_used[container]
    limit[container] = mem_limit
    count[container]++
}
END {
    found = 0
    for (c in sum) {
        avg = sum[c] / count[c]
        avg_util = (avg / limit[c]) * 100
        peak_util = (max_used[c] / limit[c]) * 100
        if (avg_util < 40 && peak_util < 60) {
            found = 1
            # Recommend peak * 1.5 for headroom
            recommended = max_used[c] * 1.5
            savings = limit[c] - recommended
            printf "  %-30s | Current: %4.0f MB | Peak: %4.0f MB (%.1f%%) | Recommended: %4.0f MB | Save: %4.0f MB\n", 
                   c, limit[c], max_used[c], peak_util, recommended, savings
        }
    }
    if (found == 0) {
        print "  None - all containers are reasonably sized"
    }
}' | sort -t'|' -k5 -rn

echo ""
echo "Data points analyzed: $(tail -n +2 "$LOG_FILE" | awk -F',' -v threshold="$THRESHOLD" '$1 >= threshold' | wc -l)"
echo "Collection period: $THRESHOLD to $(date '+%Y-%m-%d')"
