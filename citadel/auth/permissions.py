from enum import IntEnum

class PermissionLevel(IntEnum):
    UNVERIFIED = 0
    TWIT = 1
    USER = 2
    AIDE = 3
    SYSOP = 4
