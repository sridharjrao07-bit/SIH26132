import os

def generate_summary(output_file):
    with open(output_file, 'w', encoding='utf-8') as out:
        out.write("# Krishi Bazaar (SIH26132) - Comprehensive Project Summary\n\n")
        out.write("This document summarizes all the work completed so far, including the database schema, ingestion pipelines, scraper fallbacks, the API layer, and the new marketplace pivot. It includes the complete source code for reference.\n\n")
        
        directories = ['db', 'ingestion', 'forecasting', 'notifications', 'app', 'templates', 'tests', 'docs', 'demo']
        root_files = ['pytest.ini', 'requirements.txt', '.env.example', 'agmarknetAPI']
        
        for d in directories:
            if not os.path.exists(d):
                continue
            for root, dirs, files in os.walk(d):
                if '__pycache__' in dirs:
                    dirs.remove('__pycache__')
                if 'migrations' in dirs:
                    dirs.sort()
                files.sort()
                for file in files:
                    if file.endswith(('.py', '.sql', '.md', '.txt', '.html', '.sh', '.yaml')):
                        if file in ['project_summary.md', 'SQL_APPLY.md']: # skip summary docs itself except SQL_APPLY
                            pass
                        file_path = os.path.join(root, file)
                        out.write(f"## File: {file_path.replace(os.sep, '/')}\n\n")
                        ext = file.split('.')[-1]
                        lang = ext if ext != 'txt' else 'text'
                        out.write(f"```{lang}\n")
                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                out.write(f.read())
                        except Exception as e:
                            out.write(f"Error reading file: {e}")
                        out.write(f"\n```\n\n")
        
        for file in root_files:
            if os.path.exists(file):
                out.write(f"## File: {file}\n\n")
                ext = file.split('.')[-1]
                lang = ext if '.' in file else 'text'
                out.write(f"```{lang}\n")
                try:
                    with open(file, 'r', encoding='utf-8') as f:
                        out.write(f.read())
                except Exception as e:
                    out.write(f"Error reading file: {e}")
                out.write(f"\n```\n\n")

if __name__ == "__main__":
    generate_summary('project_summary_with_code.md')
    print("Successfully generated project_summary_with_code.md")
