import re
from pathlib import Path

from app.main import app
from scripts.generate_api_docs import update_api_md


def test_api_md_sync():
    """Ensure docs/API.md matches the generated output."""
    # This will exit(1) if they do not match
    try:
        update_api_md(check_only=True)
    except SystemExit as e:
        if e.code != 0:
            raise AssertionError("docs/API.md is out of sync. Please run 'make docs'")

def test_api_contract_paths():
    """Ensure all endpoints mentioned in API_CONTRACT.md exist."""
    project_root = Path(__file__).resolve().parent.parent
    contract_path = project_root / "frontend_handoff" / "API_CONTRACT.md"
    content = contract_path.read_text(encoding="utf-8")
    
    # Extract paths mentioned in table formats like `/api/v1/something`
    # Also handle `{id}` parameters.
    matches = re.findall(r'`(/api/v1/[a-zA-Z0-9_/{}-]+)[`|]', content)
    
    openapi = app.openapi()
    actual_paths = openapi.get("paths", {}).keys()
    
    missing = []
    for m in matches:
        # Some exceptions in the contract text
        if "/*" in m:
            continue
        
        # Normalize `/{id}` from the contract to match any OpenAPI path parameter.
        pattern = m.replace("{id}", "{[^}]+}").replace("{payment_id}", "{[^}]+}")
        
        found = False
        for actual in actual_paths:
            if re.match(f"^{pattern}$", actual):
                found = True
                break
        
        if not found:
            missing.append(m)
            
            
    if missing:
        raise AssertionError(f"Endpoints documented in API_CONTRACT.md but missing in app.openapi(): {set(missing)}")
    
    # bump this if you intentionally remove documented endpoints
    assert len(set(matches)) >= 25, f"Expected at least 25 unique matches, found {len(set(matches))}"
