@echo off
set FARMER_JWT=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhdWQiOiJhdXRoZW50aWNhdGVkIiwicm9sZSI6ImF1dGhlbnRpY2F0ZWQiLCJzdWIiOiJlYmYzYjkwNi1lZTFlLTRjMzctYWRjMC1jYjhjN2U5NGUyNDciLCJlbWFpbCI6ImFkbWluQGtyaXNoaWJhemFhci5sb2NhbCIsImlhdCI6MTc4ODM2OTI5OSwiZXhwIjoxNzg4Mzc2NDk5fQ.-ZiE71M2R8bAhf0wVq-1MEFg3iJPLXINnM460FqpnIE
echo -- GET /me/ --
curl.exe -sS -i -H "Authorization: Bearer %FARMER_JWT%" "http://127.0.0.1:8000/api/v1/me/"
echo.
echo.
echo -- POST /lots/ --
curl.exe -sS -i -H "Authorization: Bearer %FARMER_JWT%" -H "Content-Type: application/json" -d "{\"commodity_id\":\"6ed43180-9896-4b0c-96f7-922143b5aa08\",\"market_id\":\"f5557697-afd2-4406-a709-4fe530ce1998\",\"quantity_qtl\":20,\"grade\":\"General\",\"asking_price\":1600}" "http://127.0.0.1:8000/api/v1/lots/" > curl_out.txt
type curl_out.txt
echo.
