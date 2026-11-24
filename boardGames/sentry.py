def scrub_secret(value, secret):
    """Copy of `value` (an event or any part of it) with `secret` masked."""
    if not secret:
        return value
    if isinstance(value, str):
        return value.replace(secret, '[Filtered]')
    if isinstance(value, dict):
        return {scrub_secret(k, secret): scrub_secret(v, secret) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(scrub_secret(v, secret) for v in value)
    return value
