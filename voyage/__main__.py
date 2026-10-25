from schema import parse_voyage_request
from voyage import voyage_calculate


def main() -> None:
    mars = voyage_calculate(
        parse_voyage_request(
            {
                "origin": "earth",
                "destination": "mars",
                "spacecraft_mass_kg": 10000,
                "isp_s": 300,
                "crew": 4,
            }
        )
    )
    moon = voyage_calculate(
        parse_voyage_request(
            {
                "origin": "leo",
                "destination": "moon",
                "spacecraft_mass_kg": 10000,
                "isp_s": 300,
                "crew": 4,
            }
        )
    )
    assert abs(mars.travel_time_days - 259) < 1e-9
    assert abs(moon.travel_time_days - 5) < 1e-9
    assert mars.delta_v_m_s > 5000
    assert moon.delta_v_m_s > 3000
    print(mars.to_dict())
    print(moon.to_dict())


if __name__ == "__main__":
    main()
