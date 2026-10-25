from __future__ import annotations

from schema import VoyageRequest, VoyageResult, parse_voyage_request, parse_voyage_result

from voyage.physics import consumables_kg, hohmann_delta_v_m_s, rocket_propellant_kg, route_elements
from voyage.windows import launch_window_utc


def voyage_calculate(request: VoyageRequest | dict) -> VoyageResult:
    """Plain-physics one-way transfer. Travel time is the schema.ROUTES check value."""
    if not isinstance(request, VoyageRequest):
        request = parse_voyage_request(request)
    r1, r2, mu, days = route_elements(request.origin, request.destination)
    delta_v = hohmann_delta_v_m_s(r1, r2, mu)
    propellant = rocket_propellant_kg(request.spacecraft_mass_kg, delta_v, request.isp_s)
    oxygen, water, food = consumables_kg(request.crew, days)
    return parse_voyage_result(
        {
            "origin": request.origin,
            "destination": request.destination,
            "spacecraft_mass_kg": request.spacecraft_mass_kg,
            "isp_s": request.isp_s,
            "crew": request.crew,
            "delta_v_m_s": delta_v,
            "travel_time_days": days,
            "propellant_kg": propellant,
            "launch_window_utc": launch_window_utc(request.origin, request.destination),
            "oxygen_kg": oxygen,
            "water_kg": water,
            "food_kg": food,
        }
    )
