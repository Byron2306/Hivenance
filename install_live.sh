#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "[install_live] Preparing local live VAMP install in $ROOT_DIR"

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

mkdir -p logs data config

if [[ ! -f .env.live ]]; then
  cat > .env.live <<'ENV'
# Exchange credentials
KRAKEN_API_KEY=
KRAKEN_API_SECRET=
BINANCE_API_KEY=
BINANCE_API_SECRET=

# On-chain / wallet
WEB3_RPC_URL=https://mainnet.base.org
WATCH_ADDRESS=
ERC20_TOKEN_ADDRESS=

# Optional provider keys
ONEINCH_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ENV
  echo "[install_live] Created .env.live template (fill secrets before running live)."
fi

set -a
source .env.live
set +a

python3 - <<'PY'
import json, yaml, pathlib, os
root = pathlib.Path('.')
settings_path = root / 'config' / 'settings.yaml'
live_path = root / 'config' / 'settings.live.yaml'
keys_path = root / 'config' / 'api_keys.json'

settings = yaml.safe_load(settings_path.read_text()) or {}
settings.update({
    'dry_run': False,
    'auto_trade_enabled': True,
    'live_mode': True,
    'ui_enabled': True,
    'network_enabled': False,
    'queen_telegram_confirm_enabled': bool(os.getenv('TELEGRAM_BOT_TOKEN') and os.getenv('TELEGRAM_CHAT_ID')),
})
live_path.write_text(yaml.safe_dump(settings, sort_keys=False))

keys = {}
if keys_path.exists():
    keys = json.loads(keys_path.read_text() or '{}')

def put(k, env):
    v = os.getenv(env, '').strip()
    if v:
        keys[k] = v

put('kraken_api_key', 'KRAKEN_API_KEY')
put('kraken_api_secret', 'KRAKEN_API_SECRET')
put('binance_api_key', 'BINANCE_API_KEY')
put('binance_api_secret', 'BINANCE_API_SECRET')
put('web3_rpc_url', 'WEB3_RPC_URL')
put('watch_address', 'WATCH_ADDRESS')
put('erc20_token_address', 'ERC20_TOKEN_ADDRESS')

keys_path.write_text(json.dumps(keys, indent=2))
print('[install_live] wrote config/settings.live.yaml and updated config/api_keys.json')
PY

echo "[install_live] Running full VAMP validation..."
bash scripts/run_vamp_checks.sh

echo "[install_live] Done. Start live mode with:"
echo "  source .venv/bin/activate"
echo "  export CRYPTSWARM_SETTINGS_PATH=config/settings.live.yaml"
echo "  export CRYPTSWARM_LIVE=1"
echo "  python3 start_vamp.py"
