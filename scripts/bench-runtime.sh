#!/usr/bin/env bash
# Compare live process CPU and RAM on Raspberry Pi OS without extra dependencies.
# Usage: bash scripts/bench-runtime.sh rust 30 [PIDs...]
#        bash scripts/bench-runtime.sh python 30 [PIDs...]
set -euo pipefail

if [[ $# -lt 2 || ! "$2" =~ ^[0-9]+$ || "$2" -lt 3 || "$2" -gt 600 ]]; then
    echo "Usage: $0 {rust|python} {seconds:3..600} [PID ...]" >&2
    exit 2
fi
label=$1
seconds=$2
shift 2

if (( $# > 0 )); then
    pids=("$@")
else
    case "$label" in
        rust)
            mapfile -t pids < <(pgrep -x vinylpi64 || true)
            ;;
        python)
            # Include the web process and recognizer subprocess when they
            # were launched through the usual Python entry points.
            mapfile -t pids < <(ps -eo pid=,args= | awk '
                ($2 ~ /python([0-9.]*)?$/ || $2 ~ /\/python([0-9.]*)?$/ || $2 ~ /gunicorn$/) && /vinylpi/ { print $1 }
            ')
            ;;
        *)
            echo "Unknown runtime '$label'; supply rust or python." >&2
            exit 2
            ;;
    esac
fi
if (( ${#pids[@]} == 0 )); then
    echo "No $label process found. Use 'ps -ef | grep -E "vinylpi|python"' and pass its PID explicitly." >&2
    exit 1
fi
for pid in "${pids[@]}"; do
    [[ "$pid" =~ ^[0-9]+$ && -r "/proc/$pid/stat" ]] || {
        echo "Invalid or inaccessible PID: $pid" >&2
        exit 1
    }
done

hertz=$(getconf CLK_TCK)
read_ticks() {
    local pid stat rest
    local sum=0
    local -a f
    for pid in "${pids[@]}"; do
        [[ -r "/proc/$pid/stat" ]] || continue
        stat=$(<"/proc/$pid/stat")
        rest=${stat##*) }
        read -r -a f <<< "$rest"
        sum=$((sum + f[11] + f[12]))
    done
    printf '%s\n' "$sum"
}
read_memory() {
    local pid rss pss
    local total_rss=0 total_pss=0
    for pid in "${pids[@]}"; do
        [[ -r "/proc/$pid/status" ]] || continue
        rss=$(awk '/^VmRSS:/ { print $2; exit }' "/proc/$pid/status")
        total_rss=$((total_rss + ${rss:-0}))
        if [[ -r "/proc/$pid/smaps_rollup" ]]; then
            pss=$(awk '/^Pss:/ { print $2; exit }' "/proc/$pid/smaps_rollup" 2>/dev/null || true)
            total_pss=$((total_pss + ${pss:-0}))
        fi
    done
    printf '%s %s\n' "$total_rss" "$total_pss"
}

printf 'Runtime: %s | PIDs: %s | Duration: %s s\n' "$label" "${pids[*]}" "$seconds"
printf 'Keep the workload, record, Pixoo mode and Wi-Fi conditions identical across runs.\n'
start_ticks=$(read_ticks)
start_ns=$(date +%s%N)
max_rss=0
sum_rss=0
sum_pss=0
samples=0
for ((i=0; i<seconds; i++)); do
    read -r rss pss < <(read_memory)
    (( rss > max_rss )) && max_rss=$rss
    sum_rss=$((sum_rss + rss))
    sum_pss=$((sum_pss + pss))
    samples=$((samples + 1))
    sleep 1
done
end_ns=$(date +%s%N)
end_ticks=$(read_ticks)
awk -v a="$start_ticks" -v b="$end_ticks" -v hz="$hertz" \
    -v elapsed_ns="$((end_ns - start_ns))" -v n="$samples" \
    -v rss="$sum_rss" -v maxrss="$max_rss" -v pss="$sum_pss" '
BEGIN {
    elapsed = elapsed_ns / 1000000000.0
    printf "Average CPU usage: %.1f%% of one core (100%% = 1 fully utilized core)\n", 100*(b-a)/hz/elapsed
    printf "Mean RSS: %.1f MiB | Sampled peak RSS: %.1f MiB\n", rss/n/1024, maxrss/1024
    if (pss > 0) printf "Mean PSS (shared-memory-adjusted): %.1f MiB\n", pss/n/1024
    printf "Elapsed: %.1f seconds\n", elapsed
}'
