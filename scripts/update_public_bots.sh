#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-external/public-bots}"

repos=(
  "freqtrade:https://github.com/freqtrade/freqtrade.git"
  "hummingbot:https://github.com/hummingbot/hummingbot.git"
  "jesse:https://github.com/jesse-ai/jesse.git"
  "jesse-example-strategies:https://github.com/jesse-ai/example-strategies.git"
  "octobot:https://github.com/Drakkar-Software/OctoBot.git"
)

set_sparse_paths() {
  local name="$1"
  local path="$2"
  case "$name" in
    freqtrade)
      git -C "$path" sparse-checkout set \
        config_examples docker freqtrade/optimize freqtrade/plugins freqtrade/templates user_data
      ;;
    hummingbot)
      git -C "$path" sparse-checkout set \
        conf controllers hummingbot/client/config hummingbot/connector hummingbot/core hummingbot/strategy hummingbot/strategy_v2 scripts
      ;;
    jesse)
      git -C "$path" sparse-checkout set \
        docs-perf jesse tests utils
      ;;
    jesse-example-strategies)
      git -C "$path" sparse-checkout set \
        DUAL_THRUST Donchian IFR2 KDJstrategy MACD_EMA MAGen RSI2 SMACrossover SimpleBollinger TradingView_RSI TurtleRules
      ;;
    octobot)
      git -C "$path" sparse-checkout set \
        docker docs octobot packages
      ;;
  esac
}

mkdir -p "$ROOT"
for spec in "${repos[@]}"; do
  name="${spec%%:*}"
  url="${spec#*:}"
  path="$ROOT/$name"
  if [[ ! -d "$path/.git" ]]; then
    git clone --depth 1 --filter=blob:none --sparse "$url" "$path"
  else
    git -C "$path" fetch --depth 1 origin
    branch="$(git -C "$path" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')"
    if [[ -z "$branch" ]]; then
      branch="main"
    fi
    git -C "$path" reset --hard "origin/$branch"
  fi
  set_sparse_paths "$name" "$path"
done

manifest="$ROOT/manifest.json"
printf '{\n  "repos": {\n' > "$manifest"
first=1
for dir in "$ROOT"/*; do
  [[ -d "$dir/.git" ]] || continue
  name="$(basename "$dir")"
  commit="$(git -C "$dir" rev-parse --short HEAD)"
  subject="$(git -C "$dir" log -1 --format='%s' | sed 's/\\/\\\\/g; s/"/\\"/g')"
  remote="$(git -C "$dir" config --get remote.origin.url | sed 's/\\/\\\\/g; s/"/\\"/g')"
  if [[ "$first" -eq 0 ]]; then
    printf ',\n' >> "$manifest"
  fi
  first=0
  printf '    "%s": {"commit": "%s", "subject": "%s", "remote": "%s"}' "$name" "$commit" "$subject" "$remote" >> "$manifest"
  printf "%s " "$dir"
  git -C "$dir" log -1 --format='%h %s'
done
printf '\n  }\n}\n' >> "$manifest"
