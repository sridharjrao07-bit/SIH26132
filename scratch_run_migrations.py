import os
import glob
from dotenv import load_dotenv
import psycopg2

def run_migrations():
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
    db_url = os.environ.get('SUPABASE_DB_URL')
    if not db_url:
        print("No SUPABASE_DB_URL found in .env")
        return

    print(f"Connecting to {db_url.split('@')[1]}...")
    
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cursor = conn.cursor()
        
        migration_dir = os.path.join(os.path.dirname(__file__), 'db', 'migrations')
        files = sorted(glob.glob(os.path.join(migration_dir, '*.sql')))
        files = [f for f in files if os.path.basename(f) >= '008']
        
        for file in files:
            print(f"Executing {os.path.basename(file)}...")
            with open(file, 'r', encoding='utf-8') as f:
                sql = f.read()
                cursor.execute(sql)
                
        print("All migrations applied successfully!")
        
    except Exception as e:
        print(f"Error during migration: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    run_migrations()
