import asyncio, os
from ingestion.dca_retail import DcaRetailAdapter

async def main():
    api_key = os.environ.get('DATA_GOV_IN_API_KEY')
    adapter = DcaRetailAdapter(api_key=api_key)
    rows = await adapter.fetch_retail()
    for r in rows[:5]:
        print(r)

if __name__ == '__main__':
    asyncio.run(main())
