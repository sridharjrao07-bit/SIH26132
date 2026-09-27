import pg8000.dbapi, urllib.parse, ssl, os

db_url = os.environ.get('SUPABASE_DB_URL')
url = urllib.parse.urlparse(db_url)
ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE
conn = pg8000.dbapi.connect(user=url.username, password=url.password, host=url.hostname, port=url.port, database=url.path[1:], ssl_context=ssl_context)
conn.autocommit = False
cur = conn.cursor()

# Get onion uuid
cur.execute("SELECT id FROM public.commodities WHERE lower(name_en) = 'onion' LIMIT 1")
onion_uuid = cur.fetchone()[0]

# Get a user_id to spoof authentication
cur.execute("SELECT id FROM public.user_profiles LIMIT 1")
user_id_row = cur.fetchone()
if not user_id_row:
    print("No users found. Creating a temporary user.")
    cur.execute("INSERT INTO public.user_profiles (id, phone, name) VALUES (gen_random_uuid(), '+919999999999', 'Test User') RETURNING id")
    user_id = cur.fetchone()[0]
else:
    user_id = user_id_row[0]

print(f"onion_uuid: {onion_uuid}")
print(f"Using user_id: {user_id}")

try:
    import json
    claims = json.dumps({"sub": str(user_id), "role": "authenticated"})
    cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (claims,))
    
    cur.execute("select id from public.consumer_node_upsert('Test RWA', 'rwa', 'Nashik')")
    consumer_node_id = cur.fetchone()[0]
    print(f"consumer_node_id: {consumer_node_id}")

    cur.execute(f"select id from public.group_buy_create('{onion_uuid}', now() + interval '2 days', 100, 90)")
    group_buy_id = cur.fetchone()[0]
    print(f"group_buy_id: {group_buy_id}")

    cur.execute(f"select public.group_buy_join('{group_buy_id}', 20.0)")
    join_res = cur.fetchone()[0]
    print(f"group_buy_join returned: {join_res}")
except Exception as e:
    print(f"Error executing write path: {e}")

cur.close()
conn.close()
