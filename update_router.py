import sys

with open('app/routers/direct.py', 'r', encoding='utf-8') as f:
    code = f.read()

helpers_code = """
from ingestion.retail_loader import latest_retail_price

def _load_chain_profiles(supabase: Client) -> Dict[str, ValueChain]:
    try:
        resp = supabase.table("value_chain_profiles").select("*").eq("is_active", True).eq("channel", "traditional").execute()
        chains = {}
        for row in resp.data:
            if row.get("commodity_id"):
                stages = [Stage.from_dict(s) for s in row.get("stages", [])]
                if stages:
                    vc = ValueChain(stages, name="db_profile")
                    if row.get("margin_scale") is not None:
                        vc = vc.scaled(float(row["margin_scale"]))
                    chains[row["commodity_id"]] = vc
        return chains
    except Exception as e:
        structlog.get_logger().error("failed_to_load_chain_profiles", error=str(e))
        return {}

def _resolve_retail_price(supabase: Client, commodity_id: Optional[str], category: str, provided_price: Optional[float], district: str = "Maharashtra") -> float:
    if provided_price is not None:
        return provided_price
    commodity_name = category.capitalize() # fallback
    if commodity_id:
        try:
            res = supabase.table("commodities").select("name_en").eq("id", commodity_id).limit(1).execute()
            if res.data:
                commodity_name = res.data[0]["name_en"]
        except Exception:
            pass
    try:
        price, _, _ = latest_retail_price(commodity_name, "Maharashtra")
        return price
    except Exception as e:
        raise HTTPException(422, f"Could not fetch retail price for {commodity_name}: {e}")
"""

code = code.replace("def _to_plan_config(req: PlanRequest) -> DirectConfig:", 
    "def _to_plan_config(req: PlanRequest, supabase: Client) -> DirectConfig:")

code = code.replace("        enforce_grade=req.enforce_grade,", 
    "        enforce_grade=req.enforce_grade,\n        traditional_chains=_load_chain_profiles(supabase),")

code = code.replace("# ─────────────────────────────────────────────────────────────────────────────\n# Helpers\n# ─────────────────────────────────────────────────────────────────────────────", 
    "# ─────────────────────────────────────────────────────────────────────────────\n# Helpers\n# ─────────────────────────────────────────────────────────────────────────────\n" + helpers_code)

code = code.replace("def consumer_rupee(req: RupeeRequest, supabase: Client = Depends(get_supabase)) -> Dict[str, Any]:", 
"""def consumer_rupee(req: RupeeRequest, supabase: Client = Depends(get_supabase)) -> Dict[str, Any]:
    req.retail_price = _resolve_retail_price(supabase, req.commodity_id, req.category, req.retail_price)""")

code = code.replace("def fair_price(req: FairPriceRequest, supabase: Client = Depends(get_supabase)) -> Dict[str, Any]:", 
"""def fair_price(req: FairPriceRequest, supabase: Client = Depends(get_supabase)) -> Dict[str, Any]:
    req.retail_price = _resolve_retail_price(supabase, req.commodity_id, req.category, req.retail_price)""")

code = code.replace("    if not req.lots or not req.demands:\n        raise HTTPException(422, \"at least one lot and one demand are required\")\n    try:\n        plan = plan_direct_channel(_to_lots(req), _to_demands(req), _to_plan_config(req))", 
"""    if not req.lots or not req.demands:
        raise HTTPException(422, "at least one lot and one demand are required")
    for d in req.demands:
        d.retail_price_per_qtl = _resolve_retail_price(supabase, d.commodity_id, d.category, d.retail_price_per_qtl)
    try:
        plan = plan_direct_channel(_to_lots(req), _to_demands(req), _to_plan_config(req, supabase))""")

code = code.replace("    plan = plan_direct_channel(_to_lots(req.plan), _to_demands(req.plan), _to_plan_config(req.plan))", 
"""    for d in req.plan.demands:
        d.retail_price_per_qtl = _resolve_retail_price(supabase, d.commodity_id, d.category, d.retail_price_per_qtl, req.district)
    plan = plan_direct_channel(_to_lots(req.plan), _to_demands(req.plan), _to_plan_config(req.plan, supabase))""")

# direct_config
code = code.replace("def direct_config(category: str = Query(\"vegetable\"), supabase: Client = Depends(get_supabase)) -> Dict[str, Any]:\n    \"\"\"Publish the chain model and rate card the engine is using.",
"""def direct_config(category: str = Query("vegetable"), supabase: Client = Depends(get_supabase)) -> Dict[str, Any]:
    \"\"\"Publish the chain model and rate card the engine is using.""")

code = code.replace("    trad = default_traditional_chain(category)\n    direct = default_direct_chain(category)",
"""    chains = _load_chain_profiles(supabase)
    # just pick first for the category if any, else default
    trad = next((v for k,v in chains.items() if v.category == category), None)
    if not trad:
        trad = default_traditional_chain(category)
    direct = default_direct_chain(category)""")

with open('app/routers/direct.py', 'w', encoding='utf-8') as f:
    f.write(code)

