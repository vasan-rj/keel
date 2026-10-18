from keel.principal import Principal


def require_write(principal: Principal) -> None:
    """Raise if the principal's token is read-only. Write tools call this first."""
    if getattr(principal, "scope", "full") == "read_only":
        raise PermissionError("read-only token cannot perform writes")
