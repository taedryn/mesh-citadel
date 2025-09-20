class RoomError(BaseException):
    """ base class for room errors """

class RoomNotFoundError(RoomError):
    """ specified room not found """

class PermissionDeniedError(RoomError):
    """ user requested to do something they don't have permission for """
