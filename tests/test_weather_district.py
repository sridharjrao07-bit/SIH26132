from forecasting.engine import ForecastEngine


class MockBuilder:
    def __init__(self, data):
        self.data = data

    def select(self, *args, **kwargs):
        return self

    def gte(self, *args, **kwargs):
        return self

    def eq(self, column, value):
        if column == "market_id":
            self.data = [d for d in self.data if d.get("market_id") == value]
        return self

    def order(self, *args, **kwargs):
        return self

    def range(self, *args, **kwargs):
        if args[0] == 0:
            return self
        return MockBuilder([])

    def execute(self):
        class MockData:
            def __init__(self, d):
                self.data = d

        return MockData(self.data)


def test_weather_district_filtering(monkeypatch):
    weather_data = [
        {"market_id": "M1", "observation_date": "2026-09-01", "rain_mm": 50.0},
        {"market_id": "M2", "observation_date": "2026-09-01", "rain_mm": 0.0},
    ]
    prices_data = []
    for i in range(10):
        d = f"2026-09-{i + 1:02d}"
        prices_data.append(
            {
                "market_id": "M1",
                "commodity_id": "C1",
                "arrival_date": d,
                "modal_price": 1000.0,
                "source": "manual",
            }
        )
        prices_data.append(
            {
                "market_id": "M2",
                "commodity_id": "C1",
                "arrival_date": d,
                "modal_price": 1000.0,
                "source": "manual",
            }
        )

    class MockSupabase:
        def table(self, name):
            if name == "prices":
                return MockBuilder(prices_data)
            elif name == "weather_daily":
                return MockBuilder(weather_data)
            elif name == "events":
                return MockBuilder([])
            elif name == "commodities":
                return MockBuilder([{"id": "C1", "sanity_min": 500, "sanity_max": 2000}])
            elif name == "forecasts":

                class MockUpsert:
                    def upsert(self, *args, **kwargs):
                        return MockBuilder([])

                return MockUpsert()
            return MockBuilder([])

    engine = ForecastEngine(MockSupabase())

    # We want to patch build_feature_matrix to assert it gets the right weather
    called_weather = {}

    import forecasting.features

    orig_build = forecasting.features.build_feature_matrix

    def mock_build(history, weather, events, district_prices, target_commodity_id):
        # We need a way to know which market this is for.
        # It's M1 if history has M1. Wait, history rows might not have market_id since we build_daily_series.
        # No, history is the raw rows from fetch_history. Wait, features takes history.
        m_id = history[0]["market_id"] if "market_id" in history[0] else "unknown"
        called_weather[m_id] = weather
        return orig_build(history, weather, events, district_prices, target_commodity_id)

    monkeypatch.setattr(forecasting.features, "build_feature_matrix", mock_build)

    monkeypatch.setattr(
        forecasting.engine,
        "get_settings",
        lambda: type("Settings", (), {"forecast_model": "feature_ols"})(),
    )

    engine.run()

    assert "M1" in called_weather
    assert "M2" in called_weather

    w1 = called_weather["M1"]
    w2 = called_weather["M2"]

    assert len(w1) == 1
    assert w1[0]["rain_mm"] == 50.0

    assert len(w2) == 1
    assert w2[0]["rain_mm"] == 0.0
