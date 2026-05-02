import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_absolute_error, r2_score
from data_generator import NODES, generate_consumption_data
from datetime import datetime, timedelta

_models: dict = {}
_metrics_cache: dict = {}

# 3-hour slot distribution by building type (8 slots: 00,03,...,21)
_HOURLY_DIST = {
    "house":     [0.040, 0.030, 0.055, 0.095, 0.120, 0.145, 0.210, 0.305],
    "school":    [0.020, 0.015, 0.040, 0.185, 0.220, 0.200, 0.185, 0.135],
    "mosque":    [0.085, 0.070, 0.105, 0.115, 0.150, 0.115, 0.105, 0.255],
    "apartment": [0.045, 0.030, 0.055, 0.095, 0.115, 0.140, 0.215, 0.305],  # akşam piki
    "market":    [0.025, 0.020, 0.045, 0.135, 0.175, 0.185, 0.215, 0.130],  # gündüz/akşam
    "office":    [0.020, 0.015, 0.035, 0.170, 0.215, 0.210, 0.185, 0.090],  # mesai saatleri
}


# ── Gelişmiş model: haftanın günü + yılın günü + son 7g ort + son 3g ort ──
def _build_lagged_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().reset_index(drop=True)
    df["lag_7d"] = df["consumption_kwh"].rolling(7, min_periods=1).mean().shift(1)
    df["lag_3d"] = df["consumption_kwh"].rolling(3, min_periods=1).mean().shift(1)
    return df.dropna(subset=["lag_7d", "lag_3d", "consumption_kwh"])


def _train_enhanced_model(node_id: str):
    node = next(n for n in NODES if n["id"] == node_id)
    df = generate_consumption_data(node, days=1095)
    df = _build_lagged_df(df)

    X = df[["day_of_week", "day_of_year", "lag_7d", "lag_3d"]].values
    y = df["consumption_kwh"].values

    model = Pipeline([
        ("poly", PolynomialFeatures(degree=2, include_bias=False)),
        ("lr",   LinearRegression()),
    ])
    model.fit(X, y)
    return model, df


def get_model(node_id: str):
    if node_id not in _models:
        _models[node_id] = _train_enhanced_model(node_id)
    return _models[node_id]  # returns (pipeline, training_df)


# ── Basit poly model (mevcut kod uyumluluğu için) ────────────────────────
def _train_simple_model(node_id: str) -> Pipeline:
    node = next(n for n in NODES if n["id"] == node_id)
    df = generate_consumption_data(node, days=1095)
    X = df[["day_of_week", "day_of_year"]].values
    y = df["consumption_kwh"].values
    m = Pipeline([
        ("poly", PolynomialFeatures(degree=2, include_bias=False)),
        ("lr",   LinearRegression()),
    ])
    m.fit(X, y)
    return m


# ── İlerleyen gün tahminleri ─────────────────────────────────────────────
# Lag özellikleri son gerçek değerlere sabitlenir → tahmin zinciri patlaması önlenir
def predict_next_days(node_id: str, days: int = 30) -> list[dict]:
    model, train_df = get_model(node_id)
    lag7 = float(train_df["consumption_kwh"].tail(7).mean())
    lag3 = float(train_df["consumption_kwh"].tail(3).mean())

    start = datetime(2026, 4, 1)
    results = []
    for i in range(days):
        date = start + timedelta(days=i)
        dow  = date.weekday()
        doy  = date.timetuple().tm_yday
        pred = float(model.predict(np.array([[dow, doy, lag7, lag3]]))[0])
        results.append({"date": date.strftime("%Y-%m-%d"), "predicted_kwh": round(max(0.1, pred), 2)})
    return results


def get_latest_consumption(node_id: str) -> float:
    node = next(n for n in NODES if n["id"] == node_id)
    df   = generate_consumption_data(node, days=1095)
    return float(df["consumption_kwh"].iloc[-1])


def get_history(node_id: str, days: int = 90) -> list[dict]:
    node = next(n for n in NODES if n["id"] == node_id)
    df   = generate_consumption_data(node, days=1095)
    return df.tail(days)[["date", "consumption_kwh"]].to_dict(orient="records")


# ── Model metrikleri (MAPE tabanlı doğruluk) ────────────────────────────
def get_model_metrics(node_id: str) -> dict:
    if node_id in _metrics_cache:
        return _metrics_cache[node_id]

    node = next(n for n in NODES if n["id"] == node_id)
    df   = generate_consumption_data(node, days=365).tail(180).reset_index(drop=True)
    df   = _build_lagged_df(df)

    X = df[["day_of_week", "day_of_year", "lag_7d", "lag_3d"]].values
    y = df["consumption_kwh"].values

    split = int(len(X) * 0.75)
    X_tr, X_te = X[:split], X[split:]
    y_tr, y_te = y[:split], y[split:]

    m = Pipeline([
        ("poly", PolynomialFeatures(degree=2, include_bias=False)),
        ("lr",   LinearRegression()),
    ])
    m.fit(X_tr, y_tr)
    y_pred = np.maximum(m.predict(X_te), 0.1)

    mae  = round(float(mean_absolute_error(y_te, y_pred)), 2)
    mape = float(np.mean(np.abs((y_te - y_pred) / np.maximum(y_te, 0.1)))) * 100
    acc  = round(min(99.9, max(0.0, 100.0 - mape)), 1)
    r2   = round(float(r2_score(y_te, y_pred)), 3)

    result = {
        "model_name": "Polynomial Regression",
        "degree": 2,
        "features": ["Haftanın Günü", "Yılın Günü", "Son 7g Ort.", "Son 3g Ort."],
        "feature_count": 14,  # PolynomialFeatures degree=2 of 4 inputs → 14 features
        "mae": mae,
        "r2": r2,
        "accuracy": acc,
    }
    _metrics_cache[node_id] = result
    return result


