from db import get_db
from utils import format_permission_level

async def handle_user_command(args):
    if args.subcommand == "list":
        await list_users(args.sort)
    elif args.subcommand == "edit":
        await edit_user(args)


async def list_users(sort_field):
    db = await get_db()
    query = f"""
        SELECT id, username, display_name, permission_level, status, last_login
        FROM users
        ORDER BY {sort_field} COLLATE NOCASE
    """
    async with db.execute(query) as cursor:
        rows = await cursor.fetchall()

    print(f"{'ID':<4} {'Username':<16} {'Display Name':<20} {'Perm':<6} {'Status':<10} {'Last Login'}")
    print("-" * 80)
    for row in rows:
        id_, username, display_name, perm, status, last_login = row
        print(f"{id_:<4} {username:<16} {display_name or '':<20} {format_permission_level(perm):<6} {status:<10} {last_login or ''}")


async def edit_user(args):
    db = await get_db()

    # Check if user exists
    async with db.execute("SELECT id FROM users WHERE username = ?", (args.username,)) as cursor:
        row = await cursor.fetchone()
        if not row:
            print(f"User '{args.username}' not found.")
            return

    updates = []
    params = []

    if args.new_username:
        updates.append("username = ?")
        params.append(args.new_username)
    if args.display_name is not None:
        updates.append("display_name = ?")
        params.append(args.display_name)
    if args.permission is not None:
        updates.append("permission_level = ?")
        params.append(args.permission)

    if not updates:
        print("No changes specified. Use --new-username, --display-name, or --permission.")
        return

    params.append(args.username)
    query = f"UPDATE users SET {', '.join(updates)} WHERE username = ?"

    await db.execute(query, params)
    await db.commit()
    print(f"User '{args.username}' updated successfully.")

