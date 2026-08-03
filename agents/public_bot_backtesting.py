import csv
import json
import os
import time
import uuid
from typing import Any, Dict, Optional


class PublicBotBacktestBridge:
    """Export/ingest bridge for public-bot sidecar research.

    Hivenance does not import Freqtrade/Jesse runtimes here. It writes neutral
    CSV/JSON artifacts for sidecars and stores returned metrics for weighting.
    """

    ENGINES = {"freqtrade", "hummingbot", "jesse", "hivenance_replay"}

    def __init__(self, cfg: Any, coordinator: Optional[Any] = None):
        self.cfg = cfg
        self.coordinator = coordinator
        self.root = os.path.abspath(getattr(cfg, "public_bot_backtest_dir", "data/public_bot_backtests") or "data/public_bot_backtests")
        os.makedirs(self.root, exist_ok=True)

    def status(self) -> Dict[str, Any]:
        return {
            "name": "PUBLIC_BOT_BACKTEST_BRIDGE",
            "enabled": True,
            "mode": "export_ingest_sidecar",
            "root": self.root,
            "engines": sorted(self.ENGINES),
            "runs": self.list_runs(limit=25),
        }

    def export(self, engine: str = "freqtrade", symbol: Optional[str] = None, days: int = 30) -> Dict[str, Any]:
        engine = self._engine(engine)
        ds = self._ds()
        if not ds:
            return {"ok": False, "error": "data_store_unavailable"}
        run_id = f"{engine}-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        run_dir = os.path.join(self.root, run_id)
        os.makedirs(run_dir, exist_ok=True)

        market_rows = ds.market_bee_history(symbol or "", days=int(days or 30)) if hasattr(ds, "market_bee_history") else []
        proposals = []
        try:
            proposals = list(getattr(self.coordinator, "_last_worker_proposals", None) or [])
        except Exception:
            proposals = []

        candle_path = os.path.join(run_dir, "candles.csv")
        proposal_path = os.path.join(run_dir, "proposals.json")
        manifest_path = os.path.join(run_dir, "manifest.json")
        self._write_candles(candle_path, market_rows)
        with open(proposal_path, "w", encoding="utf-8") as f:
            json.dump(proposals, f, indent=2, sort_keys=True)
        payload = {
            "ok": True,
            "run_id": run_id,
            "engine": engine,
            "symbol": symbol,
            "days": int(days or 30),
            "status": "EXPORTED",
            "export_path": run_dir,
            "files": {
                "candles_csv": candle_path,
                "proposals_json": proposal_path,
                "manifest_json": manifest_path,
            },
            "rows": len(market_rows),
            "proposals": len(proposals),
            "created_ts": time.time(),
            "updated_ts": time.time(),
            "sidecar_hint": self._sidecar_hint(engine, run_dir),
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        self._persist(run_id, payload)
        self._share("buzz.public_bot.backtest.export", payload)
        return payload

    def ingest(self, run_id: str, metrics: Optional[Dict[str, Any]] = None, metrics_path: Optional[str] = None) -> Dict[str, Any]:
        if not run_id:
            return {"ok": False, "error": "run_id_required"}
        metrics = dict(metrics or {})
        if metrics_path:
            try:
                with open(metrics_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    metrics.update(loaded)
            except Exception as e:
                return {"ok": False, "run_id": run_id, "error": f"metrics_read_error:{e}"}
        existing = (self.list_runs(run_id=run_id) or {}).get(run_id) or {}
        payload = dict(existing)
        payload.update({
            "ok": True,
            "run_id": run_id,
            "engine": payload.get("engine") or metrics.get("engine") or "unknown",
            "symbol": payload.get("symbol") or metrics.get("symbol"),
            "status": "INGESTED",
            "metrics": metrics,
            "updated_ts": time.time(),
        })
        payload.setdefault("created_ts", time.time())
        self._persist(run_id, payload)
        try:
            if self.coordinator and hasattr(self.coordinator, "apply_public_bot_backtest_metrics"):
                payload["worker_updates"] = self.coordinator.apply_public_bot_backtest_metrics(payload)
        except Exception:
            payload["worker_updates"] = {"ok": False, "error": "worker_metric_apply_failed"}
        self._persist(run_id, payload)
        self._share("buzz.public_bot.backtest.ingest", payload)
        return payload

    def list_runs(self, run_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        ds = self._ds()
        if ds and hasattr(ds, "get_public_bot_backtests"):
            return ds.get_public_bot_backtests(run_id=run_id, limit=limit)
        return {}

    def _write_candles(self, path: str, rows: list) -> None:
        fields = ["timestamp", "symbol", "open", "high", "low", "close", "volume", "source", "raw_score"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for rec in rows:
                price = self._float(rec.get("price_usd"))
                volume = self._float(rec.get("volume_24h_usd"))
                ts = self._float(rec.get("ts"))
                writer.writerow({
                    "timestamp": int(ts * 1000) if ts < 10_000_000_000 else int(ts),
                    "symbol": rec.get("symbol"),
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": volume,
                    "source": "hivenance_market_bee",
                    "raw_score": rec.get("score"),
                })

    def _sidecar_hint(self, engine: str, run_dir: str) -> str:
        if engine == "freqtrade":
            return f"Import {os.path.join(run_dir, 'candles.csv')} as OHLCV, run sidecar backtest, write metrics.json, then POST /public_bot/backtest/ingest.json."
        if engine == "jesse":
            return f"Use {os.path.join(run_dir, 'candles.csv')} with Jesse research/backtest sidecar and return metrics.json."
        if engine == "hummingbot":
            return f"Use {os.path.join(run_dir, 'candles.csv')} with Hummingbot backtesting/replay tooling and return metrics.json."
        return "Use exported files with any sidecar runner and ingest metrics JSON."

    def _persist(self, run_id: str, payload: Dict[str, Any]) -> None:
        ds = self._ds()
        if ds and hasattr(ds, "upsert_public_bot_backtest"):
            ds.upsert_public_bot_backtest(run_id, payload)

    def _share(self, typ: str, payload: Dict[str, Any]) -> None:
        try:
            if self.coordinator:
                self.coordinator.share_data(typ, {
                    "buzz": {"type": typ, "source": "PUBLIC_BOT_BACKTEST", "ts": int(time.time() * 1000)},
                    "payload": payload,
                })
        except Exception:
            pass

    def _engine(self, engine: str) -> str:
        engine = str(engine or "freqtrade").lower()
        return engine if engine in self.ENGINES else "freqtrade"

    def _ds(self):
        try:
            return self.coordinator.agents.get("data_store") if self.coordinator else None
        except Exception:
            return None

    def _float(self, value: Any) -> float:
        try:
            return float(value or 0.0)
        except Exception:
            return 0.0
