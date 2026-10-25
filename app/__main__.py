from app.gate import gate
from app.tools import tool_diagnose, tool_safemode_status
from schema import Authority, MOCK_ALERTS, load_alerts


def _self_check() -> None:
    alerts = {alert.alert_id: alert for alert in load_alerts(MOCK_ALERTS)}
    assert gate(alerts["rw-backup"]) is Authority.AUTO
    assert gate(alerts["cabin-leak"]) is Authority.ASK_CREW
    rw = tool_diagnose({"alert_id": "rw-backup"})
    leak = tool_diagnose({"alert_id": "cabin-leak"})
    assert rw["authority"] == "auto"
    assert leak["authority"] == "ask_crew"
    status = tool_safemode_status()
    assert status["alert_count"] >= 2


def main() -> None:
    from app.server import serve

    _self_check()
    serve()


if __name__ == "__main__":
    main()