# ── Güven aralıklı tahmin ────────────────────────────────────────────────
def predict_with_ci(node_id: str, days: int = 30) -> list[dict]:
    model, train_df = get_model(node_id)

    # Artık (residuals) hesapla
    df_lag = _build_lagged_df(train_df)
    X_all  = df_lag[["day_of_week", "day_of_year", "lag_7d", "lag_3d"]].values
    y_all  = df_lag["consumption_kwh"].values
    resid  = y_all - model.predict(X_all)
    std_r  = float(np.std(resid))

    # Sabit lag özellikleri → kararlı tahmin serisi
    lag7  = float(train_df["consumption_kwh"].tail(7).mean())
    lag3  = float(train_df["consumption_kwh"].tail(3).mean())

    start = datetime(2026, 4, 1)
    results = []
    for i in range(days):
        date  = start + timedelta(days=i)
        dow   = date.weekday()
        doy   = date.timetuple().tm_yday
        pred  = float(model.predict(np.array([[dow, doy, lag7, lag3]]))[0])
        pred  = max(0.1, pred)
        # Belirsizlik zaman içinde genişler
        grow  = 1.0 + i * 0.015
        lower = max(0.0, pred - 1.28 * std_r * grow)
        upper = pred + 1.28 * std_r * grow
        results.append({
            "date":          date.strftime("%Y-%m-%d"),
            "predicted_kwh": round(pred, 2),
            "lower":         round(lower, 2),
            "upper":         round(upper, 2),
        })
    return results


# ── Geçmiş backtest: gerçek vs tahmin (son N gün) ───────────────────────
def get_backtest(node_id: str, days: int = 14) -> list[dict]:
    model, train_df = get_model(node_id)
    df_lag = _build_lagged_df(train_df)

    # Son (days+10) günden son days tanesini al
    test_df = df_lag.tail(days + 10).head(days)
    results = []
    for _, row in test_df.iterrows():
        X = np.array([[row["day_of_week"], row["day_of_year"], row["lag_7d"], row["lag_3d"]]])
        pred   = float(model.predict(X)[0])
        pred   = max(0.1, pred)
        actual = float(row["consumption_kwh"])
        err    = abs(pred - actual) / max(actual, 0.1) * 100
        results.append({
            "date":           str(row["date"]),
            "actual_kwh":     round(actual, 2),
            "predicted_kwh":  round(pred, 2),
            "error_pct":      round(err, 1),
        })
    return results


# ── Özellik önemi (permütasyon tabanlı) ─────────────────────────────────
def get_feature_importance(node_id: str) -> list[dict]:
    model, train_df = get_model(node_id)
    df_lag = _build_lagged_df(train_df).tail(365)
    feat_cols = ["day_of_week", "day_of_year", "lag_7d", "lag_3d"]
    labels    = ["Haftanın Günü", "Yılın Günü", "Son 7g Ort.", "Son 3g Ort."]

    X = df_lag[feat_cols].values
    y = df_lag["consumption_kwh"].values

    base_mae = mean_absolute_error(y, np.maximum(model.predict(X), 0.1))

    rng = np.random.RandomState(42)
    importances = []
    for i, lbl in enumerate(labels):
        X_perm       = X.copy()
        X_perm[:, i] = rng.permutation(X_perm[:, i])
        perm_mae     = mean_absolute_error(y, np.maximum(model.predict(X_perm), 0.1))
        importances.append({"feature": lbl, "delta_mae": max(0.0, perm_mae - base_mae)})

    total = sum(f["delta_mae"] for f in importances) or 1.0
    for f in importances:
        f["importance_pct"] = round(f["delta_mae"] / total * 100, 1)
        del f["delta_mae"]

    return sorted(importances, key=lambda x: x["importance_pct"], reverse=True)


# ── Trend analizi ────────────────────────────────────────────────────────
def get_trend(node_id: str) -> dict:
    node = next(n for n in NODES if n["id"] == node_id)
    df   = generate_consumption_data(node, days=1095)

    last_7 = float(df["consumption_kwh"].iloc[-7:].mean())
    prev_7 = float(df["consumption_kwh"].iloc[-14:-7].mean())

    if prev_7 == 0:
        return {"direction": "sabit", "percent": 0.0, "last_7_avg": round(last_7, 2), "prev_7_avg": 0.0}

    change_pct = (last_7 - prev_7) / prev_7 * 100
    direction  = "artış" if change_pct > 3 else "düşüş" if change_pct < -3 else "sabit"

    return {
        "direction":  direction,
        "percent":    round(abs(change_pct), 1),
        "last_7_avg": round(last_7, 2),
        "prev_7_avg": round(prev_7, 2),
    }


# ── Saatlik profil ───────────────────────────────────────────────────────
def predict_hourly(node_id: str, daily_kwh: float) -> list[dict]:
    node  = next(n for n in NODES if n["id"] == node_id)
    dist  = _HOURLY_DIST.get(node["type"], _HOURLY_DIST["house"])
    total = sum(dist)
    rng   = np.random.RandomState(int(daily_kwh * 100) % 2**31)
    hours = ["00:00", "03:00", "06:00", "09:00", "12:00", "15:00", "18:00", "21:00"]
    return [
        {"hour": h, "predicted_kwh": round(max(0.001, daily_kwh * (d / total) * (1 + rng.uniform(-0.04, 0.04))), 3)}
        for h, d in zip(hours, dist)
    ]
