def context_usage(usage):
    """Only explicit provider context counters; token totals aren't a limit."""
    if type(usage) is not dict or set(usage) != {'used', 'limit'}:
        return None
    used, limit = (usage['used'], usage['limit'])
    if type(used) is not int or type(limit) is not int or (not -(2**53) <= used <= 2**53) or (not 1 <= limit <= 2**53):
        return None
    percent = max(0, min(100, (used * 200 + limit) // (2 * limit)))
    return (used, limit, percent)
