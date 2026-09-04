import os, sys, json, time, subprocess
from pathlib import Path
from supabase import create_client, Client

env_text = Path(".env").read_text(encoding="utf-8")
env_vars = {}
for line in env_text.splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env_vars[k.strip()] = v.strip().strip("'\"")

supabase_url = env_vars.get("SUPABASE_URL")
supabase_key = env_vars.get("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

email = f"farmer_{int(time.time())}@example.com"
password = "TestPassword123!"

print(f"Creating user {email}...")
res = supabase.auth.admin.create_user({"email": email, "password": password, "email_confirm": True})
user_id = res.user.id
print(f"Created user with ID: {user_id}")

time.sleep(2)
profile_res = supabase.table("user_profiles").select("*").eq("id", user_id).execute()
print(f"User profile in DB: {profile_res.data}")

mint_cmd = [sys.executable, "demo/mint_admin_token.py", "--sub", user_id, "--hours", "2"]
res = subprocess.run(mint_cmd, capture_output=True, text=True, encoding="utf-8")
jwt = res.stdout.strip().splitlines()[1].strip()
print("Minted JWT locally (hidden)")

env_copy = os.environ.copy()
env_copy["RUN_SCHEDULER"] = "0"
env_copy["RATE_LIMIT_ENABLED"] = "0"
print("Starting Uvicorn...")
uvicorn_proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"], env=env_copy)
time.sleep(5)

def run_curl_bat(name, bat_content):
    Path(name).write_text(bat_content, encoding="utf-8")
    return subprocess.run(["cmd.exe", "/c", name], capture_output=True, text=True, encoding="utf-8").stdout

bat_script = f"""@echo off
set FARMER_JWT={jwt}
echo -- GET /me/ --
curl.exe -sS -i -H "Authorization: Bearer %FARMER_JWT%" "http://127.0.0.1:8000/api/v1/me/"
echo.
echo.
echo -- POST /lots/ --
curl.exe -sS -i -H "Authorization: Bearer %FARMER_JWT%" -H "Content-Type: application/json" -d "{{\\"commodity_id\\":\\"6ed43180-9896-4b0c-96f7-922143b5aa08\\",\\"market_id\\":\\"f5557697-afd2-4406-a709-4fe530ce1998\\",\\"quantity_qtl\\":20,\\"grade\\":\\"General\\",\\"asking_price\\":1600}}" "http://127.0.0.1:8000/api/v1/lots/" > curl_out.txt
type curl_out.txt
echo.
"""
out1 = run_curl_bat("run_curls.bat", bat_script)
Path("out1.txt").write_text(out1, encoding="utf-8")

out = Path("curl_out.txt").read_text(encoding="utf-8")
lines = out.strip().splitlines()
body = lines[-1]
lot_id = None
try:
    data = json.loads(body)
    lot_id = data.get("id")
except Exception as e:
    pass

if lot_id:
    print(f"Parsed lot ID: {lot_id}")
    bat_script2 = f"""@echo off
set FARMER_JWT={jwt}
echo -- GET /lots/{lot_id}/advice --
curl.exe -sS -i -H "Authorization: Bearer %FARMER_JWT%" "http://127.0.0.1:8000/api/v1/lots/{lot_id}/advice"
echo.
echo.
echo -- GET /lots/{lot_id}/matches --
curl.exe -sS -i -H "Authorization: Bearer %FARMER_JWT%" "http://127.0.0.1:8000/api/v1/lots/{lot_id}/matches"
echo.
"""
    out2 = run_curl_bat("run_curls2.bat", bat_script2)
    Path("out2.txt").write_text(out2, encoding="utf-8")
    print("Wrote out2.txt")
else:
    print("Could not parse lot_id from:", body)

uvicorn_proc.terminate()
uvicorn_proc.wait()
print("Uvicorn terminated.")
