import os
import sys
import asyncio
from dotenv import load_dotenv

load_dotenv(r"c:\Users\Kyohyun\Desktop\Study\CodingStudy\SKT_Fly_ai\ChefYam\IRI-ON\be\.env")
sys.path.append(r"c:\Users\Kyohyun\Desktop\Study\CodingStudy\SKT_Fly_ai\ChefYam\IRI-ON\be")

from services.mcp_clients_manager import init_mcp_manager
import json

async def main():
    manager = await init_mcp_manager()
    server = manager.get_client("k-mfds-fooddb")
    for t in server.tool_info:
        if t.name == "searchFoodNutrition":
            print(json.dumps(t.input_schema, indent=2))
    await manager.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
