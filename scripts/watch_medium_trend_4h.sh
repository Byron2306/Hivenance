#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="${HIVENANCE_DB:-$ROOT/data/swarm_data.db}"
LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/medium_trend_4h_monitor.log"
DURATION_SEC="${HIVENANCE_MONITOR_DURATION_SEC:-14400}"
INTERVAL_SEC="${HIVENANCE_MONITOR_INTERVAL_SEC:-300}"

mkdir -p "$LOG_DIR"
cd "$ROOT" || exit 1

query() {
  local title="$1"
  local sql="$2"
  printf '\n[%s]\n' "$title"
  sqlite3 -readonly "$DB" "$sql" 2>&1 || true
}

started="$(date +%s)"
deadline="$((started + DURATION_SEC))"
printf 'Hivenance medium-trend monitor started at %s\n' "$(date -Iseconds)" | tee -a "$LOG_FILE"
printf 'database=%s duration_sec=%s interval_sec=%s\n' "$DB" "$DURATION_SEC" "$INTERVAL_SEC" | tee -a "$LOG_FILE"

while :; do
  now="$(date +%s)"
  remaining="$((deadline - now))"
  {
    printf '\n===== %s remaining=%ss =====\n' "$(date -Iseconds)" "$remaining"
    query "phase2 latest" "SELECT run_id,status,datetime(completed_ts,'unixepoch'),forecasts_total,non_abstain_forecasts FROM hypothesis_runs ORDER BY completed_ts DESC LIMIT 5;"
    query "medium trend forecasts" "SELECT model_id,symbol,horizon_seconds,direction,abstain,datetime(ts,'unixepoch'),datetime(target_ts,'unixepoch'),ROUND(expected_net_bps,3),reason FROM hypothesis_forecasts WHERE model_id='medium_horizon_trend_v1' ORDER BY ts DESC LIMIT 12;"
    query "medium trend counts" "SELECT COUNT(*) AS total, SUM(CASE WHEN abstain=0 THEN 1 ELSE 0 END) AS active, MIN(datetime(target_ts,'unixepoch')), MAX(datetime(target_ts,'unixepoch')) FROM hypothesis_forecasts WHERE model_id='medium_horizon_trend_v1';"
    query "medium trend receipts" "SELECT symbol,horizon_seconds,lookback_seconds,policy,entries,ROUND(mean_net_bps,3),ROUND(lower_bound_net_bps,3),accepted FROM medium_horizon_trend_receipts ORDER BY accepted DESC, lower_bound_net_bps DESC LIMIT 8;"
    query "phase3 latest" "SELECT run_id,status,datetime(completed_ts,'unixepoch'),forecasts_examined,simulations_created,completed,rejected,expired FROM simulation_runs ORDER BY completed_ts DESC LIMIT 5;"
    query "phase4 latest" "SELECT run_id,status,datetime(completed_ts,'unixepoch'),rows_examined,candidate_count,pbo_estimate,champion_key,ready_for_phase5_review FROM phase4_validation_runs ORDER BY completed_ts DESC LIMIT 5;"
    printf '\n[python phase processes]\n'
    ps -o pid,ppid,etime,stat,cmd -C python -C python3 | grep -E "run_research_acceptance|run_phase1|run_phase2|run_phase3|run_phase4|run_medium" || true
  } | tee -a "$LOG_FILE"

  if [ "$remaining" -le 0 ]; then
    printf '\nMonitor completed at %s\n' "$(date -Iseconds)" | tee -a "$LOG_FILE"
    break
  fi
  sleep_for="$INTERVAL_SEC"
  if [ "$remaining" -lt "$sleep_for" ]; then
    sleep_for="$remaining"
  fi
  sleep "$sleep_for"
done
