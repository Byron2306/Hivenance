import os
import json
import subprocess
from typing import Any, Dict, Optional

from agents.hummingbot_strategy_v2 import HummingbotStrategyV2Catalog


class PublicBotBridge:
    """Registry for external public trading bots used as sidecars.

    This intentionally does not import GPL/large bot internals. Hivenance can use
    these systems through process/API/Docker boundaries while keeping its own
    strategy and wallet safety code independent.
    """

    DEFAULT_REPOS = {
        "freqtrade": {
            "license": "GPL-3.0",
            "mode": "sidecar_only",
            "strengths": ["backtesting", "hyperopt", "pairlists", "protections", "dry_run"],
            "safe_use": "Run as an external service/process and ingest reports or signals.",
        },
        "hummingbot": {
            "license": "Apache-2.0",
            "mode": "adapter_or_sidecar",
            "strengths": ["connectors", "controllers", "executors", "market_making", "gateway"],
            "safe_use": "Prefer sidecar first; small Apache-licensed adapter ideas can be clean-roomed later.",
        },
        "jesse": {
            "license": "MIT",
            "mode": "adapter_or_sidecar",
            "strengths": ["backtesting", "strategy_research", "metrics", "paper_live_modes"],
            "safe_use": "Use as external research/backtest runner; import only if dependencies are isolated.",
        },
        "jesse-example-strategies": {
            "license": "MIT",
            "mode": "reference_strategies",
            "strengths": ["example_strategies", "indicator_patterns"],
            "safe_use": "Reference examples; port ideas cleanly into Hivenance workers.",
        },
        "octobot": {
            "license": "GPL-3.0",
            "mode": "sidecar_only",
            "strengths": ["automation", "strategy_profiles", "social/trading integrations", "ui"],
            "safe_use": "Run as an external service/process and ingest reports or signals.",
        },
    }

    def __init__(self, cfg: Any, root: Optional[str] = None):
        self.cfg = cfg
        self.root = root or getattr(cfg, "public_bot_repo_root", "external/public-bots")

    def status(self) -> Dict[str, Any]:
        repos = {}
        manifest = self._manifest()
        for name, meta in self.DEFAULT_REPOS.items():
            path = os.path.join(self.root, name)
            pinned = (manifest.get("repos") or {}).get(name) or {}
            implementation_paths = self._implementation_paths(name)
            repos[name] = {
                **meta,
                "path": path,
                "present": os.path.isdir(os.path.join(path, ".git")),
                "commit": pinned.get("commit") or self._git(path, ["rev-parse", "--short", "HEAD"]),
                "subject": pinned.get("subject"),
                "remote": pinned.get("remote") or self._git(path, ["config", "--get", "remote.origin.url"]),
                "docker_compose": os.path.exists(os.path.join(path, "docker-compose.yml")),
                "dockerfile": os.path.exists(os.path.join(path, "Dockerfile")),
                "implementation_paths": implementation_paths,
                "implementation_present": {
                    rel: os.path.exists(os.path.join(path, rel)) for rel in implementation_paths
                },
            }
        return {
            "enabled": bool(getattr(self.cfg, "public_bot_integrations_enabled", True)),
            "local_implementations_enabled": bool(getattr(self.cfg, "local_crypto_bot_implementations_enabled", True)),
            "repo_root": self.root,
            "policy": {
                "do_not_import_gpl": True,
                "sidecar_boundary_for_gpl": ["freqtrade", "octobot"],
                "wallet_authority": "hivenance_only",
                "live_execution": "disabled_until_explicit_executor",
            },
            "repos": repos,
            "hummingbot_strategy_v2": HummingbotStrategyV2Catalog(self.cfg, root=self.root).status(),
            "recommended_next": [
                "Use Freqtrade sidecar for backtest/hyperopt reports.",
                "Use Hummingbot sidecar concepts for executor lifecycle and connectors.",
                "Use Jesse sidecar for strategy research metrics.",
                "Keep MAGIC/BEAM watch-only until Arbitrum/BNB executors exist.",
            ],
        }

    def _implementation_paths(self, name: str) -> list:
        return {
            "freqtrade": ["freqtrade/plugins", "freqtrade/optimize", "freqtrade/templates", "config_examples"],
            "hummingbot": ["controllers", "hummingbot/connector", "hummingbot/strategy_v2", "hummingbot/core"],
            "jesse": ["jesse", "docs-perf"],
            "jesse-example-strategies": ["RSI2", "SMACrossover", "MACD_EMA", "Donchian", "KDJstrategy"],
            "octobot": ["octobot", "packages", "docs"],
        }.get(name, [])

    def sidecar_commands(self) -> Dict[str, Any]:
        root = self.root
        return {
            "freqtrade": {
                "dry_run_backtest": f"docker compose -f {root}/freqtrade/docker-compose.yml run --rm freqtrade backtesting",
                "notes": "Configure a separate freqtrade user_data dir; do not share wallet keys.",
            },
            "hummingbot": {
                "start": f"docker compose -f {root}/hummingbot/docker-compose.yml up",
                "notes": "Use as a separate connector/executor sidecar; Hivenance remains wallet authority.",
            },
            "jesse": {
                "research": f"cd {root}/jesse && python -m jesse",
                "notes": "Best used in isolated virtualenv/container for strategy research.",
            },
            "octobot": {
                "start": f"docker compose -f {root}/octobot/docker-compose.yml up",
                "notes": "GPL sidecar only; ingest exported metrics/signals.",
            },
        }

    def _manifest(self) -> Dict[str, Any]:
        path = os.path.join(self.root, "manifest.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _git(self, path: str, args: list) -> Optional[str]:
        if not os.path.isdir(os.path.join(path, ".git")):
            return None
        try:
            out = subprocess.check_output(["git", "-C", path] + args, stderr=subprocess.DEVNULL, timeout=5)
            return out.decode("utf-8", errors="replace").strip() or None
        except Exception:
            return None
