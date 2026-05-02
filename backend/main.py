from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os, sys

sys.path.insert(0, os.path.dirname(__file__))

from data_generator import NODES, get_latest_solar, get_node_averages, get_full_daily_data
from ml_model import (predict_next_days, get_latest_consumption, get_history,
                       get_model_metrics, predict_hourly, get_trend,
                       predict_with_ci, get_backtest, get_feature_importance)
from json_data_loader import get_latest_period_stats

UNIT_PRICE = 2.85  # TL / kWh

app = FastAPI(title="EcoNode Dashboard")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=os.path.join(frontend_dir, "static")), name="static")


@app.get("/")
def root():
    return FileResponse(os.path.join(frontend_dir, "index.html"))


def _build_node(node: dict) -> dict:
    # Use ANNUAL AVERAGE for dashboard view as requested
    consumption, solar = get_node_averages(node["id"])
    
    net_current      = max(0.0, consumption - solar)
    daily_bill       = round(net_current * UNIT_PRICE, 2)

    predictions      = predict_next_days(node["id"], days=30)
    pred_consumption = sum(p["predicted_kwh"] for p in predictions)
    pred_solar       = node["base_solar"] * 30
    pred_net         = max(0.0, pred_consumption - pred_solar)
    monthly_bill     = round(pred_net * UNIT_PRICE, 2)
    next_day_kwh     = predictions[0]["predicted_kwh"] if predictions else 0.0

    return {
        "id":                       node["id"],
        "name":                     node["name"],
        "type":                     node["type"],
        "lat":                      node["lat"],
        "lon":                      node["lon"],
        "current_kwh":              round(consumption, 2),
        "current_solar_kwh":        round(solar, 2),
        "net_current_kwh":          round(net_current, 2),
        "daily_bill_tl":            daily_bill,
        "predicted_monthly_kwh":    round(pred_consumption, 2),
        "predicted_monthly_solar":  round(pred_solar, 2),
        "predicted_monthly_net":    round(pred_net, 2),
        "bill_tl":                  monthly_bill,
        "predicted_next_day_kwh":   round(next_day_kwh, 2),
        "base_solar":               node["base_solar"],
    }


@app.get("/nodes")
def get_nodes():
    return [_build_node(n) for n in NODES]


@app.get("/predict/{node_id}")
def predict_node(node_id: str, days: int = 30):
    if node_id not in [n["id"] for n in NODES]:
        raise HTTPException(status_code=404, detail="Node not found")
    return {
        "node_id":     node_id,
        "history":     get_history(node_id, days=90),
        "predictions": predict_next_days(node_id, days=days),
    }


@app.get("/summary")
def summary():
    nodes = [_build_node(n) for n in NODES]
    total_c  = sum(n["current_kwh"] for n in nodes)
    total_s  = sum(n["current_solar_kwh"] for n in nodes)
    total_net = sum(n["net_current_kwh"] for n in nodes)
    total_bill = sum(n["bill_tl"] for n in nodes)
    total_pred = sum(n["predicted_monthly_kwh"] for n in nodes)
    return {
        "total_current_kwh":          round(total_c, 2),
        "total_solar_kwh":            round(total_s, 2),
        "total_net_kwh":              round(total_net, 2),
        "avg_current_kwh":            round(total_c / len(nodes), 2),
        "total_predicted_monthly_kwh": round(total_pred, 2),
        "total_bill_tl":              round(total_bill, 2),
        "unit_price_tl":              UNIT_PRICE,
        "node_count":                 len(nodes),
    }

@app.get("/analysis")
def get_analysis():
    df = get_full_daily_data()
    node_comp = df.groupby("node_id")["consumption_kwh"].sum().to_dict()
    return {
        "total_consumption": round(df["consumption_kwh"].sum(), 2),
        "avg_consumption":   round(df["consumption_kwh"].mean(), 2),
        "max_consumption":   round(df["consumption_kwh"].max(), 2),
        "min_consumption":   round(df["consumption_kwh"].min(), 2),
        "node_comparison":   node_comp
    }


@app.get("/monthly")
def get_monthly():
    df = get_full_daily_data().copy()
    df["month"] = df["date"].apply(lambda x: x.split("-")[1])
    monthly = df.groupby("month").agg({"consumption_kwh": "sum", "solar_kwh": "sum"}).reset_index()
    results = []
    for _, row in monthly.iterrows():
        net = max(0, row["consumption_kwh"] - row["solar_kwh"])
        results.append({
            "month": row["month"],
            "total_consumption": round(row["consumption_kwh"], 2),
            "total_solar": round(row["solar_kwh"], 2),
            "total_bill": round(net * UNIT_PRICE, 2)
        })
    return results


