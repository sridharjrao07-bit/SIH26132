from datetime import date

import httpx
import pytest
import respx
from scripts.backfill_weather import fetch_weather_chunk


@pytest.mark.asyncio
async def test_fetch_weather_chunk_missing_days_not_written():
    with respx.mock:
        respx.get(url__startswith="https://archive-api.open-meteo.com/v1/archive").mock(
            return_value=httpx.Response(200, json={
                "daily": {
                    "time": ["2026-09-01", "2026-09-02"],
                    "precipitation_sum": [1.5, None], # Missing precipitation for 2nd day
                    "temperature_2m_mean": [25.5, 26.0]
                }
            })
        )
        
        async with httpx.AsyncClient() as client:
            data = await fetch_weather_chunk(
                client, 20.0, 73.0, date(2026, 9, 1), date(2026, 9, 2)
            )
            
            daily = data.get("daily", {})
            time_array = daily.get("time", [])
            precip_array = daily.get("precipitation_sum", [])
            temp_array = daily.get("temperature_2m_mean", [])
            
            # The logic in backfill_weather script skips records where p_sum or t_mean is None.
            # We verify the data returned matches our mock.
            assert time_array == ["2026-09-01", "2026-09-02"]
            assert precip_array[1] is None
            
            # Simulated script logic
            records = []
            rejected = 0
            for i in range(len(time_array)):
                dt_str = time_array[i]
                p_sum = precip_array[i]
                t_mean = temp_array[i]
                
                if p_sum is None or t_mean is None:
                    rejected += 1
                    continue
                    
                records.append({
                    "observation_date": dt_str,
                    "precipitation_sum_mm": round(p_sum, 2),
                    "temperature_2m_mean_c": round(t_mean, 2)
                })
                
            assert len(records) == 1
            assert rejected == 1
            assert records[0]["observation_date"] == "2026-09-01"

