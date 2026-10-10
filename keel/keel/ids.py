import uuid


def as_uuid(value) -> uuid.UUID:
    """Parse a client-supplied id into a UUID at the tool boundary.

    Agents may pass malformed or fabricated ids; without this, asyncpg raises a
    DataError deep inside the query. Here a bad id raises ValueError, which each
    tool maps to its own clean "not found" contract.
    """
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
