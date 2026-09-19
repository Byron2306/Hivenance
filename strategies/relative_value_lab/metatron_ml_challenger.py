from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from statistics import fmean, pstdev
from typing import Any, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


@dataclass(frozen=True)
class MLChallenge:
    anomaly_score: float
    regime: str
    confidence: float
    reason: str
    authority: str = RELATIVE_VALUE_AUTHORITY
    research_only: bool = True
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LightweightIsolationForest:
    """Metatron-inspired dependency-light anomaly model, deterministic when seeded."""

    def __init__(self, *, n_trees: int = 48, sample_size: int = 128, seed: int = 2306):
        self.n_trees = int(n_trees)
        self.sample_size = int(sample_size)
        self.rng = random.Random(seed)
        self.trees: list[dict[str, Any]] = []

    def fit(self, rows: Sequence[Sequence[float]]) -> None:
        data = [list(map(float, row)) for row in rows]
        if len(data) < 4:
            raise ValueError("ml_challenger_insufficient_training_rows")
        self.trees = []
        height = max(1, int(math.ceil(math.log2(min(self.sample_size, len(data))))))
        for _ in range(self.n_trees):
            sample = self.rng.sample(data, min(self.sample_size, len(data)))
            self.trees.append(self._tree(sample, 0, height))

    def _tree(self, rows: list[list[float]], depth: int, max_depth: int) -> dict[str, Any]:
        if depth >= max_depth or len(rows) <= 1:
            return {"leaf": True, "n": len(rows)}
        j = self.rng.randrange(len(rows[0]))
        vals = [r[j] for r in rows]
        lo, hi = min(vals), max(vals)
        if lo == hi:
            return {"leaf": True, "n": len(rows)}
        split = self.rng.uniform(lo, hi)
        left = [r for r in rows if r[j] < split]
        right = [r for r in rows if r[j] >= split]
        return {"leaf": False, "j": j, "split": split,
                "left": self._tree(left, depth + 1, max_depth),
                "right": self._tree(right, depth + 1, max_depth)}

    def _path(self, row: Sequence[float], tree: dict[str, Any], depth: int = 0) -> float:
        if tree["leaf"]:
            n = tree["n"]
            if n <= 1:
                return float(depth)
            c = 2 * (math.log(n - 1) + 0.5772156649) - 2 * (n - 1) / n
            return depth + c
        child = tree["left"] if row[tree["j"]] < tree["split"] else tree["right"]
        return self._path(row, child, depth + 1)

    def score(self, row: Sequence[float]) -> float:
        if not self.trees:
            raise RuntimeError("ml_challenger_not_fitted")
        avg = fmean(self._path(row, t) for t in self.trees)
        n = max(2, self.sample_size)
        c = 2 * (math.log(n - 1) + 0.5772156649) - 2 * (n - 1) / n
        return max(0.0, min(1.0, 2 ** (-avg / c)))


class MetatronMLChallenger:
    """Research-only challenger. ML can dissent; it cannot create authority or edge."""

    version = "hivenance.metatron_ml_challenger.v1"

    def __init__(self, *, seed: int = 2306):
        self.model = LightweightIsolationForest(seed=seed)
        self.means: list[float] = []
        self.stds: list[float] = []

    def fit(self, rows: Sequence[Sequence[float]]) -> None:
        data = [list(map(float, row)) for row in rows]
        if not data:
            raise ValueError("ml_challenger_empty_training_set")
        width = len(data[0])
        if any(len(r) != width for r in data):
            raise ValueError("ml_challenger_ragged_features")
        self.means = [fmean(r[j] for r in data) for j in range(width)]
        self.stds = [max(1e-9, pstdev([r[j] for r in data])) for j in range(width)]
        normalized = [self._normalize(r) for r in data]
        self.model.fit(normalized)

    def _normalize(self, row: Sequence[float]) -> list[float]:
        if len(row) != len(self.means):
            raise ValueError("ml_challenger_feature_width_changed")
        return [(float(x) - m) / s for x, m, s in zip(row, self.means, self.stds)]

    def challenge(self, row: Sequence[float]) -> MLChallenge:
        score = self.model.score(self._normalize(row))
        if score >= 0.68:
            regime = "NOVEL_STATE"
            reason = "feature constellation is far from the fitted historical state distribution"
        elif score >= 0.58:
            regime = "UNUSUAL_STATE"
            reason = "feature constellation is moderately unusual"
        else:
            regime = "FAMILIAR_STATE"
            reason = "feature constellation resembles fitted historical states"
        confidence = min(1.0, abs(score - 0.5) * 2.0)
        return MLChallenge(score, regime, confidence, reason)
