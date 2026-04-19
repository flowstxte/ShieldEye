import time
from collections import deque
from typing import List

MAX_ALERTS = 200


class AlertManager:

    def __init__(self):
        self._alerts: deque = deque(maxlen=MAX_ALERTS)

    def add(self, alert: dict):
        if "timestamp" not in alert:
            alert["timestamp"] = time.time()
        if "time_str" not in alert:
            alert["time_str"] = time.strftime("%H:%M:%S")
        self._alerts.appendleft(alert)
        self._log(alert)

    def get_all(self) -> List[dict]:
        return list(self._alerts)

    def get_by_severity(self, severity: str) -> List[dict]:
        return [a for a in self._alerts if a.get("severity") == severity]

    def get_recent(self, seconds: int = 60) -> List[dict]:
        cutoff = time.time() - seconds
        return [a for a in self._alerts if a.get("timestamp", 0) >= cutoff]

    def count(self) -> int:
        return len(self._alerts)

    def clear(self):
        self._alerts.clear()
        print("[Alerts] Cleared.")

    def stats(self) -> dict:
        breakdown = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        for a in self._alerts:
            sev = a.get("severity", "low")
            breakdown[sev] = breakdown.get(sev, 0) + 1
        return {"total": len(self._alerts), "by_severity": breakdown}

    @staticmethod
    def _log(alert: dict):
        icons = {"LOW": "ℹ️ ", "MEDIUM": "⚠️ ", "HIGH": "🔶", "CRITICAL": "🚨"}
        sev   = alert.get("severity", "").upper()
        print(f"[Alert] {icons.get(sev,'📋')} [{alert.get('time_str','')}] [{sev}] "
              f"{alert.get('title','')} — {alert.get('detail','')}")