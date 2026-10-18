"""Anomaly outputs are scores, never represented as calibrated probabilities."""

from sklearn.ensemble import IsolationForest


def assess_signals(history: list[list[float]], severity: float) -> dict:
    if len(history) < 8:
        return {
            "risk_score": round(severity * 100, 1),
            "probability": None,
            "method": "external severity only",
            "history_sufficient": False,
        }
    baseline, latest = history[:-1], history[-1]
    ewma = baseline[0][0]
    for row in baseline[1:]:
        ewma = 0.3 * row[0] + 0.7 * ewma
    current_ewma = 0.3 * latest[0] + 0.7 * ewma
    model = IsolationForest(n_estimators=100, random_state=17, contamination="auto", n_jobs=1)
    model.fit(baseline)
    anomaly = max(0.0, min(1.0, float(-model.score_samples([latest])[0])))
    decline = max(0.0, min(1.0, (ewma - latest[0]) / 0.2))
    risk = 100 * (0.5 * severity + 0.3 * anomaly + 0.2 * decline)
    return {
        "risk_score": round(risk, 2),
        "probability": None,
        "anomaly_score": round(anomaly, 4),
        "otif_ewma": round(current_ewma, 4),
        "history_sufficient": True,
        "method": "EWMA + Isolation Forest + uncalibrated weighted evidence score",
        "weights": {"external_severity": 0.5, "anomaly": 0.3, "otif_decline": 0.2},
    }
