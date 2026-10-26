"""Missions the crew can fly. Choosing one sets the ship and the path.

Flown entries are the six Apollo landings (Apollo 13 never landed, so it is not here).
Mars and Jupiter entries are later expeditions. The rest are further-out trips to real places.
Apollo leaves low Earth orbit for the Moon. Everything else is a direct Hohmann from Earth.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from schema import ROOT

SELECTION = ROOT / "queue" / "mission.json"


@dataclass(frozen=True)
class MissionSpec:
    id: str
    name: str
    group: str  # flown | mars | jupiter | expedition
    blurb: str
    site: str
    crew_names: str
    launch: datetime
    origin: str
    destination: str
    spacecraft_mass_kg: int
    isp_s: int
    crew: int

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "group": self.group,
            "blurb": self.blurb,
            "site": self.site,
            "crew_names": self.crew_names,
            "year": self.launch.year,
            "origin": self.origin,
            "destination": self.destination,
            "crew": self.crew,
            "spacecraft_mass_kg": self.spacecraft_mass_kg,
            "isp_s": self.isp_s,
            "launch_utc": self.launch.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# Apollo dry masses are the CSM plus lunar module, without propellant. J missions (15–17)
# flew a heavier lander and a rover. 314 seconds is the service propulsion engine.
_APOLLO = dict(origin="leo", destination="moon", crew=3, isp_s=314, group="flown")

CATALOG: dict[str, MissionSpec] = {
    spec.id: spec
    for spec in (
        MissionSpec(
            id="apollo-11",
            name="Apollo 11",
            blurb="First landing on the Moon. July 1969.",
            site="Sea of Tranquility",
            crew_names="Armstrong, Collins, Aldrin",
            launch=_utc(1969, 7, 16, 13, 32),
            spacecraft_mass_kg=15_200,
            **_APOLLO,
        ),
        MissionSpec(
            id="apollo-12",
            name="Apollo 12",
            blurb="Pinpoint landing beside Surveyor 3. November 1969.",
            site="Ocean of Storms",
            crew_names="Conrad, Gordon, Bean",
            launch=_utc(1969, 11, 14, 16, 22),
            spacecraft_mass_kg=15_200,
            **_APOLLO,
        ),
        MissionSpec(
            id="apollo-14",
            name="Apollo 14",
            blurb="Fra Mauro, the site Apollo 13 never reached. February 1971.",
            site="Fra Mauro",
            crew_names="Shepard, Roosa, Mitchell",
            launch=_utc(1971, 1, 31, 21, 3),
            spacecraft_mass_kg=15_200,
            **_APOLLO,
        ),
        MissionSpec(
            id="apollo-15",
            name="Apollo 15",
            blurb="First rover, at Hadley Rille. August 1971.",
            site="Hadley–Apennine",
            crew_names="Scott, Worden, Irwin",
            launch=_utc(1971, 7, 26, 13, 34),
            spacecraft_mass_kg=16_400,
            **_APOLLO,
        ),
        MissionSpec(
            id="apollo-16",
            name="Apollo 16",
            blurb="Descartes highlands. April 1972.",
            site="Descartes Highlands",
            crew_names="Young, Mattingly, Duke",
            launch=_utc(1972, 4, 16, 17, 54),
            spacecraft_mass_kg=16_400,
            **_APOLLO,
        ),
        MissionSpec(
            id="apollo-17",
            name="Apollo 17",
            blurb="Last time anyone landed on the Moon. December 1972.",
            site="Taurus–Littrow",
            crew_names="Cernan, Evans, Schmitt",
            launch=_utc(1972, 12, 7, 5, 33),
            spacecraft_mass_kg=16_400,
            **_APOLLO,
        ),
        MissionSpec(
            id="ares",
            name="Ares",
            group="mars",
            blurb="Crewed landing at Jezero. Already on the coast.",
            site="Jezero Crater",
            crew_names="",
            launch=_utc(2026, 6, 12),
            origin="earth",
            destination="mars",
            spacecraft_mass_kg=12_000,
            isp_s=450,
            crew=4,
        ),
        MissionSpec(
            id="olympus",
            name="Olympus",
            group="mars",
            blurb="Six people to the scarp of Olympus Mons.",
            site="Olympus Mons",
            crew_names="",
            launch=_utc(2039, 7, 25),
            origin="earth",
            destination="mars",
            spacecraft_mass_kg=28_000,
            isp_s=450,
            crew=6,
        ),
        MissionSpec(
            id="valhalla",
            name="Valhalla",
            group="jupiter",
            blurb="A base on Callisto, outside the worst of Jupiter's radiation.",
            site="Valhalla, Callisto",
            crew_names="",
            launch=_utc(2061, 2, 18),
            origin="earth",
            destination="jupiter",
            spacecraft_mass_kg=42_000,
            isp_s=900,
            crew=4,
        ),
        MissionSpec(
            id="conamara",
            name="Conamara",
            group="jupiter",
            blurb="Onto Europa's ice, over the ocean.",
            site="Conamara Chaos, Europa",
            crew_names="",
            launch=_utc(2074, 10, 9),
            origin="earth",
            destination="jupiter",
            spacecraft_mass_kg=38_000,
            isp_s=900,
            crew=4,
        ),
        MissionSpec(
            id="cloud-nine",
            name="Cloud Nine",
            group="expedition",
            blurb="A habitat in Venus's clouds, where the air is temperate.",
            site="Venus cloud deck",
            crew_names="",
            launch=_utc(2042, 6, 3),
            origin="earth",
            destination="venus",
            spacecraft_mass_kg=18_000,
            isp_s=450,
            crew=4,
        ),
        MissionSpec(
            id="icarus",
            name="Icarus",
            group="expedition",
            blurb="South pole of Mercury, in the shadow of Chao Meng-Fu.",
            site="Chao Meng-Fu, Mercury",
            crew_names="",
            launch=_utc(2046, 3, 21),
            origin="earth",
            destination="mercury",
            spacecraft_mass_kg=14_000,
            isp_s=450,
            crew=3,
        ),
        MissionSpec(
            id="kraken",
            name="Kraken",
            group="expedition",
            blurb="Splashdown in Kraken Mare, a methane sea on Titan.",
            site="Kraken Mare, Titan",
            crew_names="",
            launch=_utc(2068, 8, 14),
            origin="earth",
            destination="saturn",
            spacecraft_mass_kg=36_000,
            isp_s=850,
            crew=4,
        ),
        MissionSpec(
            id="persephone",
            name="Persephone",
            group="expedition",
            blurb="The long coast, to the ice plains of Pluto.",
            site="Sputnik Planitia, Pluto",
            crew_names="",
            launch=_utc(2088, 1, 19),
            origin="earth",
            destination="pluto",
            spacecraft_mass_kg=50_000,
            isp_s=950,
            crew=4,
        ),
    )
}


def _load() -> MissionSpec:
    if SELECTION.exists():
        try:
            mission_id = json.loads(SELECTION.read_text()).get("id")
        except (OSError, json.JSONDecodeError):
            mission_id = None
        if mission_id in CATALOG:
            return CATALOG[mission_id]
    return CATALOG["ares"]


_current: MissionSpec = _load()


def current_mission() -> MissionSpec:
    return _current


def catalog() -> list[dict]:
    return [spec.public() for spec in CATALOG.values()]


def activate(mission_id: str) -> MissionSpec:
    """Make this the ship the map, the supplies, and the flight all follow."""
    global _current
    if mission_id not in CATALOG:
        known = ", ".join(CATALOG)
        raise KeyError(f"No mission {mission_id!r}. Known: {known}")
    _current = CATALOG[mission_id]
    SELECTION.parent.mkdir(parents=True, exist_ok=True)
    tmp = SELECTION.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"id": mission_id}) + "\n")
    os.replace(tmp, SELECTION)
    return _current
