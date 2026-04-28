class WindowError(RuntimeError):
    """Base exception for Backup Manager window-management issues."""


class WindowAlreadyOpenError(WindowError):
    """Raised when a single-instance popout is already open."""