@app.get("/history_all")
def history_all():
    return get_full_daily_data().fillna(0).to_dict(orient="records")


@app.get("/analysis/type")
def get_analysis_by_type():
    df = get_full_daily_data()
    grouped = df.groupby("tip").agg(
        total_consumption=("consumption_kwh", "sum"),
        total_solar=("solar_kwh", "sum"),
        node_count=("node_id", "nunique")
    ).reset_index()
    results = []
    for _, row in grouped.iterrows():
        ratio = (row["total_solar"] / row["total_consumption"] * 100) if row["total_consumption"] > 0 else 0
        results.append({
            "tip": row["tip"],
            "total_consumption": round(row["total_consumption"], 2),
            "total_solar": round(row["total_solar"], 2),
            "node_count": int(row["node_count"]),
            "solar_ratio": round(ratio, 1)
        })
    return results


@app.get("/analysis/solar_ratio")
def get_solar_ratio():
    df = get_full_daily_data()
    grouped = df.groupby("node_id").agg(
        consumption=("consumption_kwh", "sum"),
        solar=("solar_kwh", "sum"),
        tip=("tip", "first")
    ).reset_index()
    node_name = {n["id"]: n["name"] for n in NODES}
    results = []
    for _, row in grouped.iterrows():
        ratio = (row["solar"] / row["consumption"] * 100) if row["consumption"] > 0 else 0
        results.append({
            "node_id": row["node_id"],
            "name": node_name.get(row["node_id"], row["node_id"]),
            "tip": row["tip"],
            "consumption": round(row["consumption"], 2),
            "solar": round(row["solar"], 2),
            "ratio": round(ratio, 1)
        })
    results.sort(key=lambda x: x["ratio"], reverse=True)
    return results


@app.get("/analysis/co2")
def get_co2():
    CO2_PER_KWH = 0.42
    df = get_full_daily_data()
    grouped = df.groupby("node_id").agg(
        solar=("solar_kwh", "sum"),
        consumption=("consumption_kwh", "sum"),
        tip=("tip", "first")
    ).reset_index()
    node_name = {n["id"]: n["name"] for n in NODES}
    total_solar = float(df["solar_kwh"].sum())
    by_node = []
    for _, row in grouped.iterrows():
        by_node.append({
            "node_id": row["node_id"],
            "name": node_name.get(row["node_id"], row["node_id"]),
            "solar_kwh": round(row["solar"], 2),
            "co2_saved_kg": round(row["solar"] * CO2_PER_KWH, 2),
        })
    by_node.sort(key=lambda x: x["co2_saved_kg"], reverse=True)
    return {
        "total_solar_kwh": round(total_solar, 2),
        "co2_saved_kg": round(total_solar * CO2_PER_KWH, 2),
        "co2_equiv_trees": round(total_solar * CO2_PER_KWH / 21.77, 1),
        "by_node": by_node
    }


@app.get("/analysis/anomalies")
def get_anomalies():
    import numpy as np
    df = get_full_daily_data()
    node_name = {n["id"]: n["name"] for n in NODES}
    results = []
    for node_id, grp in df.groupby("node_id"):
        vals = grp["consumption_kwh"].values
        mean, std = float(np.mean(vals)), float(np.std(vals))
        threshold = mean + 2 * std
        anomaly_days = grp[grp["consumption_kwh"] > threshold][["date", "consumption_kwh"]].to_dict(orient="records")
        results.append({
            "node_id": node_id,
            "name": node_name.get(node_id, node_id),
            "tip": grp["tip"].iloc[0] if "tip" in grp.columns else "unknown",
            "avg_consumption": round(mean, 2),
            "std": round(std, 2),
            "threshold": round(threshold, 2),
            "anomaly_count": len(anomaly_days),
            "anomaly_days": anomaly_days[:5]
        })
    results.sort(key=lambda x: x["anomaly_count"], reverse=True)
    return results


