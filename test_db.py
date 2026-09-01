import os
import sys
import urllib.request
import urllib.error
import json

def parse_env():
    env_vars = {}
    if os.path.exists('.env'):
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    env_vars[key.strip()] = val.strip()
    return env_vars

def test_supabase_connection():
    env = parse_env()
    url = env.get('SUPABASE_URL')
    key = env.get('SUPABASE_ANON_KEY')
    
    if not url or 'your-project' in url:
        print("[ERROR] SUPABASE_URL is missing or contains placeholder 'your-project'.")
        print("Please edit .env to add your actual project URL.")
        sys.exit(1)
        
    if not key or 'your-anon-key' in key:
        print("[ERROR] SUPABASE_ANON_KEY is missing or contains placeholder.")
        print("Please edit .env to add your actual anon key.")
        sys.exit(1)
        
    print(f"Testing connection to Supabase API at: {url}")
    
    req = urllib.request.Request(f"{url}/rest/v1/markets?select=id&limit=1")
    req.add_header('apikey', key)
    req.add_header('Authorization', f'Bearer {key}')
    
    try:
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                print("[SUCCESS] Successfully connected to Supabase!")
                data = json.loads(response.read().decode())
                print("[SUCCESS] Schema migrations (Stage 1) appear to be applied correctly (found 'markets' table)!")
            else:
                print(f"[ERROR] Connected, but received status code {response.status}")
    except urllib.error.URLError as e:
        print(f"[ERROR] Connection failed: {e.reason}")
        if hasattr(e, 'read'):
            try:
                err_body = e.read().decode('utf-8', errors='ignore')
                print("Error Details:", err_body)
            except:
                pass
                
if __name__ == '__main__':
    test_supabase_connection()
