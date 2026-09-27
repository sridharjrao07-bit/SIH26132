import re

with open('app/routers/direct.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Fix consumer_rupee
code = re.sub(
    r'def consumer_rupee\(req: RupeeRequest\) -> Dict\[str, Any\]:',
    r'def consumer_rupee(req: RupeeRequest, supabase: Client = Depends(get_supabase)) -> Dict[str, Any]:',
    code
)

# Fix fair_price
code = re.sub(
    r'def fair_price\(req: FairPriceRequest\) -> Dict\[str, Any\]:',
    r'def fair_price(req: FairPriceRequest, supabase: Client = Depends(get_supabase)) -> Dict[str, Any]:',
    code
)

# Fix plan_direct
code = re.sub(
    r'def plan_direct\(req: PlanRequest\) -> Dict\[str, Any\]:',
    r'def plan_direct(req: PlanRequest, supabase: Client = Depends(get_supabase)) -> Dict[str, Any]:',
    code
)

# Fix direct_config
code = re.sub(
    r'def direct_config\(category: str = Query\("vegetable"\)\) -> Dict\[str, Any\]:',
    r'def direct_config(category: str = Query("vegetable"), supabase: Client = Depends(get_supabase)) -> Dict[str, Any]:',
    code
)

with open('app/routers/direct.py', 'w', encoding='utf-8') as f:
    f.write(code)