@app.get("/forecast/{node_id}")
def forecast_node(node_id: str):
    if node_id not in [n["id"] for n in NODES]:
        raise HTTPException(status_code=404, detail="Node not found")

    node = next(n for n in NODES if n["id"] == node_id)

    history            = get_history(node_id, days=21)
    predictions_ci     = predict_with_ci(node_id, days=30)
    metrics            = get_model_metrics(node_id)
    trend              = get_trend(node_id)
    backtest           = get_backtest(node_id, days=14)
    feature_importance = get_feature_importance(node_id)
    tomorrow_kwh       = predictions_ci[0]["predicted_kwh"] if predictions_ci else 0.0
    hourly             = predict_hourly(node_id, tomorrow_kwh)

    # uyarılar
    alerts = []
    avg_pred = sum(p["predicted_kwh"] for p in predictions_ci) / max(len(predictions_ci), 1)
    max_pred = max(predictions_ci, key=lambda p: p["predicted_kwh"])
    if max_pred["predicted_kwh"] > avg_pred * 1.20:
        alerts.append({
            "severity": "high", "type": "high_consumption", "icon": "⚡",
            "message": f"Yüksek tüketim tahmini: {max_pred['date']} tarihinde {max_pred['predicted_kwh']:.1f} kWh"
                       f" (30g ort. {avg_pred:.1f} kWh)"
        })

    max_h = max(hourly, key=lambda h: h["predicted_kwh"])
    alerts.append({
        "severity": "info", "type": "peak_hour", "icon": "🕐",
        "message": f"Yarınki pik saat: {max_h['hour']} — beklenen yük {max_h['predicted_kwh']:.2f} kWh"
    })

    if trend["direction"] == "artış" and trend["percent"] > 8:
        alerts.append({
            "severity": "warning", "type": "trend_up", "icon": "📈",
            "message": f"Son 7 gün tüketim ortalaması %{trend['percent']:.1f} artış eğiliminde"
        })
    elif trend["direction"] == "düşüş" and trend["percent"] > 8:
        alerts.append({
            "severity": "good", "type": "trend_down", "icon": "📉",
            "message": f"Son 7 gün tüketim %{trend['percent']:.1f} düşüş eğiliminde — verimlilik artıyor"
        })

    # Backtest özet
    if backtest:
        avg_err = sum(b["error_pct"] for b in backtest) / len(backtest)
        if avg_err < 10:
            alerts.append({
                "severity": "good", "type": "model_ok", "icon": "✅",
                "message": f"Model doğrulaması geçti — son 14 günde ort. hata %{avg_err:.1f}"
            })
        elif avg_err > 20:
            alerts.append({
                "severity": "warning", "type": "model_warn", "icon": "⚠️",
                "message": f"Model hatası yüksek — son 14 günde ort. %{avg_err:.1f}. Veriler değişmiş olabilir."
            })

    # Tüm node'ların karşılaştırması
    all_nodes_forecast = []
    for n in NODES:
        preds_7 = predict_with_ci(n["id"], days=7)
        avg_7d  = sum(p["predicted_kwh"] for p in preds_7) / len(preds_7)
        all_nodes_forecast.append({
            "id":                     n["id"],
            "name":                   n["name"],
            "type":                   n["type"],
            "predicted_tomorrow_kwh": round(preds_7[0]["predicted_kwh"], 2),
            "predicted_7d_avg_kwh":   round(avg_7d, 2),
        })

    max_node_id = max(all_nodes_forecast, key=lambda x: x["predicted_tomorrow_kwh"])["id"]
    for nf in all_nodes_forecast:
        nf["is_highest"] = nf["id"] == max_node_id

    return {
        "node_id":            node_id,
        "node_name":          node["name"],
        "node_type":          node["type"],
        "history":            history,
        "predictions":        predictions_ci,   # now includes lower/upper CI
        "backtest":           backtest,
        "metrics":            metrics,
        "feature_importance": feature_importance,
        "trend":              trend,
        "hourly":             hourly,
        "alerts":             alerts,
        "all_nodes_forecast": all_nodes_forecast,
    }


@app.get("/analysis/savings")
def get_savings():
    df = get_full_daily_data()
    node_name = {n["id"]: n["name"] for n in NODES}
    grouped = df.groupby("node_id").agg(
        consumption=("consumption_kwh", "sum"),
        solar=("solar_kwh", "sum"),
        tip=("tip", "first")
    ).reset_index()
    results = []
    for _, row in grouped.iterrows():
        net = max(0, row["consumption"] - row["solar"])
        actual_bill = round(net * UNIT_PRICE, 2)
        no_solar_bill = round(row["consumption"] * UNIT_PRICE, 2)
        saved = round(no_solar_bill - actual_bill, 2)
        results.append({
            "node_id": row["node_id"],
            "name": node_name.get(row["node_id"], row["node_id"]),
            "tip": row["tip"],
            "consumption_kwh": round(row["consumption"], 2),
            "solar_kwh": round(row["solar"], 2),
            "actual_bill_tl": actual_bill,
            "no_solar_bill_tl": no_solar_bill,
            "saved_tl": saved
        })
    results.sort(key=lambda x: x["saved_tl"], reverse=True)
    return results
