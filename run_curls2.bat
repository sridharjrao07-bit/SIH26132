@echo off
set FARMER_JWT=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhdWQiOiJhdXRoZW50aWNhdGVkIiwicm9sZSI6ImF1dGhlbnRpY2F0ZWQiLCJzdWIiOiJlYmYzYjkwNi1lZTFlLTRjMzctYWRjMC1jYjhjN2U5NGUyNDciLCJlbWFpbCI6ImFkbWluQGtyaXNoaWJhemFhci5sb2NhbCIsImlhdCI6MTc4ODM2OTI5OSwiZXhwIjoxNzg4Mzc2NDk5fQ.-ZiE71M2R8bAhf0wVq-1MEFg3iJPLXINnM460FqpnIE
echo -- GET /lots/bb5c60d3-2f53-4ae7-b223-0377f20b583c/advice --
curl.exe -sS -i -H "Authorization: Bearer %FARMER_JWT%" "http://127.0.0.1:8000/api/v1/lots/bb5c60d3-2f53-4ae7-b223-0377f20b583c/advice"
echo.
echo.
echo -- GET /lots/bb5c60d3-2f53-4ae7-b223-0377f20b583c/matches --
curl.exe -sS -i -H "Authorization: Bearer %FARMER_JWT%" "http://127.0.0.1:8000/api/v1/lots/bb5c60d3-2f53-4ae7-b223-0377f20b583c/matches"
echo.
