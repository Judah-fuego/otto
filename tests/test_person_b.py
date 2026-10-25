"""Comprehensive test suite for Person B deliverables (voyage and app)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.alerts import alert_source, alerts_by_id
from app.gate import AUTO_CONFIDENCE, IRREVERSIBLE_SUBSYSTEMS, REVERSIBLE_SUBSYSTEMS, gate
from app.tools import dispatch_tool, tool_diagnose, tool_safemode_status, tool_voyage_calculate
from app.voice import extract_token_and_expiry, realtime_url
from schema import (
    FOOD_KG_PER_PERSON_DAY,
    MOCK_ALERTS,
    OXYGEN_KG_PER_PERSON_DAY,
    ROUTES,
    WATER_KG_PER_PERSON_DAY,
    Alert,
    Authority,
    load_alerts,
    parse_voyage_request,
)
from voyage import voyage_calculate
from voyage.windows import launch_window_utc


class TestVoyagePhysics(unittest.TestCase):
    def test_earth_mars_voyage(self) -> None:
        result = voyage_calculate(
            {
                "origin": "earth",
                "destination": "mars",
                "spacecraft_mass_kg": 10000,
                "isp_s": 300,
                "crew": 4,
            }
        )
        self.assertEqual(result.origin, "earth")
        self.assertEqual(result.destination, "mars")
        self.assertAlmostEqual(result.travel_time_days, ROUTES[("earth", "mars")], places=5)
        self.assertGreater(result.delta_v_m_s, 5000)
        self.assertGreater(result.propellant_kg, 0)
        self.assertAlmostEqual(result.oxygen_kg, 4 * 259 * OXYGEN_KG_PER_PERSON_DAY, places=2)
        self.assertAlmostEqual(result.water_kg, 4 * 259 * WATER_KG_PER_PERSON_DAY, places=2)
        self.assertAlmostEqual(result.food_kg, 4 * 259 * FOOD_KG_PER_PERSON_DAY, places=2)
        self.assertIsNotNone(result.launch_window_utc)
        self.assertTrue(result.launch_window_utc.endswith("Z"))

    def test_leo_moon_voyage(self) -> None:
        result = voyage_calculate(
            {
                "origin": "leo",
                "destination": "moon",
                "spacecraft_mass_kg": 10000,
                "isp_s": 300,
                "crew": 4,
            }
        )
        self.assertEqual(result.origin, "leo")
        self.assertEqual(result.destination, "moon")
        self.assertAlmostEqual(result.travel_time_days, ROUTES[("leo", "moon")], places=5)
        self.assertGreater(result.delta_v_m_s, 3000)
        self.assertGreater(result.propellant_kg, 0)
        self.assertAlmostEqual(result.oxygen_kg, 4 * 5 * OXYGEN_KG_PER_PERSON_DAY, places=2)
        self.assertAlmostEqual(result.water_kg, 4 * 5 * WATER_KG_PER_PERSON_DAY, places=2)
        self.assertAlmostEqual(result.food_kg, 4 * 5 * FOOD_KG_PER_PERSON_DAY, places=2)
        self.assertIsNotNone(result.launch_window_utc)
        self.assertTrue(result.launch_window_utc.endswith("Z"))

    def test_unsupported_route_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_voyage_request(
                {
                    "origin": "mars",
                    "destination": "earth",
                    "spacecraft_mass_kg": 10000,
                    "isp_s": 300,
                    "crew": 4,
                }
            )

    def test_invalid_parameters_raise(self) -> None:
        with self.assertRaises(ValueError):
            parse_voyage_request(
                {
                    "origin": "earth",
                    "destination": "mars",
                    "spacecraft_mass_kg": -100,
                    "isp_s": 300,
                    "crew": 4,
                }
            )
        with self.assertRaises(ValueError):
            parse_voyage_request(
                {
                    "origin": "earth",
                    "destination": "mars",
                    "spacecraft_mass_kg": 10000,
                    "isp_s": 300,
                    "crew": 0,
                }
            )


class TestAuthorityGate(unittest.TestCase):
    def test_demo_alerts(self) -> None:
        alerts = {alert.alert_id: alert for alert in load_alerts(MOCK_ALERTS)}
        self.assertEqual(gate(alerts["rw-backup"]), Authority.AUTO)
        self.assertEqual(gate(alerts["cabin-leak"]), Authority.ASK_CREW)

    def test_reversible_subsystems(self) -> None:
        for sub in REVERSIBLE_SUBSYSTEMS:
            confident_alert = Alert(
                alert_id="test-high",
                time="2026-10-25T18:00:00Z",
                channel="A-1",
                subsystem=sub,
                confidence=AUTO_CONFIDENCE,
                values=(0.1, 0.2),
            )
            self.assertEqual(gate(confident_alert), Authority.AUTO)

            uncertain_alert = Alert(
                alert_id="test-low",
                time="2026-10-25T18:00:00Z",
                channel="A-1",
                subsystem=sub,
                confidence=AUTO_CONFIDENCE - 0.05,
                values=(0.1, 0.2),
            )
            self.assertEqual(gate(uncertain_alert), Authority.ESCALATE)

    def test_irreversible_subsystems(self) -> None:
        for sub in IRREVERSIBLE_SUBSYSTEMS:
            alert = Alert(
                alert_id="test-irrev",
                time="2026-10-25T18:00:00Z",
                channel="F-1",
                subsystem=sub,
                confidence=0.99,
                values=(0.1, 0.2),
            )
            self.assertEqual(gate(alert), Authority.ASK_CREW)

    def test_other_subsystems_escalate(self) -> None:
        for sub in ("power_eps", "mechanisms"):
            alert = Alert(
                alert_id="test-other",
                time="2026-10-25T18:00:00Z",
                channel="P-1",
                subsystem=sub,
                confidence=0.99,
                values=(0.1, 0.2),
            )
            self.assertEqual(gate(alert), Authority.ESCALATE)


class TestTools(unittest.TestCase):
    def test_tool_voyage_calculate_defaults(self) -> None:
        res = dispatch_tool("voyage_calculate", {})
        self.assertEqual(res["origin"], "earth")
        self.assertEqual(res["destination"], "mars")
        self.assertEqual(res["crew"], 4)
        self.assertAlmostEqual(res["travel_time_days"], 259.0)
        self.assertIn("delta_v_km_s", res)

    def test_tool_voyage_calculate_moon_synonyms(self) -> None:
        res = dispatch_tool("voyage_calculate", {"destination": "moon"})
        self.assertEqual(res["origin"], "leo")
        self.assertEqual(res["destination"], "moon")
        self.assertAlmostEqual(res["travel_time_days"], 5.0)

    def test_tool_safemode_status(self) -> None:
        status = dispatch_tool("safemode_status", {})
        self.assertIn("live", status)
        self.assertIn("alert_count", status)
        self.assertIn("alert_ids", status)
        self.assertGreaterEqual(status["alert_count"], 2)

    def test_tool_diagnose(self) -> None:
        rw = dispatch_tool("diagnose", {"alert_id": "rw-backup"})
        self.assertEqual(rw["authority"], "auto")
        self.assertEqual(rw["channel"], "A-1")
        self.assertFalse(rw["cannot_be_undone"])

        leak = dispatch_tool("diagnose", {"alert_id": "cabin-leak"})
        self.assertEqual(leak["authority"], "ask_crew")
        self.assertEqual(leak["channel"], "F-1")
        self.assertTrue(leak["cannot_be_undone"])

        unknown = dispatch_tool("diagnose", {"alert_id": "missing-id"})
        self.assertIn("error", unknown)
        self.assertIn("known", unknown)

    def test_unknown_tool(self) -> None:
        res = dispatch_tool("nonexistent_tool", {})
        self.assertIn("error", res)


class TestAlertSource(unittest.TestCase):
    def test_mock_fallback_when_queue_missing(self) -> None:
        alerts, path, live = alert_source()
        self.assertFalse(live)
        self.assertTrue(path.endswith("mock_alerts.json"))
        self.assertEqual({a.alert_id for a in alerts}, {"rw-backup", "cabin-leak"})

    def test_live_queue_and_concurrency_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_file = Path(tmpdir) / "alerts.json"
            queue_file.write_text(json.dumps([
                {
                    "alert_id": "live-alert",
                    "time": "2026-10-25T18:00:00Z",
                    "channel": "P-1",
                    "subsystem": "power_eps",
                    "confidence": 0.85,
                    "values": [0.1, 0.2],
                }
            ]))
            with patch("app.alerts.ALERT_QUEUE", queue_file):
                alerts, path, live = alert_source()
                self.assertTrue(live)
                self.assertEqual(len(alerts), 1)
                self.assertEqual(alerts[0].alert_id, "live-alert")

                # Test corrupted/half-written file fallback
                queue_file.write_text("{ incomplete json")
                cached_alerts, _, cached_live = alert_source()
                self.assertTrue(cached_live)
                self.assertEqual(len(cached_alerts), 1)
                self.assertEqual(cached_alerts[0].alert_id, "live-alert")


class TestVoiceSessionAndToken(unittest.TestCase):
    def test_extract_token_and_expiry_nested_dict(self) -> None:
        payload = {
            "client_secret": {
                "value": "xai_es_secret_123",
                "expires_at": 1782672000,
            }
        }
        val, exp = extract_token_and_expiry(payload)
        self.assertEqual(val, "xai_es_secret_123")
        self.assertEqual(exp, 1782672000)

    def test_extract_token_and_expiry_direct_value(self) -> None:
        payload = {
            "value": "xai_es_direct_456",
            "expires_at": 1782672000,
        }
        val, exp = extract_token_and_expiry(payload)
        self.assertEqual(val, "xai_es_direct_456")
        self.assertEqual(exp, 1782672000)

    def test_extract_token_and_expiry_string_client_secret(self) -> None:
        payload = {
            "client_secret": "xai_es_string_789",
            "expires_at": 1782672000,
        }
        val, exp = extract_token_and_expiry(payload)
        self.assertEqual(val, "xai_es_string_789")
        self.assertEqual(exp, 1782672000)

    def test_extract_token_invalid_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            extract_token_and_expiry({"unexpected": "key"})

    def test_realtime_url_generation(self) -> None:
        url = realtime_url()
        self.assertTrue(url.startswith("wss://") or url.startswith("ws://"))
        self.assertIn("realtime?model=", url)


if __name__ == "__main__":
    unittest.main()
