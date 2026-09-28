import os
import sys
from pathlib import Path

# Bootstrap env vars so pydantic-settings doesn't crash
os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "placeholder")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "placeholder")
os.environ.setdefault("SUPABASE_JWT_SECRET", "ci-placeholder-jwt-secret-32b-min")
os.environ.setdefault("SUPABASE_DB_URL", "postgresql://p@db.placeholder.supabase.co:5432/postgres")
os.environ.setdefault("DATA_GOV_IN_API_KEY", "placeholder")
os.environ.setdefault("RUN_SCHEDULER", "0")
os.environ.setdefault("RATE_LIMIT_ENABLED", "0")
os.environ.setdefault("APP_ENV", "development")

from app.main import app


def generate_markdown() -> str:
    openapi = app.openapi()
    lines = []
    lines.append("## Endpoints")
    lines.append("")
    lines.append("| Method | Path | Summary |")
    lines.append("|---|---|---|")

    # We want a stable ordering. Sort by path, then method.
    for path, methods in sorted(openapi.get("paths", {}).items()):
        for method, details in sorted(methods.items()):
            summary = details.get("summary", "")
            lines.append(f"| {method.upper()} | `{path}` | {summary} |")

    lines.append("")
    return "\n".join(lines)

def update_api_md(check_only: bool = False):
    project_root = Path(__file__).resolve().parent.parent
    api_md_path = project_root / "docs" / "API.md"

    with open(api_md_path, "r", encoding="utf-8") as f:
        content = f.read()

    start_marker = "<!-- BEGIN GENERATED: endpoint reference — do not edit; run `make docs` -->"
    end_marker = "<!-- END GENERATED -->"

    if start_marker not in content or end_marker not in content:
        print("Markers not found in docs/API.md", file=sys.stderr)
        sys.exit(1)

    start_idx = content.find(start_marker) + len(start_marker)
    end_idx = content.find(end_marker)

    new_content = content[:start_idx] + "\n\n" + generate_markdown() + "\n" + content[end_idx:]

    if check_only:
        if content != new_content:
            print("docs/API.md is out of sync. Please run 'make docs'", file=sys.stderr)
            sys.exit(1)
    else:
        with open(api_md_path, "w", encoding="utf-8") as f:
            f.write(new_content)

if __name__ == "__main__":
    check_mode = len(sys.argv) > 1 and sys.argv[1] == "--check"
    update_api_md(check_only=check_mode)
    if not check_mode:
        print("Updated docs/API.md")
