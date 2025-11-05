def format_permission_level(level):
    levels = {
        0: "Unverified",
        1: "Twit",
        2: "User",
        3: "Aide",
        4: "Sysop"
    }
    return levels.get(level, f"Unknown({level})")

