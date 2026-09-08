"""
calibration_v13.py — Is the confidence number telling the truth?

Your prediction_audit table already records every live signal with its
displayed confidence and its resolved WIN/LOSS outcome. Nothing has ever
read it back. This does.

Two separate questions, often confused:

  DISCRIMINATION — do higher-confidence signals win more often than
                   lower-confidence ones? If the hit rate is flat across
                   confidence buckets, the number carries no information
                   and should be removed from the UI.

  CALIBRATION    — when it says 60%, do 60% of those signals win? A model
                   can discriminate well but be badly calibrated, and that
                   is fixable by remapping without touching the signal.

Discrimination cannot be manufactured. Calibration can be repaired. So the
discrimination result decides whether the confidence number is salvageable.
"""

import math


def _fetch_resolved(db_conn_factory, limit=5000):
    with db_conn_factory() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT confidence, result, option_type, prediction,
                       pnl_points, generated_at
                FROM prediction_audit
                WHERE status = 'CLOSED'
                  AND result IN ('WIN', 'LOSS')
                  AND confidence IS NOT NULL
                ORDER BY generated_at DESC
                LIMIT %s
            """, (limit,))
            return cur.fetchall()


def _wilson(wins, n, z=1.96):
    """Wilson interval. With small per-bucket samples a naive proportion is
    badly overconfident, and every bucket here will be small."""
    if n == 0:
        return (None, None)
    p = wins / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, centre - half) * 100, 1),
            round(min(1.0, centre + half) * 100, 1))


def calibration_report(db_conn_factory, buckets=(0, 40, 50, 60, 70, 101)):
    rows = _fetch_resolved(db_conn_factory)
    n = len(rows)
    if n < 20:
        return {
            "status": "insufficient_data",
            "resolved_signals": n,
            "message": (
                f"Only {n} resolved signals. Need 20+ for any read and 100+ "
                "for a reliable one. Keep the tracker running."),
        }

    wins = sum(1 for r in rows if r[1] == "WIN")
    overall_hit = wins / n
    mean_conf = sum(float(r[0]) for r in rows) / n / 100.0

    # Brier score: mean squared error of the probability itself.
    # 0 is perfect, 0.25 is what you get by always saying 50%.
    brier = sum((float(r[0]) / 100.0 - (1.0 if r[1] == "WIN" else 0.0)) ** 2
                for r in rows) / n

    # ---- reliability curve -------------------------------------------
    table = []
    for lo, hi in zip(buckets[:-1], buckets[1:]):
        sub = [r for r in rows if lo <= float(r[0]) < hi]
        if not sub:
            continue
        w = sum(1 for r in sub if r[1] == "WIN")
        lo_ci, hi_ci = _wilson(w, len(sub))
        table.append({
            "confidence_band": f"{lo}-{hi - 1}%",
            "signals": len(sub),
            "claimed_confidence": round(
                sum(float(r[0]) for r in sub) / len(sub), 1),
            "actual_hit_rate": round(w / len(sub) * 100, 1),
            "ci95": [lo_ci, hi_ci],
        })

    # ---- discrimination ----------------------------------------------
    # Rank correlation between confidence and outcome. This is the number
    # that decides whether the confidence value is worth keeping at all.
    conf = [float(r[0]) for r in rows]
    outcome = [1.0 if r[1] == "WIN" else 0.0 for r in rows]
    disc = _rank_corr(conf, outcome)
    se = 1.0 / math.sqrt(n)

    if disc is None:
        verdict = "UNMEASURABLE"
    elif abs(disc) < se:
        verdict = "NO DISCRIMINATION — confidence carries no information"
    elif disc < 0:
        verdict = "INVERTED — high-confidence signals win LESS often"
    elif disc < 2 * se:
        verdict = "WEAK — direction is right but not statistically separable"
    else:
        verdict = "DISCRIMINATES — higher confidence really does win more"

    gap = (overall_hit - mean_conf) * 100

    return {
        "status": "success",
        "resolved_signals": n,
        "overall_hit_rate_percent": round(overall_hit * 100, 1),
        "mean_displayed_confidence_percent": round(mean_conf * 100, 1),
        "calibration_gap_percentage_points": round(gap, 1),
        "brier_score": round(brier, 4),
        "brier_reference": {
            "always_50_percent": 0.25,
            "read": "Above 0.25 means the confidence number is worse than "
                    "printing 50% on every signal.",
        },
        "discrimination_correlation": (round(disc, 4)
                                       if disc is not None else None),
        "discrimination_standard_error": round(se, 4),
        "verdict": verdict,
        "reliability_curve": table,
        "what_to_do": (
            "If discrimination is NO or INVERTED, remove the confidence "
            "percentage from the UI — a number that does not predict is "
            "worse than no number, because users act on it. If it "
            "DISCRIMINATES but the calibration gap is large, keep the "
            "ranking and remap the displayed value onto the observed hit "
            "rate per band, which is a display fix and needs no new signal."
        ),
    }


def _rank_corr(a, b):
    n = len(a)
    if n < 20:
        return None
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return num / (da * db) if da and db else None


def _ranks(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def signal_breakdown(db_conn_factory):
    """Hit rate split by CE vs PE and by prediction label. A large CE/PE
    asymmetry usually means the model is fitting one directional regime
    rather than reading the market."""
    rows = _fetch_resolved(db_conn_factory)
    if len(rows) < 20:
        return {"status": "insufficient_data", "resolved_signals": len(rows)}

    out = {}
    for key_idx, label in ((2, "by_option_type"), (3, "by_prediction")):
        groups = {}
        for r in rows:
            k = str(r[key_idx] or "UNKNOWN")
            groups.setdefault(k, []).append(r)
        out[label] = {
            k: {
                "signals": len(v),
                "hit_rate": round(
                    sum(1 for x in v if x[1] == "WIN") / len(v) * 100, 1),
                "ci95": _wilson(sum(1 for x in v if x[1] == "WIN"), len(v)),
                "avg_points": round(
                    sum(float(x[4] or 0) for x in v) / len(v), 2),
            }
            for k, v in groups.items() if len(v) >= 5
        }
    out["status"] = "success"
    out["resolved_signals"] = len(rows)
    return out
