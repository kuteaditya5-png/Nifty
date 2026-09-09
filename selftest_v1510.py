"""Offline validation of the v15.10 endpoint logic.

Network and the app's deps (fastapi/yfinance/psycopg) are unavailable in this
sandbox, so the real functions are lifted out of main.py by AST and executed
against synthetic series with known statistical properties. Same discipline
FINDINGS_v13.md used on the v13 engine.
"""
import ast, math, sys
import numpy as np
import pandas as pd

SRC = open("main.py").read()
tree = ast.parse(SRC)

WANT = {
    "_v157_num", "_v157_candidate_features", "_v158_train_rule",
    "_v1510_eval", "_v1510_decorrelate", "_v1510_vote_series",
    "_v1510_pair_events", "v1510_feature_interaction_regime",
}
ns = {"np": np, "pd": pd, "math": math}


class FakeApp:
    def get(self, *a, **k):
        return lambda f: f


ns["app"] = FakeApp()

for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in WANT:
        node.decorator_list = [] if node.name.startswith("v1510_") else node.decorator_list
        exec(compile(ast.Module([node], []), "<x>", "exec"), ns)
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id.startswith("V1510_"):
                exec(compile(ast.Module([node], []), "<x>", "exec"), ns)

missing = WANT - set(ns)
assert not missing, missing
print("lifted:", len(WANT), "functions")


# ---- unit: decorrelation actually enforces non-overlap -----------------
dec = ns["_v1510_decorrelate"]
ev = [(i, 1.0) for i in range(100)]           # a signal on every bar
assert len(dec(ev, 6)) == 17, len(dec(ev, 6))  # ceil(100/6)
ev2 = [(0, 1.0), (3, 1.0), (6, 1.0), (60, 1.0)]
assert len(dec(ev2, 6)) == 3                   # bar 3 dropped, overlaps bar 0
print("decorrelate: non-overlap enforced")

# duplicates on the same bar collapse to one
assert len(dec([(10, 1.0), (10, 1.0), (10, 1.0)], 6)) == 1
print("decorrelate: same-bar duplicates collapse")


# ---- unit: eval significance ------------------------------------------
ev_fn = ns["_v1510_eval"]
m = ev_fn([1.0] * 55 + [-1.0] * 45, cost_bps=3.0)
assert m["signals"] == 100 and m["accuracy_percent"] == 55.0
assert abs(m["net_avg_bps"] - (m["avg_bps"] - 3.0)) < 1e-9
assert 0.30 < m["p_value"] < 0.35, m["p_value"]   # 55/100 is not significant
print("eval: p-value + cost subtraction correct  ->", m)


# ---- end-to-end on synthetic series -----------------------------------
def synth(n, seed, kind="noise"):
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.0012, n)
    if kind == "trend":
        for i in range(1, n):
            r[i] += 0.35 * r[i - 1]
    if kind == "revert":
        for i in range(1, n):
            r[i] -= 0.35 * r[i - 1]
    close = 23500 * np.exp(np.cumsum(r))
    idx = pd.date_range("2025-01-01 09:15", periods=n, freq="15min")
    hi = close * (1 + np.abs(rng.normal(0, 0.0006, n)))
    lo = close * (1 - np.abs(rng.normal(0, 0.0006, n)))
    op = np.concatenate([[close[0]], close[:-1]])
    df = pd.DataFrame({"open": op, "high": hi, "low": lo, "close": close}, index=idx)
    ema20 = df.close.ewm(span=20).mean()
    ema50 = df.close.ewm(span=50).mean()
    d = df.close.diff()
    rs = d.clip(lower=0).rolling(14).mean() / (-d.clip(upper=0)).rolling(14).mean()
    df["ema20"], df["ema50"] = ema20, ema50
    df["rsi"] = 100 - 100 / (1 + rs)
    df["macd"] = df.close.ewm(span=12).mean() - df.close.ewm(span=26).mean()
    tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(),
                    (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    return df


def run(df):
    ns["_v146_load_raw_history"] = lambda *a, **k: df
    ns["_v148_quality_report"] = lambda *a, **k: {"backtest_ready": True}
    ns["_v146_feature_frame_from_raw"] = lambda raw: raw
    return ns["v1510_feature_interaction_regime"](blocks=4, top_k=4, cost_bps=3.0)


print("\n--- pure noise, 6 seeds (an honest engine must land near 50%) ---")
accs, nets, verdicts = [], [], []
for s in range(6):
    r = run(synth(4200, s, "noise"))
    if r.get("status") != "success":
        print(f"  seed {s}: {r.get('message')}")
        continue
    x, u = r["summary"], r["uncorrected_comparison"]
    accs.append(x["weighted_accuracy_percent"])
    nets.append(x["net_avg_bps"])
    verdicts.append(r["verdict"])
    print(f"  seed {s}: independent n={x['independent_signals']:>4} "
          f"acc={x['weighted_accuracy_percent']:>5}%  p={x['p_value']:<7} "
          f"net={x['net_avg_bps']:>7}bps  | v15.9 would report n={u['signals']:>4} "
          f"acc={u['accuracy_percent']}%  -> {r['verdict']}")

if accs:
    print(f"\n  mean accuracy on noise: {np.mean(accs):.1f}%  (target ~50)")
    print(f"  mean net bps on noise : {np.mean(nets):.2f}  (must be negative after cost)")
    print(f"  promotions on noise   : {sum(1 for v in verdicts if 'REPEATABLE' in v)}/{len(verdicts)} (must be 0)")

print("\n--- mean-reverting series (feature rules should find signal) ---")
r = run(synth(4200, 11, "revert"))
if r.get("status") == "success":
    x = r["summary"]
    print(f"  independent n={x['independent_signals']} acc={x['weighted_accuracy_percent']}% "
          f"p={x['p_value']} gross={x['weighted_avg_bps']}bps net={x['net_avg_bps']}bps -> {r['verdict']}")
    print(f"  gate checks: {r['gate_checks']}")
    print(f"  fragility  : {r['fragility']}")
    tc = r["top_interactions"][:3]
    for c in tc:
        print(f"   cell {c['name']}: train {c['train_accuracy_percent']}% "
              f"(n={c['train_signals']}) -> val {c['validation_accuracy_percent']}% "
              f"(n={c['validation_signals']}), degradation {c['degradation_pts']} pts")
else:
    print(" ", r.get("message"))
