from __future__ import annotations

import logging

from schema import ALERT_QUEUE, MOCK_ALERTS, Alert, load_alerts

_cached_live_alerts: list[Alert] = []


def alert_source() -> tuple[list[Alert], str, bool]:
    """Live queue if Person A has written it, otherwise the demo file.
    Safely handles transient partial writes by caching recent valid live alerts."""
    global _cached_live_alerts
    if ALERT_QUEUE.exists():
        try:
            alerts = load_alerts(ALERT_QUEUE)
            _cached_live_alerts = alerts
            return alerts, str(ALERT_QUEUE), True
        except Exception as exc:  # noqa: BLE001
            logging.warning("Failed to parse live alerts queue (%s); using cached state", exc)
            if _cached_live_alerts:
                return _cached_live_alerts, str(ALERT_QUEUE), True
    return load_alerts(MOCK_ALERTS), str(MOCK_ALERTS), False


def alerts_by_id() -> dict[str, Alert]:
    alerts, _, _ = alert_source()
    return {alert.alert_id: alert for alert in alerts}
