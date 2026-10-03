import time
import requests
from typing import Any, Dict, List, Optional, Tuple


class DexMarginOracle:
    """Read-only DEX route and pool quality oracle for curated on-chain tokens."""

    CHAIN_SLUGS = {
        1: "ethereum",
        10: "optimism",
        56: "bsc",
        137: "polygon",
        8453: "base",
        42161: "arbitrum",
    }

    STABLES = {"USD", "USDC", "USDT", "DAI"}
    NATIVE = {
        1: "ETH",
        10: "ETH",
        8453: "ETH",
        42161: "ETH",
        137: "MATIC",
        56: "BNB",
    }

    def __init__(self, cfg: Any, coordinator: Optional[Any] = None):
        self.cfg = cfg
        self.coordinator = coordinator
        self.chain_id = int(getattr(cfg, "onchain_chain_id", 1) or 1)
        self.chain_slug = self.CHAIN_SLUGS.get(self.chain_id, str(self.chain_id))
        self.api_key = getattr(cfg, "oneinch_api_key", None)
        self.wallet_address = getattr(cfg, "watch_address", None)
        self.timeout = float(getattr(cfg, "dex_oracle_timeout_sec", 8) or 8)
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._quote_backoff: Dict[str, float] = {}
        self._last_good_route: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    def token_universe(self) -> List[Dict[str, Any]]:
        tokens = getattr(self.cfg, "onchain_token_addresses", None) or {}
        out = []
        for sym, info in tokens.items():
            if not sym:
                continue
            if str(sym).upper() in self.STABLES or str(sym).upper() in ("WETH",):
                continue
            if isinstance(info, dict):
                addr = info.get("address") or info.get("addr")
                dec = info.get("decimals")
            else:
                addr = info
                dec = None
            if addr:
                out.append({
                    "symbol": str(sym).upper(),
                    "address": str(addr),
                    "decimals": int(dec) if dec is not None else 18,
                })
        return out

    def analyze_symbol(self, symbol: str, amount_usd: Optional[float] = None) -> Dict[str, Any]:
        base = self._base_symbol(symbol)
        token = self._token_info(base)
        if not token:
            return self._result(symbol, allowed=False, reason="TOKEN_NOT_CONFIGURED")
        return self.analyze_token(token, amount_usd=amount_usd, quote_symbol=self._quote_symbol(symbol))

    def analyze_token(self, token: Dict[str, Any], amount_usd: Optional[float] = None, quote_symbol: str = "USDC") -> Dict[str, Any]:
        amount_usd = float(amount_usd or getattr(self.cfg, "dex_probe_amount_usd", 1.0) or 1.0)
        symbol = f"{str(token.get('symbol')).upper()}/{quote_symbol or 'USD'}"
        cache_key = f"{self.chain_id}:{token.get('address')}:{amount_usd}:{quote_symbol}"
        ttl = float(getattr(self.cfg, "dex_oracle_cache_sec", 45) or 45)
        cached = self._cache.get(cache_key)
        if cached and time.time() - cached[0] < ttl:
            return dict(cached[1])

        pool = self._dexscreener_pool(token.get("address"))
        route = self._roundtrip_quote(token, amount_usd)
        history = self._local_history(symbol)
        contract_risk = self._contract_risk(token, pool, route)
        result = self._score(symbol, token, pool, route, amount_usd, history=history, contract_risk=contract_risk)
        result["readiness"] = self._readiness(result)
        self._cache[cache_key] = (time.time(), dict(result))
        return result

    def exec_quality_for_symbol(self, symbol: str, amount_usd: Optional[float] = None) -> Dict[str, Any]:
        res = self.analyze_symbol(symbol, amount_usd=amount_usd)
        q = res.get("quality") or {}
        return {
            "quote_output_ratio": q.get("roundtrip_ratio"),
            "min_output_ratio": float(getattr(self.cfg, "dex_min_output_ratio", getattr(self.cfg, "onchain_min_output_ratio", 0.90)) or 0.90),
            "price_impact_pct": q.get("price_impact_pct"),
            "gas_drag_pct": q.get("gas_drag_pct"),
            "gas_usd": q.get("gas_usd"),
            "route_liquidity_usd": q.get("liquidity_usd"),
            "liquidity_usd": q.get("liquidity_usd"),
            "dex_net_margin_pct": q.get("net_margin_pct"),
            "dex_exit_allowed": res.get("allowed"),
            "dex_reason": res.get("reason"),
        }

    def market_bee_snapshot(self, top_n: Optional[int] = None, amount_usd: Optional[float] = None) -> Dict[str, Any]:
        """Rank curated tokens across hour/day/week/month pool analytics."""
        top_n = int(top_n or getattr(self.cfg, "market_bee_top_n", 4) or 4)
        quote = str(getattr(self.cfg, "volatility_harvest_quote_asset", "USD") or "USD").upper()
        amount_usd = float(amount_usd or getattr(self.cfg, "dex_probe_amount_usd", 1.0) or 1.0)
        tokens = self.token_universe()
        rows = []
        for token in tokens:
            analysis = self.analyze_token(token, amount_usd=amount_usd, quote_symbol=quote)
            pool = analysis.get("pool") or {}
            quality = analysis.get("quality") or {}
            horizons = self._horizon_snapshot(pool)
            history = analysis.get("history") or {}
            if (history.get("week") or {}).get("price_change_pct") is not None:
                horizons["week"] = {
                    "price_change_pct": (history.get("week") or {}).get("price_change_pct"),
                    "volume_usd": None,
                    "source": "local_history",
                    "samples": (history.get("week") or {}).get("samples"),
                }
            elif horizons.get("week", {}).get("price_change_pct") is None:
                horizons["week"]["source"] = "collecting_local_history"
            if (history.get("month") or {}).get("price_change_pct") is not None:
                horizons["month"] = {
                    "price_change_pct": (history.get("month") or {}).get("price_change_pct"),
                    "volume_usd": None,
                    "source": "local_history",
                    "samples": (history.get("month") or {}).get("samples"),
                }
            elif horizons.get("month", {}).get("price_change_pct") is None:
                horizons["month"]["source"] = "collecting_local_history"
            momentum_score = self._horizon_score(horizons)
            exit_score = 0.0
            rr = quality.get("roundtrip_ratio")
            if rr is not None:
                exit_score = max(0.0, min(1.0, (float(rr) - 0.85) / 0.14))
            liquidity_score = min(
                1.0,
                float(quality.get("liquidity_usd") or 0.0) / max(1.0, float(getattr(self.cfg, "dex_min_liquidity_usd", 50000) or 50000) * 3.0),
            )
            volume_score = min(
                1.0,
                float(quality.get("volume_24h_usd") or 0.0) / max(1.0, float(getattr(self.cfg, "dex_min_volume_24h_usd", 25000) or 25000) * 4.0),
            )
            risk_penalty = 0.0
            if not analysis.get("allowed"):
                risk_penalty += 0.25
            if "TOKEN_TOO_NEW" in str(analysis.get("reason") or ""):
                risk_penalty += 0.20
            score = (
                0.30 * momentum_score
                + 0.25 * exit_score
                + 0.25 * liquidity_score
                + 0.20 * volume_score
                - risk_penalty
            )
            row = {
                "symbol": analysis.get("symbol"),
                "allowed": analysis.get("allowed"),
                "readiness": analysis.get("readiness"),
                "reason": analysis.get("reason"),
                "score": round(max(0.0, min(1.0, score)), 6),
                "horizons": horizons,
                "history": analysis.get("history") or {},
                "contract_risk": analysis.get("contract_risk") or {},
                "quality": quality,
                "pool": pool,
                "components": {
                    "momentum": round(momentum_score, 4),
                    "exit": round(exit_score, 4),
                    "liquidity": round(liquidity_score, 4),
                    "volume": round(volume_score, 4),
                    "risk_penalty": round(risk_penalty, 4),
                },
            }
            rows.append(row)
        ranked = sorted(rows, key=lambda r: r.get("score", 0.0), reverse=True)
        return {
            "ts": int(time.time() * 1000),
            "chain": self.chain_slug,
            "quote_asset": quote,
            "probe_amount_usd": amount_usd,
            "top_n": top_n,
            "top": ranked[:top_n],
            "all": ranked,
        }

    def _score(
        self,
        symbol: str,
        token: Dict[str, Any],
        pool: Dict[str, Any],
        route: Dict[str, Any],
        amount_usd: float,
        history: Optional[Dict[str, Any]] = None,
        contract_risk: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        liquidity = self._float(pool.get("liquidity_usd"))
        volume_24h = self._float(pool.get("volume_24h_usd"))
        txns_24h = int(self._float(pool.get("txns_24h")))
        age_hours = self._float(pool.get("age_hours"))
        price_change_h1 = self._float(pool.get("price_change_h1_pct"))
        price_change_h24 = self._float(pool.get("price_change_h24_pct"))
        roundtrip_ratio = route.get("roundtrip_ratio")
        gas_usd = route.get("gas_usd")

        min_liq = float(getattr(self.cfg, "dex_min_liquidity_usd", 50000) or 0)
        min_vol = float(getattr(self.cfg, "dex_min_volume_24h_usd", 25000) or 0)
        min_txns = int(getattr(self.cfg, "dex_min_txns_24h", 50) or 0)
        min_age = float(getattr(self.cfg, "dex_min_token_age_hours", 24) or 0)
        min_roundtrip = float(getattr(self.cfg, "dex_min_roundtrip_ratio", 0.94) or 0.94)
        max_gas_drag = float(getattr(self.cfg, "dex_max_gas_drag_pct", 0.01) or 0.01)

        gas_drag = (float(gas_usd) / amount_usd) if gas_usd is not None and amount_usd > 0 else None
        price_impact = None
        if roundtrip_ratio is not None:
            price_impact = max(0.0, 1.0 - float(roundtrip_ratio))
        net_margin = None
        if roundtrip_ratio is not None:
            net_margin = float(roundtrip_ratio) - 1.0 - float(gas_drag or 0.0)

        reasons = []
        if pool.get("error"):
            reasons.append("POOL_DATA_UNAVAILABLE")
        if route.get("error"):
            reasons.append("QUOTE_UNAVAILABLE")
        if route.get("stale"):
            reasons.append("QUOTE_STALE")
        if min_liq and liquidity < min_liq:
            reasons.append("LIQUIDITY_THIN")
        if min_vol and volume_24h < min_vol:
            reasons.append("VOLUME_TOO_LOW")
        if min_txns and txns_24h < min_txns:
            reasons.append("TXNS_TOO_LOW")
        if min_age and age_hours >= 0 and age_hours < min_age:
            reasons.append("TOKEN_TOO_NEW")
        if roundtrip_ratio is not None and roundtrip_ratio < min_roundtrip:
            reasons.append("ROUNDTRIP_TOO_EXPENSIVE")
        if gas_drag is not None and gas_drag > max_gas_drag:
            reasons.append("GAS_DRAG_TOO_HIGH")
        contract_risk = contract_risk or {}
        if contract_risk.get("risk_level") == "HIGH":
            reasons.append("CONTRACT_RISK_HIGH")

        volatility_score = min(1.0, (abs(price_change_h1) / 8.0) + (abs(price_change_h24) / 30.0))
        liquidity_score = min(1.0, liquidity / max(1.0, min_liq * 3.0 if min_liq else 150000.0))
        volume_score = min(1.0, volume_24h / max(1.0, min_vol * 4.0 if min_vol else 100000.0))
        exit_score = 0.0
        if roundtrip_ratio is not None:
            exit_score = max(0.0, min(1.0, (float(roundtrip_ratio) - 0.85) / 0.14))
        age_score = min(1.0, max(0.0, age_hours / max(1.0, min_age * 4.0))) if age_hours >= 0 else 0.5
        score = (
            0.25 * volatility_score
            + 0.25 * liquidity_score
            + 0.20 * volume_score
            + 0.20 * exit_score
            + 0.10 * age_score
        )

        allowed = len(reasons) == 0
        return self._result(
            symbol,
            allowed=allowed,
            reason="OK" if allowed else ",".join(reasons),
            token=token,
            pool=pool,
            route=route,
            score=round(max(0.0, min(1.0, score)), 6),
            quality={
                "liquidity_usd": liquidity,
                "volume_24h_usd": volume_24h,
                "txns_24h": txns_24h,
                "age_hours": age_hours,
                "price_change_h1_pct": price_change_h1,
                "price_change_h24_pct": price_change_h24,
                "roundtrip_ratio": roundtrip_ratio,
                "price_impact_pct": price_impact,
                "gas_usd": gas_usd,
                "gas_drag_pct": gas_drag,
                "net_margin_pct": net_margin,
            },
            history=history or {},
            contract_risk=contract_risk,
        )

    def _readiness(self, result: Dict[str, Any]) -> str:
        reason = str(result.get("reason") or "")
        route = result.get("route") or {}
        q = result.get("quality") or {}
        risk = result.get("contract_risk") or {}
        if risk.get("risk_level") == "HIGH":
            return "BLOCKED"
        if "QUOTE_UNAVAILABLE" in reason and not route.get("stale"):
            return "DATA_STALE"
        if "ROUNDTRIP_TOO_EXPENSIVE" in reason or "LIQUIDITY_THIN" in reason:
            return "BLOCKED"
        if route.get("stale"):
            return "WATCH"
        if result.get("allowed") and (q.get("roundtrip_ratio") or 0) >= float(getattr(self.cfg, "dex_ready_roundtrip_ratio", 0.985) or 0.985):
            return "READY"
        if result.get("allowed"):
            return "WATCH"
        return "BLOCKED"

    def _dexscreener_pool(self, token_address: str) -> Dict[str, Any]:
        if not token_address:
            return {"error": "missing token address"}
        url = f"https://api.dexscreener.com/token-pairs/v1/{self.chain_slug}/{token_address}"
        try:
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            pairs = data if isinstance(data, list) else (data.get("pairs") or [])
            best = None
            for p in pairs:
                if str(p.get("chainId") or "").lower() not in (self.chain_slug.lower(), str(self.chain_id)):
                    continue
                liq = self._float(((p.get("liquidity") or {}).get("usd")))
                if best is None or liq > self._float(((best.get("liquidity") or {}).get("usd"))):
                    best = p
            if not best:
                return {"error": "no pool found"}
            created_ms = self._float(best.get("pairCreatedAt"))
            age_hours = -1.0
            if created_ms > 0:
                age_hours = max(0.0, (time.time() * 1000.0 - created_ms) / 3600000.0)
            txns = best.get("txns") or {}
            h24 = txns.get("h24") or {}
            return {
                "dex_id": best.get("dexId"),
                "pair_address": best.get("pairAddress"),
                "url": best.get("url"),
                "liquidity_usd": self._float(((best.get("liquidity") or {}).get("usd"))),
                "volume_24h_usd": self._float(((best.get("volume") or {}).get("h24"))),
                "txns_24h": int(self._float(h24.get("buys")) + self._float(h24.get("sells"))),
                "price_usd": self._float(best.get("priceUsd")),
                "price_change_h1_pct": self._float(((best.get("priceChange") or {}).get("h1"))),
                "price_change_h24_pct": self._float(((best.get("priceChange") or {}).get("h24"))),
                "price_change_h6_pct": self._float(((best.get("priceChange") or {}).get("h6"))),
                "price_change_m5_pct": self._float(((best.get("priceChange") or {}).get("m5"))),
                "volume_m5_usd": self._float(((best.get("volume") or {}).get("m5"))),
                "volume_h1_usd": self._float(((best.get("volume") or {}).get("h1"))),
                "volume_h6_usd": self._float(((best.get("volume") or {}).get("h6"))),
                "fdv": self._float(best.get("fdv")),
                "market_cap": self._float(best.get("marketCap")),
                "age_hours": age_hours,
            }
        except Exception as e:
            return {"error": str(e)}

    def _external_ohlcv_history(self, pool: Dict[str, Any]) -> Dict[str, Any]:
        pair = pool.get("pair_address")
        if not pair:
            return {"source": "geckoterminal", "error": "missing_pair_address"}
        cache_key = f"ohlcv:{self.chain_slug}:{pair}"
        ttl = float(getattr(self.cfg, "market_bee_ohlcv_cache_sec", 1800) or 1800)
        cached = self._cache.get(cache_key)
        if cached and time.time() - cached[0] < ttl:
            return dict(cached[1])
        url = f"https://api.geckoterminal.com/api/v2/networks/{self.chain_slug}/pools/{pair}/ohlcv/day"
        try:
            resp = requests.get(
                url,
                params={"aggregate": 1, "limit": 31, "currency": "usd"},
                timeout=self.timeout,
                headers={"accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            candles = (((data or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
            parsed = []
            for c in candles:
                if len(c) >= 6:
                    parsed.append({
                        "ts": int(c[0]),
                        "open": self._float(c[1]),
                        "high": self._float(c[2]),
                        "low": self._float(c[3]),
                        "close": self._float(c[4]),
                        "volume": self._float(c[5]),
                    })
            parsed = sorted(parsed, key=lambda x: x["ts"])
            if not parsed:
                out = {"source": "geckoterminal", "error": "no_candles"}
            else:
                latest = parsed[-1]["close"]
                def change(days: int) -> Optional[float]:
                    if len(parsed) <= days or latest <= 0:
                        return None
                    old = parsed[-(days + 1)]["close"]
                    if old <= 0:
                        return None
                    return ((latest - old) / old) * 100.0
                def vol(days: int) -> Optional[float]:
                    vals = parsed[-days:] if len(parsed) >= days else parsed
                    if not vals:
                        return None
                    return sum(float(x.get("volume") or 0.0) for x in vals)
                out = {
                    "source": "geckoterminal",
                    "samples": len(parsed),
                    "latest_close": latest,
                    "week": {
                        "price_change_pct": change(7),
                        "volume_usd": vol(7),
                    },
                    "month": {
                        "price_change_pct": change(30),
                        "volume_usd": vol(30),
                    },
                }
            self._cache[cache_key] = (time.time(), dict(out))
            return out
        except Exception as e:
            out = {"source": "geckoterminal", "error": str(e)}
            self._cache[cache_key] = (time.time(), dict(out))
            return out

    def _horizon_snapshot(self, pool: Dict[str, Any]) -> Dict[str, Any]:
        h1 = self._float(pool.get("price_change_h1_pct"))
        h6 = self._float(pool.get("price_change_h6_pct"))
        d1 = self._float(pool.get("price_change_h24_pct"))
        external = self._external_ohlcv_history(pool)
        week = external.get("week") or {}
        month = external.get("month") or {}
        # DexScreener's token-pairs endpoint does not always expose 7d/30d changes.
        # Keep those explicit as None so downstream code can distinguish unavailable
        # data from a real 0% move.
        return {
            "hour": {
                "price_change_pct": h1,
                "volume_usd": self._float(pool.get("volume_h1_usd")),
            },
            "day": {
                "price_change_pct": d1,
                "volume_usd": self._float(pool.get("volume_24h_usd")),
            },
            "week": {
                "price_change_pct": week.get("price_change_pct"),
                "volume_usd": week.get("volume_usd"),
                "source": external.get("source"),
                "samples": external.get("samples"),
                "error": external.get("error"),
            },
            "month": {
                "price_change_pct": month.get("price_change_pct"),
                "volume_usd": month.get("volume_usd"),
                "source": external.get("source"),
                "samples": external.get("samples"),
                "error": external.get("error"),
            },
            "micro": {
                "m5_change_pct": self._float(pool.get("price_change_m5_pct")),
                "h6_change_pct": h6,
                "m5_volume_usd": self._float(pool.get("volume_m5_usd")),
                "h6_volume_usd": self._float(pool.get("volume_h6_usd")),
            },
        }

    def _local_history(self, symbol: str) -> Dict[str, Any]:
        ds = None
        try:
            ds = getattr(self.coordinator, "agents", {}).get("data_store") if self.coordinator else None
        except Exception:
            ds = None
        if not ds or not hasattr(ds, "market_bee_history"):
            return {"week": {"price_change_pct": None, "samples": 0}, "month": {"price_change_pct": None, "samples": 0}}
        rows = ds.market_bee_history(symbol, days=31)
        if not rows:
            return {"week": {"price_change_pct": None, "samples": 0}, "month": {"price_change_pct": None, "samples": 0}}
        latest = rows[-1]
        latest_price = self._float(latest.get("price_usd"))

        def change(days: int) -> Optional[float]:
            cutoff = time.time() - (days * 86400.0)
            prior = None
            for row in rows:
                if self._float(row.get("ts")) <= cutoff:
                    prior = row
                else:
                    break
            if not prior or latest_price <= 0:
                return None
            old = self._float(prior.get("price_usd"))
            if old <= 0:
                return None
            return ((latest_price - old) / old) * 100.0

        return {
            "week": {"price_change_pct": change(7), "samples": len(rows)},
            "month": {"price_change_pct": change(30), "samples": len(rows)},
        }

    def _contract_risk(self, token: Dict[str, Any], pool: Dict[str, Any], route: Dict[str, Any]) -> Dict[str, Any]:
        liquidity = self._float(pool.get("liquidity_usd"))
        fdv = self._float(pool.get("fdv"))
        market_cap = self._float(pool.get("market_cap"))
        age_hours = self._float(pool.get("age_hours"))
        roundtrip = route.get("roundtrip_ratio")
        liq_to_fdv = (liquidity / fdv) if fdv > 0 else None
        liq_to_market_cap = (liquidity / market_cap) if market_cap > 0 else None
        flags = []
        goplus = self._goplus_token_security(token)
        if pool.get("error"):
            flags.append("NO_POOL")
        if route.get("error"):
            flags.append("NO_ROUNDTRIP_QUOTE")
        if age_hours >= 0 and age_hours < float(getattr(self.cfg, "dex_min_token_age_hours", 24) or 24):
            flags.append("NEW_TOKEN")
        if liq_to_fdv is not None and liq_to_fdv < float(getattr(self.cfg, "contract_min_liquidity_to_fdv", 0.002) or 0.002):
            flags.append("LOW_LIQUIDITY_TO_FDV")
        if roundtrip is not None and float(roundtrip) < float(getattr(self.cfg, "dex_min_roundtrip_ratio", 0.94) or 0.94):
            flags.append("BAD_ROUNDTRIP")
        if liquidity <= 0:
            flags.append("ZERO_LIQUIDITY")
        try:
            if goplus:
                if str(goplus.get("is_honeypot", "0")) == "1":
                    flags.append("HONEYPOT")
                if str(goplus.get("is_blacklisted", "0")) == "1":
                    flags.append("BLACKLIST_FUNCTION")
                if str(goplus.get("is_mintable", "0")) == "1":
                    flags.append("MINTABLE")
                if str(goplus.get("is_proxy", "0")) == "1":
                    flags.append("PROXY_CONTRACT")
                sell_tax = self._float(goplus.get("sell_tax"))
                buy_tax = self._float(goplus.get("buy_tax"))
                max_tax = float(getattr(self.cfg, "contract_max_transfer_tax_pct", 0.05) or 0.05)
                if sell_tax > max_tax or buy_tax > max_tax:
                    flags.append("HIGH_TRANSFER_TAX")
                top10 = self._float(goplus.get("top_10_holder_percent"))
                max_top10 = float(getattr(self.cfg, "contract_max_top10_holder_pct", 0.80) or 0.80)
                if top10 > max_top10:
                    flags.append("HOLDER_CONCENTRATION")
        except Exception:
            pass
        unknowns = [
            "holder_concentration",
            "contract_verification",
            "liquidity_lock",
            "transfer_tax",
            "proxy_permissions",
        ]
        severe = {"NO_POOL", "ZERO_LIQUIDITY", "NO_ROUNDTRIP_QUOTE", "HONEYPOT", "BLACKLIST_FUNCTION", "HIGH_TRANSFER_TAX"}
        if any(f in severe for f in flags):
            level = "HIGH"
        elif len(flags) >= 2:
            level = "MEDIUM"
        elif flags:
            level = "LOW"
        else:
            level = "LOW"
        return {
            "token": token.get("symbol"),
            "risk_level": level,
            "flags": flags,
            "unknowns": unknowns,
            "liquidity_to_fdv": liq_to_fdv,
            "liquidity_to_market_cap": liq_to_market_cap,
            "goplus": goplus or {},
            "notes": "Best-effort risk. GoPlus fields are used when available; otherwise unknown fields remain non-blocking.",
        }

    def _goplus_token_security(self, token: Dict[str, Any]) -> Dict[str, Any]:
        if not bool(getattr(self.cfg, "goplus_security_enabled", True)):
            return {}
        addr = token.get("address")
        if not addr:
            return {}
        cache_key = f"goplus:{self.chain_id}:{addr.lower()}"
        ttl = float(getattr(self.cfg, "goplus_cache_sec", 3600) or 3600)
        cached = self._cache.get(cache_key)
        if cached and time.time() - cached[0] < ttl:
            return dict(cached[1])
        try:
            url = f"https://api.gopluslabs.io/api/v1/token_security/{self.chain_id}"
            resp = requests.get(url, params={"contract_addresses": addr}, timeout=self.timeout)
            if not (200 <= resp.status_code < 300):
                return {}
            data = resp.json()
            result = (data.get("result") or {}).get(addr.lower()) or (data.get("result") or {}).get(addr) or {}
            if isinstance(result, dict):
                self._cache[cache_key] = (time.time(), dict(result))
                return result
        except Exception:
            return {}
        return {}

    def _horizon_score(self, horizons: Dict[str, Any]) -> float:
        hour = horizons.get("hour") or {}
        day = horizons.get("day") or {}
        week = horizons.get("week") or {}
        month = horizons.get("month") or {}
        micro = horizons.get("micro") or {}
        h1 = abs(self._float(hour.get("price_change_pct")))
        d1 = abs(self._float(day.get("price_change_pct")))
        w1 = abs(self._float(week.get("price_change_pct")))
        m1 = abs(self._float(month.get("price_change_pct")))
        h6 = abs(self._float(micro.get("h6_change_pct")))
        m5 = abs(self._float(micro.get("m5_change_pct")))
        # Prefer active movement, but do not require all time horizons to exist.
        return max(0.0, min(1.0,
            (0.25 * min(1.0, h1 / 8.0))
            + (0.25 * min(1.0, d1 / 25.0))
            + (0.15 * min(1.0, w1 / 50.0))
            + (0.10 * min(1.0, m1 / 100.0))
            + (0.18 * min(1.0, h6 / 15.0))
            + (0.07 * min(1.0, m5 / 3.0))
        ))

    def _roundtrip_quote(self, token: Dict[str, Any], amount_usd: float) -> Dict[str, Any]:
        quote_token = self._token_info("USDC") or self._token_info("USD")
        if not quote_token:
            return {"error": "USDC token not configured"}
        try:
            route_key = f"roundtrip:{self.chain_id}:{token.get('address')}:{amount_usd}"
            amount_in = int(float(amount_usd) * (10 ** int(quote_token.get("decimals", 6))))
            buy = self._oneinch_quote(quote_token["address"], token["address"], amount_in)
            token_out = self._amount_out(buy)
            buy_gas = self._gas_units(buy)
            if not token_out or token_out <= 0:
                return {"error": "buy quote missing output"}
            sell = self._oneinch_quote(token["address"], quote_token["address"], int(token_out))
            stable_back = self._amount_out(sell)
            sell_gas = self._gas_units(sell)
            if not stable_back or stable_back <= 0:
                return {"error": "sell quote missing output"}
            back_usd = float(stable_back) / (10 ** int(quote_token.get("decimals", 6)))
            gas_usd = self._gas_usd((buy_gas or 0) + (sell_gas or 0))
            out = {
                "buy_dst_amount": token_out,
                "sell_dst_amount": stable_back,
                "roundtrip_ratio": back_usd / max(1e-9, amount_usd),
                "gas_usd": gas_usd,
                "stale": False,
            }
            self._last_good_route[route_key] = (time.time(), dict(out))
            return out
        except Exception as e:
            try:
                route_key = f"roundtrip:{self.chain_id}:{token.get('address')}:{amount_usd}"
                cached = self._last_good_route.get(route_key)
                ttl = float(getattr(self.cfg, "last_good_quote_ttl_sec", 900) or 900)
                if cached and time.time() - cached[0] <= ttl:
                    out = dict(cached[1])
                    out["stale"] = True
                    out["stale_age_sec"] = time.time() - cached[0]
                    out["error"] = str(e)
                    return out
            except Exception:
                pass
            return {"error": str(e)}

    def _oneinch_quote(self, src: str, dst: str, amount: int) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("1inch API key missing")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        urls = [
            (f"https://api.1inch.dev/swap/v6.0/{self.chain_id}/quote", {
                "src": src,
                "dst": dst,
                "amount": str(amount),
            }),
            (f"https://api.1inch.dev/swap/v5.2/{self.chain_id}/quote", {
                "fromTokenAddress": src,
                "toTokenAddress": dst,
                "amount": str(amount),
            }),
        ]
        last = None
        attempts = int(getattr(self.cfg, "quote_retry_attempts", 3) or 3)
        base_sleep = float(getattr(self.cfg, "quote_retry_backoff_sec", 0.6) or 0.6)
        pair_key = f"{self.chain_id}:{src}:{dst}"
        wait_until = float(self._quote_backoff.get(pair_key, 0.0) or 0.0)
        if time.time() < wait_until:
            raise RuntimeError(f"quote backoff active for {pair_key}")
        for attempt in range(max(1, attempts)):
            for url, params in urls:
                try:
                    resp = requests.get(url, params=params, headers=headers, timeout=self.timeout)
                    if 200 <= resp.status_code < 300:
                        self._quote_backoff.pop(pair_key, None)
                        return resp.json()
                    last = f"{resp.status_code}: {resp.text[:240]}"
                    if resp.status_code in (429, 500, 502, 503, 504):
                        continue
                except Exception as e:
                    last = str(e)
            if attempt < attempts - 1:
                time.sleep(base_sleep * (2 ** attempt))
        self._quote_backoff[pair_key] = time.time() + float(getattr(self.cfg, "quote_backoff_cooldown_sec", 30) or 30)
        raise RuntimeError(f"1inch quote failed: {last}")

    def _amount_out(self, quote: Dict[str, Any]) -> Optional[int]:
        for key in ("dstAmount", "toTokenAmount", "toAmount"):
            val = quote.get(key)
            if val is not None:
                try:
                    return int(val)
                except Exception:
                    pass
        return None

    def _gas_units(self, quote: Dict[str, Any]) -> Optional[int]:
        for key in ("gas", "estimatedGas"):
            val = quote.get(key)
            if val is not None:
                try:
                    return int(val)
                except Exception:
                    pass
        return None

    def _gas_usd(self, gas_units: int) -> Optional[float]:
        if not gas_units:
            return None
        try:
            gas_price = None
            exec_agent = None
            if self.coordinator:
                exec_agent = getattr(self.coordinator, "agents", {}).get("execution")
            w3 = getattr(exec_agent, "_w3", None)
            if w3:
                gas_price = int(w3.eth.gas_price)
            if not gas_price:
                return None
            native_price = self._native_price_usd()
            if native_price <= 0:
                return None
            return (float(gas_units) * float(gas_price) / 1e18) * native_price
        except Exception:
            return None

    def _native_price_usd(self) -> float:
        try:
            if self.coordinator and hasattr(self.coordinator, "get_shared_data"):
                v = self.coordinator.get_shared_data("latest_price")
                if v:
                    return float(v)
        except Exception:
            pass
        return 0.0

    def _token_info(self, sym: str) -> Optional[Dict[str, Any]]:
        tokens = getattr(self.cfg, "onchain_token_addresses", None) or {}
        sym_u = str(sym or "").upper()
        info = tokens.get(sym_u)
        if not info and sym_u == "USD":
            info = tokens.get("USDC")
        if not info:
            return None
        if isinstance(info, dict):
            addr = info.get("address") or info.get("addr")
            dec = int(info.get("decimals", 18))
        else:
            addr = info
            dec = 18
        if not addr:
            return None
        return {"symbol": sym_u, "address": str(addr), "decimals": dec}

    def _base_symbol(self, symbol: str) -> str:
        return str(symbol or "").split("/")[0].upper()

    def _quote_symbol(self, symbol: str) -> str:
        parts = str(symbol or "").split("/")
        return parts[1].upper() if len(parts) > 1 else "USDC"

    def _float(self, v: Any) -> float:
        try:
            if v is None:
                return 0.0
            return float(v)
        except Exception:
            return 0.0

    def _result(self, symbol: str, allowed: bool, reason: str, **kwargs) -> Dict[str, Any]:
        out = {
            "symbol": symbol,
            "allowed": bool(allowed),
            "reason": reason,
            "ts": int(time.time() * 1000),
        }
        out.update(kwargs)
        return out
