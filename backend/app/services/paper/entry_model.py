"""Fitted entry model - jointly weight size, implied vol, and history.

The trade-decision journal records per-name features, but the grade itself
lives on closed ``paper_trades`` (realized P&L). This module fits on that
full closed book — not only rows that happened to be journaled going forward:

  1. Every closed paper trade with a P&L is a training example. Decision-journal
     rows overlay richer entry features when they exist; missing history is
     reconstructed from the trade's thesis + live market-cap / ADV.
  2. Fit a regularized logistic regression on size, implied vs realized vol,
     unpacked reaction history, analyst positioning, trend, and days-to-print
     — not just the four factors named at the start. Sparse columns drop out.
  3. Put P(win) *in front of* the existing gates: veto names below
     ``paper_entry_model_min_prob``, and feed the model probability into the
     +EV gate. Heuristic conviction / direction / liquidity filters still run.
  4. Guardrailed like calibration: opt-in, minimum sample *and* class count,
     leave-one-out (or time-split) AUC must beat a coin flip, probabilities
     clamped. Falls back to the calibrated heuristic otherwise.

Recomputed every run from the append-only record (no persisted weights that
can drift). Pure numpy - no sklearn - so it adds no deploy weight.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PaperTrade, TradeDecision
from app.services.paper.calibration import adjust_win_prob
from app.services.paper.decisions import attach_context_features, features_from_paper_trade

logger = logging.getLogger(__name__)

# L2 penalty on standardized weights (intercept is not penalized). Stronger
# than sklearn's default C=1 because the journal is small.
_L2 = 2.0
_PROB_FLOOR = 0.05
_PROB_CEIL = 0.95
# LOOCV is fine up to this; beyond it we switch to a chronological 5-fold.
_LOO_MAX_N = 60

# Numeric transforms. Each maps a feature dict -> float | None.
_NUMERIC: list[tuple[str, str]] = [
    ("log_market_cap", "Market cap (log)"),
    ("log_dollar_volume", "Dollar volume (log ADV$)"),
    ("rel_volume", "Relative volume"),
    ("expected_move_pct", "Implied move %"),
    ("richness", "IV richness"),
    ("seller_edge", "Seller edge"),
    ("realized_vol_20d", "Realized vol (20d)"),
    ("dir_score", "Direction score"),
    ("up_rate", "Historical up-rate"),
    ("last_move_pct", "Last earnings move"),
    ("beat_rate", "Beat rate"),
    ("continuation_rate", "Continuation rate"),
    ("trend_60d", "60-day trend"),
    ("analyst_upside", "Analyst upside"),
    ("analyst_bullish_pct", "Analyst bullish %"),
    ("days_to_event", "Days to print"),
    ("heuristic_win_prob", "Heuristic win prob"),
    ("hist_win_rate", "Historical win rate"),
    ("log_sample", "History sample (log)"),
]

_CATEGORICAL = ("strategy", "direction", "conviction", "earnings_timing")


def _log10(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return math.log10(v)


def _numeric_row(feats: dict) -> dict[str, float | None]:
    sample = feats.get("edge_sample") or feats.get("hist_samples") or 0
    try:
        sample_n = float(sample)
    except (TypeError, ValueError):
        sample_n = 0.0
    seller = _as_float(feats.get("seller_edge"))
    if seller is None:
        exceed = _as_float(feats.get("exceed_rate"))
        if exceed is not None:
            seller = 1.0 - exceed
    return {
        "log_market_cap": _log10(feats.get("market_cap")),
        "log_dollar_volume": _log10(feats.get("dollar_volume")),
        "rel_volume": _as_float(feats.get("rel_volume")),
        "expected_move_pct": _as_float(feats.get("expected_move_pct")),
        "richness": _as_float(feats.get("richness")),
        "seller_edge": seller,
        "realized_vol_20d": _as_float(feats.get("realized_vol_20d")),
        "dir_score": _as_float(feats.get("dir_score")),
        "up_rate": _as_float(feats.get("up_rate")),
        "last_move_pct": _as_float(feats.get("last_move_pct")),
        "beat_rate": _as_float(feats.get("beat_rate")),
        "continuation_rate": _as_float(feats.get("continuation_rate")),
        "trend_60d": _as_float(feats.get("trend_60d")),
        "analyst_upside": _as_float(feats.get("analyst_upside")),
        "analyst_bullish_pct": _as_float(feats.get("analyst_bullish_pct")),
        "days_to_event": _as_float(feats.get("days_to_event")),
        "heuristic_win_prob": _as_float(feats.get("win_prob")),
        "hist_win_rate": _as_float(feats.get("hist_win_rate")),
        "log_sample": math.log10(1.0 + max(sample_n, 0.0)),
    }


def _as_float(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _is_win(row: TradeDecision) -> bool:
    if row.outcome in ("win", "loss"):
        return row.outcome == "win"
    return (row.realized_pnl or 0) > 0


@dataclass
class FittedEntryModel:
    applicable: bool
    n: int = 0
    n_wins: int = 0
    n_losses: int = 0
    cv_auc: float | None = None
    in_sample_auc: float | None = None
    reason: str = ""
    coefficients: list[dict] = field(default_factory=list)
    intercept: float = 0.0
    min_prob: float = 0.45
    # Internal scoring state - omitted from as_dict.
    feature_names: list[str] = field(default_factory=list)
    medians: np.ndarray | None = None
    means: np.ndarray | None = None
    stds: np.ndarray | None = None
    weights: np.ndarray | None = None  # includes intercept as last element
    cat_levels: dict[str, list[str]] = field(default_factory=dict)
    numeric_kept: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "applicable": self.applicable,
            "n": self.n,
            "n_wins": self.n_wins,
            "n_losses": self.n_losses,
            "cv_auc": round(self.cv_auc, 3) if self.cv_auc is not None else None,
            "in_sample_auc": (
                round(self.in_sample_auc, 3) if self.in_sample_auc is not None else None
            ),
            "reason": self.reason,
            "coefficients": self.coefficients,
            "intercept": round(self.intercept, 4),
            "min_prob": self.min_prob,
        }


def _empty(reason: str, settings, n: int = 0, wins: int = 0, losses: int = 0) -> FittedEntryModel:
    min_prob = getattr(settings, "paper_entry_model_min_prob", 0.45)
    return FittedEntryModel(
        applicable=False, n=n, n_wins=wins, n_losses=losses,
        reason=reason, min_prob=min_prob,
    )


def _sigmoid(z: np.ndarray) -> np.ndarray:
    z = np.clip(z, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-z))


def _fit_logreg(X: np.ndarray, y: np.ndarray, l2: float) -> np.ndarray:
    """Newton-IRLS logistic regression. Last column of X is the intercept (1s)
    and is not L2-penalized."""
    n, d = X.shape
    w = np.zeros(d)
    penalty = np.ones(d)
    penalty[-1] = 0.0  # intercept
    eye = np.diag(penalty)
    for _ in range(40):
        p = _sigmoid(X @ w)
        W = np.clip(p * (1.0 - p), 1e-6, None)
        grad = (X.T @ (p - y)) / n + (l2 / n) * (penalty * w)
        hess = (X.T * W) @ X / n + (l2 / n) * eye
        try:
            step = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            break
        w = w - step
        if float(np.max(np.abs(step))) < 1e-6:
            break
    return w


def _auc(y: np.ndarray, p: np.ndarray) -> float | None:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    n_pos = int((y == 1).sum())
    n_neg = int((y == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return None
    order = np.argsort(p)
    ranks = np.empty(len(p), dtype=float)
    ranks[order] = np.arange(1, len(p) + 1)
    # Average ranks of ties so a constant predictor scores 0.5.
    _uniq, inverse, counts = np.unique(p, return_inverse=True, return_counts=True)
    if (counts > 1).any():
        for i, c in enumerate(counts):
            if c > 1:
                idx = np.where(inverse == i)[0]
                ranks[idx] = ranks[idx].mean()
    sum_pos = float(ranks[y == 1].sum())
    return (sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def _cv_auc(X: np.ndarray, y: np.ndarray, dates: list, l2: float) -> float | None:
    n = len(y)
    if n < 8:
        return None
    if n <= _LOO_MAX_N:
        preds = np.zeros(n)
        for i in range(n):
            mask = np.ones(n, dtype=bool)
            mask[i] = False
            ytr = y[mask]
            if ytr.sum() < 1 or (len(ytr) - ytr.sum()) < 1:
                preds[i] = float(y.mean())
                continue
            w = _fit_logreg(X[mask], ytr, l2)
            preds[i] = float(_sigmoid(np.array([X[i] @ w]))[0])
        return _auc(y, preds)

    order = np.argsort([d.toordinal() if hasattr(d, "toordinal") else i for i, d in enumerate(dates)])
    Xs, ys = X[order], y[order]
    fold = max(n // 5, 8)
    preds = np.full(n, np.nan)
    for start in range(fold, n, fold):
        stop = min(start + fold, n)
        ytr = ys[:start]
        if ytr.sum() < 2 or (len(ytr) - ytr.sum()) < 2:
            continue
        w = _fit_logreg(Xs[:start], ytr, l2)
        preds[start:stop] = _sigmoid(Xs[start:stop] @ w)
    mask = np.isfinite(preds)
    if int(mask.sum()) < 10:
        return None
    return _auc(ys[mask], preds[mask])


def _hydrate(db: Session, row: TradeDecision) -> dict:
    feats = {
        "win_prob": row.win_prob,
        "expected_move_pct": row.expected_move_pct,
        "richness": row.richness,
        "seller_edge": row.seller_edge,
        "exceed_rate": row.exceed_rate,
        "dir_score": row.dir_score,
        "hist_win_rate": row.hist_win_rate,
        "hist_samples": row.hist_samples,
        "edge_sample": row.edge_sample,
        "market_cap": row.market_cap,
        "avg_volume": row.avg_volume,
        "dollar_volume": row.dollar_volume,
        "rel_volume": getattr(row, "rel_volume", None),
        "realized_vol_20d": getattr(row, "realized_vol_20d", None),
        "trend_60d": getattr(row, "trend_60d", None),
        "up_rate": getattr(row, "up_rate", None),
        "last_move_pct": getattr(row, "last_move_pct", None),
        "beat_rate": getattr(row, "beat_rate", None),
        "continuation_rate": getattr(row, "continuation_rate", None),
        "analyst_upside": getattr(row, "analyst_upside", None),
        "analyst_bullish_pct": getattr(row, "analyst_bullish_pct", None),
        "days_to_event": getattr(row, "days_to_event", None),
        "earnings_timing": getattr(row, "earnings_timing", None),
        "spot": row.spot,
        "strategy": row.strategy,
        "direction": row.direction,
        "conviction": row.conviction,
        "vol_stance": row.vol_stance,
    }
    if row.features_json:
        try:
            extra = json.loads(row.features_json) or {}
        except (json.JSONDecodeError, TypeError):
            extra = {}
        for k, v in extra.items():
            if feats.get(k) is None and v is not None:
                feats[k] = v
    return attach_context_features(
        db, row.ticker, feats,
        as_of=row.decision_date,
        earnings_date=row.earnings_date,
    )


def _trade_win(t: PaperTrade) -> bool:
    if t.outcome in ("win", "loss"):
        return t.outcome == "win"
    return (t.realized_pnl or 0) > 0


def _trade_when(t: PaperTrade) -> date:
    for ts in (t.opened_at, t.closed_at, t.created_at):
        if ts is not None:
            return ts.date() if hasattr(ts, "date") else ts
    return date.today()


@dataclass
class _Example:
    feats: dict
    y: float
    when: date
    signal_id: str | None = None


def _collect_graded_examples(db: Session) -> list[_Example]:
    """Closed paper trades are the grade; the decision journal overlays features.

    Training must not wait for a live journal row. Every closed fill with a P&L
    is an example. When a matching ``trade_decisions`` row exists, its snapshotted
    features win (they were recorded at entry). Otherwise we reconstruct from the
    trade thesis and hydrate market cap / ADV from the company + price bars.
    Deduped by ``signal_id`` so a backfilled decision doesn't double-count.
    """
    by_id: dict[str, _Example] = {}
    extra: list[_Example] = []

    trades = db.scalars(
        select(PaperTrade).where(
            PaperTrade.status == "closed",
            PaperTrade.realized_pnl.is_not(None),
        )
    ).all()
    for t in trades:
        label, feats = features_from_paper_trade(t)
        as_of = _trade_when(t)
        feats = attach_context_features(
            db, t.ticker, feats, as_of=as_of, earnings_date=t.earnings_date,
        )
        feats["strategy"] = label
        ex = _Example(
            feats=feats, y=1.0 if _trade_win(t) else 0.0,
            when=as_of, signal_id=t.signal_id,
        )
        if t.signal_id:
            by_id[t.signal_id] = ex
        else:
            extra.append(ex)

    rows = db.scalars(
        select(TradeDecision).where(
            TradeDecision.decision == "opened",
            TradeDecision.realized_pnl.is_not(None),
        )
    ).all()
    for row in rows:
        ex = _Example(
            feats=_hydrate(db, row),
            y=1.0 if _is_win(row) else 0.0,
            when=row.decision_date or date.today(),
            signal_id=row.signal_id,
        )
        if row.signal_id:
            by_id[row.signal_id] = ex
        else:
            extra.append(ex)

    return list(by_id.values()) + extra


def _design(
    rows_feats: list[dict],
    *,
    medians: np.ndarray | None = None,
    means: np.ndarray | None = None,
    stds: np.ndarray | None = None,
    cat_levels: dict[str, list[str]] | None = None,
    numeric_kept: list[str] | None = None,
) -> tuple[np.ndarray, dict]:
    """Build the (possibly scaled) design matrix. When fit stats are omitted,
    they are computed from ``rows_feats`` (training). Returns X including a
    trailing intercept column, plus the stats needed to score new rows."""
    numeric_keys = [k for k, _ in _NUMERIC]
    raw = [_numeric_row(f) for f in rows_feats]
    n = len(raw)

    if numeric_kept is None:
        numeric_kept = []
        computed_medians = []
        for key in numeric_keys:
            vals = [r[key] for r in raw if r[key] is not None]
            if len(vals) < max(8, n // 5):
                continue  # too sparse to keep
            numeric_kept.append(key)
            computed_medians.append(float(np.median(vals)))
        medians = np.array(computed_medians, dtype=float) if computed_medians else np.zeros(0)
    else:
        if medians is None:
            medians = np.zeros(len(numeric_kept))

    mat = np.zeros((n, len(numeric_kept)), dtype=float)
    for j, key in enumerate(numeric_kept):
        fill = float(medians[j]) if j < len(medians) else 0.0
        for i, r in enumerate(raw):
            v = r.get(key)
            mat[i, j] = float(v) if v is not None else fill

    if means is None or stds is None:
        means = mat.mean(axis=0) if mat.size else np.zeros(0)
        stds = mat.std(axis=0, ddof=0) if mat.size else np.zeros(0)
        stds = np.where(stds < 1e-8, 1.0, stds)
        # Drop near-constant columns.
        keep_idx = [j for j, s in enumerate(stds) if mat.size and float(np.std(mat[:, j])) >= 1e-8]
        if keep_idx and len(keep_idx) < len(numeric_kept):
            numeric_kept = [numeric_kept[j] for j in keep_idx]
            mat = mat[:, keep_idx]
            medians = medians[keep_idx]
            means = means[keep_idx]
            stds = stds[keep_idx]
            stds = np.where(stds < 1e-8, 1.0, stds)

    scaled = (mat - means) / stds if mat.size else mat

    if cat_levels is None:
        cat_levels = {}
        for cat in _CATEGORICAL:
            levels = sorted({str(f.get(cat) or "unknown") for f in rows_feats})
            # Drop the first level as the baseline so dummies aren't collinear
            # with the intercept.
            cat_levels[cat] = levels[1:] if len(levels) > 1 else []

    dummy_names: list[str] = []
    dummy_blocks: list[np.ndarray] = []
    for cat in _CATEGORICAL:
        levels = cat_levels.get(cat) or []
        block = np.zeros((n, len(levels)), dtype=float)
        for j, level in enumerate(levels):
            dummy_names.append(f"{cat}={level}")
            for i, f in enumerate(rows_feats):
                if str(f.get(cat) or "unknown") == level:
                    block[i, j] = 1.0
        if levels:
            dummy_blocks.append(block)

    parts = [scaled] if scaled.size else []
    parts.extend(dummy_blocks)
    if not parts:
        X_feat = np.zeros((n, 0))
        names: list[str] = []
    else:
        X_feat = np.hstack(parts)
        names = list(numeric_kept) + dummy_names
    intercept = np.ones((n, 1))
    X = np.hstack([X_feat, intercept]) if X_feat.size else intercept
    stats = {
        "numeric_kept": numeric_kept,
        "medians": medians,
        "means": means,
        "stds": stds,
        "cat_levels": cat_levels,
        "feature_names": names,
    }
    return X, stats


def _human(name: str) -> str:
    for key, label in _NUMERIC:
        if name == key:
            return label
    if name.startswith("strategy="):
        return f"Book: {name.split('=', 1)[1].replace('_', ' ')}"
    if name.startswith("direction="):
        return f"Direction: {name.split('=', 1)[1]}"
    if name.startswith("conviction="):
        return f"Conviction: {name.split('=', 1)[1]}"
    if name.startswith("earnings_timing="):
        return f"Timing: {name.split('=', 1)[1]}"
    return name


def fit_entry_model(db: Session, settings) -> FittedEntryModel:
    """Fit (or return a not-applicable stub) from the closed paper book."""
    if not getattr(settings, "paper_entry_model_enabled", False):
        return _empty("disabled", settings)

    min_n = int(getattr(settings, "paper_entry_model_min_samples", 30))
    min_class = int(getattr(settings, "paper_entry_model_min_class", 8))
    min_auc = float(getattr(settings, "paper_entry_model_min_auc", 0.52))
    min_prob = float(getattr(settings, "paper_entry_model_min_prob", 0.45))

    examples = _collect_graded_examples(db)
    n = len(examples)
    wins = sum(1 for e in examples if e.y >= 1.0)
    losses = n - wins
    if n < min_n:
        return _empty(
            f"need {min_n} graded trades (have {n})", settings, n, wins, losses
        )
    if wins < min_class or losses < min_class:
        return _empty(
            f"need {min_class} wins and losses (have {wins}/{losses})",
            settings, n, wins, losses,
        )

    feats = [e.feats for e in examples]
    y = np.array([e.y for e in examples])
    dates = [e.when for e in examples]
    X, stats = _design(feats)
    if X.shape[1] <= 1:
        return _empty("no usable features", settings, n, wins, losses)

    weights = _fit_logreg(X, y, _L2)
    in_p = _sigmoid(X @ weights)
    in_auc = _auc(y, in_p)
    cv_auc = _cv_auc(X, y, dates, _L2)

    coefs = []
    for name, w in zip(stats["feature_names"], weights[:-1]):
        coefs.append({"feature": name, "label": _human(name), "weight": round(float(w), 4)})
    coefs.sort(key=lambda c: abs(c["weight"]), reverse=True)

    reason = ""
    applicable = True
    if cv_auc is None:
        applicable = False
        reason = "could not score out-of-sample"
    elif cv_auc < min_auc:
        applicable = False
        reason = f"CV AUC {cv_auc:.3f} < {min_auc:.2f} (coin-flip floor)"

    model = FittedEntryModel(
        applicable=applicable,
        n=n,
        n_wins=wins,
        n_losses=losses,
        cv_auc=cv_auc,
        in_sample_auc=in_auc,
        reason=reason or ("live" if applicable else ""),
        coefficients=coefs,
        intercept=float(weights[-1]),
        min_prob=min_prob,
        feature_names=stats["feature_names"],
        medians=stats["medians"],
        means=stats["means"],
        stds=stats["stds"],
        weights=weights,
        cat_levels=stats["cat_levels"],
        numeric_kept=stats["numeric_kept"],
    )
    if applicable:
        logger.info(
            "entry-model: live n=%d wins=%d AUC_cv=%.3f AUC_in=%.3f top=%s",
            n, wins, cv_auc or 0.0, in_auc or 0.0,
            ", ".join(f"{c['feature']}={c['weight']:+.2f}" for c in coefs[:4]) or "-",
        )
    else:
        logger.info("entry-model: not applied (%s) n=%d", model.reason, n)
    return model


def predict_win_prob(
    model: FittedEntryModel | None,
    features: dict,
    strategy: str | None = None,
) -> float | None:
    """Score one setup. None when the model isn't applicable or can't score."""
    if model is None or not model.applicable or model.weights is None:
        return None
    feats = dict(features or {})
    if strategy and not feats.get("strategy"):
        feats["strategy"] = strategy
    X, _ = _design(
        [feats],
        medians=model.medians,
        means=model.means,
        stds=model.stds,
        cat_levels=model.cat_levels,
        numeric_kept=model.numeric_kept,
    )
    # Column count can mismatch if a dummy set is empty on a 1-row design vs train.
    if X.shape[1] != len(model.weights):
        # Rebuild with training dummy names by padding/truncating to fit.
        if X.shape[1] < len(model.weights):
            pad = np.zeros((1, len(model.weights) - X.shape[1]))
            # Keep intercept as last column.
            X = np.hstack([X[:, :-1], pad, X[:, -1:]])
        else:
            X = np.hstack([X[:, : len(model.weights) - 1], X[:, -1:]])
    p = float(_sigmoid(X @ model.weights)[0])
    return round(max(_PROB_FLOOR, min(_PROB_CEIL, p)), 4)


def resolve_entry_probability(
    heuristic: float | None,
    features: dict,
    strategy: str,
    model: FittedEntryModel | None,
    calib: dict | None,
    settings,
) -> tuple[float | None, str | None, float | None]:
    """Pick the win-prob the EV gate should see.

    Returns ``(gate_win_prob, skip_reason, model_p)``. When the model is live:
    veto below ``min_prob`` and use model p (calibration is not stacked).
    Otherwise fall back to the calibrated heuristic.
    """
    feats = dict(features or {})
    if not feats.get("strategy"):
        feats["strategy"] = strategy
    model_p = predict_win_prob(model, feats, strategy)
    if model is not None and model.applicable and model_p is not None:
        min_prob = getattr(settings, "paper_entry_model_min_prob", model.min_prob)
        if model_p < min_prob:
            return None, f"model reject (p={model_p:.2f})", model_p
        return model_p, None, model_p
    return adjust_win_prob(heuristic, strategy, calib, settings), None, model_p


def entry_model_state(db: Session, settings) -> dict:
    """Serializable view for the API / Learning page."""
    try:
        model = fit_entry_model(db, settings)
    except Exception as e:  # noqa: BLE001 - UI must never 500 on a fit miss
        logger.warning("entry-model state failed: %s", e)
        return {
            "enabled": bool(getattr(settings, "paper_entry_model_enabled", False)),
            "applicable": False,
            "reason": f"fit failed: {e}",
            "n": 0,
            "coefficients": [],
        }
    out = model.as_dict()
    out["enabled"] = bool(getattr(settings, "paper_entry_model_enabled", False))
    out["min_samples"] = int(getattr(settings, "paper_entry_model_min_samples", 30))
    return out
