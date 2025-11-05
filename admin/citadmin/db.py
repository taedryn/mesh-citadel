import aiosqlite

DB_PATH = "../citadel.db"  # Adjust path as needed

async def get_db():
    return await aiosqlite.connect(DB_PATH)

