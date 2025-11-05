import argparse
import asyncio
from user import handle_user_command

def main():
    parser = argparse.ArgumentParser(prog="citadmin", description="Citadel BBS Admin Tool")
    subparsers = parser.add_subparsers(dest="command")

    # User command group
    user_parser = subparsers.add_parser("user", help="Manage users")
    user_subparsers = user_parser.add_subparsers(dest="subcommand")

    # user list
    list_parser = user_subparsers.add_parser("list", help="List all users")
    list_parser.add_argument("--sort", choices=["id", "username"], default="id", help="Sort by field")

    # user edit
    edit_parser = user_subparsers.add_parser("edit", help="Edit a user's details")
    edit_parser.add_argument("username", help="Current username of the user")
    edit_parser.add_argument("--new-username", help="New username")
    edit_parser.add_argument("--display-name", help="New display name")
    edit_parser.add_argument("--permission", type=int, choices=range(0, 4), help="New permission level (0–3)")


    args = parser.parse_args()
    asyncio.run(dispatch(args))

async def dispatch(args):
    if args.command == "user":
        await handle_user_command(args)
    else:
        print("Unknown command. Use --help for usage.")

if __name__ == "__main__":
    main()

