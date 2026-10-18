"""Leakage-free univariate anomaly screening. Scores are not probabilities."""

import numpy as np
from sklearn.ensemble import IsolationForest


def assess_disruptions(signals):
    findings = []
    for signal in signals:
        values = np.array([row["value"] for row in signal["observations"]], dtype=float)
        baseline, latest = values[:-1], float(values[-1])
        median = float(np.median(baseline))
        mad = float(np.median(np.abs(baseline - median)))
        scale = max(1.4826 * mad, float(np.std(baseline)) * 0.1, 0.01)
        signed_z = (latest - median) / scale
        adverse_z = signed_z if signal["direction"] == "high" else -signed_z
        model = IsolationForest(n_estimators=100, contamination=0.05, random_state=42, n_jobs=1)
        model.fit(baseline.reshape(-1, 1))
        isolated = int(model.predict([[latest]])[0]) == -1
        anomaly = bool(isolated and adverse_z >= 3)
        ewma = float(baseline[0])
        for value in baseline[1:]:
            ewma = 0.3 * float(value) + 0.7 * ewma
        findings.append(
            {
                "signal_id": signal["id"],
                "family": signal["family"],
                "subtype": signal["subtype"],
                "metric": signal["metric"],
                "unit": signal["unit"],
                "observed_value": latest,
                "baseline_median": round(median, 3),
                "baseline_ewma": round(ewma, 3),
                "adverse_robust_z": round(adverse_z, 3),
                "isolation_outlier": isolated,
                "anomaly": anomaly,
                "baseline_samples": len(baseline),
                "baseline_start": signal["observations"][0]["day"],
                "baseline_end": signal["observations"][-2]["day"],
                "observation_date": signal["observations"][-1]["day"],
                "synthetic": True,
                "probability": None,
                "method": "Isolation Forest + directional robust z >= 3; held-out latest observation",
            }
        )
    return {
        "families_supported": ["external", "internal", "market"],
        "signals": findings,
        "anomalies": sum(row["anomaly"] for row in findings),
        "scope": "Synthetic monitoring signals. Statistical outliers are review triggers, not proof of cause or calibrated disruption probabilities.",
    }
