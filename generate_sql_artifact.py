import os
import glob

def generate_sql_artifact():
    artifact_path = r"C:\Users\sridh\.gemini\antigravity-ide\brain\8b0d4197-0cbb-468e-8dd3-b8a91acddedd\arena_database_migrations.md"
    migration_dir = os.path.join(os.path.dirname(__file__), 'db', 'migrations')
    files = sorted(glob.glob(os.path.join(migration_dir, '*.sql')))
    
    with open(artifact_path, 'w', encoding='utf-8') as out:
        out.write("# Arena Database SQL Migrations\n\n")
        out.write("Here are the SQL scripts you need to apply to the database provided by Arena. ")
        out.write("As per `docs/SQL_APPLY.md`, **paste one file at a time**, run it in the Supabase SQL editor, confirm success, and then move to the next.\n\n")
        
        out.write("> [!IMPORTANT]\n")
        out.write("> If your Arena database is **brand new**, start from `001_schema.sql` and run all of them.\n")
        out.write("> If you have already applied the previous migrations (up to `007`), start from **`008_marketplace.sql`**.\n\n")
        
        for file in files:
            basename = os.path.basename(file)
            out.write(f"## {basename}\n\n")
            out.write(f"```sql\n")
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    out.write(f.read().strip())
            except Exception as e:
                out.write(f"-- Error reading file: {e}")
            out.write(f"\n```\n\n")

if __name__ == "__main__":
    generate_sql_artifact()
