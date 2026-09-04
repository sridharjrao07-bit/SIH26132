"""
Seed script to ingest dummy data for evaluation.
Wraps scripts/ingest_csv.py for a 'zero-friction' setup.
"""
import asyncio
import os
import sys

# Ensure the app package is discoverable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.ingest_csv import main

if __name__ == "__main__":
    print("Starting database seed...")
    try:
        asyncio.run(main())
        print("Seed data successfully populated.")
    except Exception as e:
        print(f"Failed to seed data: {e}")
        sys.exit(1)
