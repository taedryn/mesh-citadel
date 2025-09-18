class MessageError(Exception):
    """Base class for message-related errors."""

class InvalidContentError(MessageError):
    """Raised when message content is empty or malformed."""

class InvalidRecipientError(MessageError):
    """Raised when a private message is sent to a nonexistent user."""

