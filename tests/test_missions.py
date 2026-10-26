"""The mission catalog sets the ship and the path."""

from __future__ import annotations

import math
import unittest
from datetime import timedelta

from app import mission
from app.missions import CATALOG, activate, current_mission
from voyage.calculator import AU_KM


def _polar(r1: float, r2: float, angle: float) -> float:
    """The radius the map draws at this angle. Signed eccentricity, same as MissionMap."""
    a = (r1 + r2) / 2
    e = (r2 - r1) / (r2 + r1)
    return (a * (1 - e * e)) / (1 + e * math.cos(angle))


class TestMissionCatalog(unittest.TestCase):
    def setUp(self) -> None:
        self._previous = current_mission().id

    def tearDown(self) -> None:
        activate(self._previous)

    def test_flown_landings_are_the_six_apollo_touchdowns(self) -> None:
        flown = [spec for spec in CATALOG.values() if spec.group == "flown"]
        self.assertEqual([spec.id for spec in flown], [f"apollo-{n}" for n in (11, 12, 14, 15, 16, 17)])
        self.assertNotIn("apollo-13", CATALOG)
        for spec in flown:
            self.assertEqual(spec.origin, "leo")
            self.assertEqual(spec.destination, "moon")
            self.assertEqual(spec.crew, 3)
            self.assertTrue(spec.crew_names)
            self.assertTrue(spec.site)

    def test_later_expeditions_cover_mars_jupiter_and_further(self) -> None:
        groups = {spec.group for spec in CATALOG.values()}
        self.assertEqual(groups, {"flown", "mars", "jupiter", "expedition"})
        self.assertGreaterEqual(sum(spec.destination == "mars" for spec in CATALOG.values()), 2)
        self.assertGreaterEqual(sum(spec.destination == "jupiter" for spec in CATALOG.values()), 2)
        further = {spec.destination for spec in CATALOG.values() if spec.group == "expedition"}
        self.assertTrue({"venus", "mercury", "saturn", "pluto"} <= further)

    def test_unknown_mission_is_rejected(self) -> None:
        with self.assertRaises(KeyError):
            activate("apollo-13")

    def test_apollo_path_is_an_earth_centered_transfer(self) -> None:
        spec = activate("apollo-11")
        arrived = mission.trajectory(spec.launch + timedelta(days=mission._coast_days()))
        self.assertEqual(arrived["mission"], "Apollo 11")
        self.assertEqual(arrived["destination"], "moon")
        self.assertEqual(arrived["origin"], "leo")
        self.assertEqual(arrived["frame"], "earth")
        self.assertEqual(arrived["phase"], "arrived")
        self.assertEqual(arrived["crew"], 3)
        self.assertEqual(arrived["positions_au"]["earth"], [0.0, 0.0])
        sx, sy = arrived["positions_au"]["ship"]
        self.assertAlmostEqual(math.hypot(sx, sy) * AU_KM, 384_400, delta=500)
        self.assertGreater(arrived["one_way_light_delay_s"], 1.0)
        self.assertLess(arrived["one_way_light_delay_s"], 1.5)
        staged = mission.trajectory(None)
        self.assertEqual(staged["phase"], "ready")
        self.assertEqual(staged["progress"], 0)

    def test_ares_stays_the_live_mars_coast(self) -> None:
        spec = activate("ares")
        self.assertEqual(spec.destination, "mars")
        self.assertEqual(spec.spacecraft_mass_kg, 12_000)
        underway = mission.trajectory(spec.launch + timedelta(days=10))
        self.assertEqual(underway["frame"], "sun")
        self.assertEqual(underway["phase"], "transit")
        self.assertGreater(underway["progress"], 0)
        self.assertLess(underway["progress"], 0.2)

    def test_ship_lies_on_the_drawn_arc(self) -> None:
        parking = 6_678.137 / AU_KM
        moon = 384_400 / AU_KM
        routes = ((1.0, 1.523679), (1.0, 0.723332), (1.0, 0.387098), (parking, moon))
        for r1, r2 in routes:
            for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
                radius, angle = mission._ship(frac * 10, 10, r1, r2)
                self.assertGreaterEqual(angle, -1e-9)
                self.assertLessEqual(angle, math.pi + 1e-9)
                self.assertAlmostEqual(radius, _polar(r1, r2, angle), delta=max(1e-6, 1e-3 * abs(_polar(r1, r2, angle))))
            start_r, start_a = mission._ship(0, 10, r1, r2)
            end_r, end_a = mission._ship(10, 10, r1, r2)
            self.assertAlmostEqual(start_r, r1, delta=max(1e-6, 1e-4 * r1))
            self.assertAlmostEqual(end_r, r2, delta=max(1e-6, 1e-4 * r2))
            self.assertAlmostEqual(start_a, 0.0, places=5)
            self.assertAlmostEqual(end_a, math.pi, places=5)
