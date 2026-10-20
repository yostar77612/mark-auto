"""Pure, bounded projections for the existing desktop settings store."""


def page_row(identity, identities):
    return identities.index(identity) if type(identity) is str and identity in identities else 0


def bounded_size(value, minimum, maximum, default):
    return max(minimum, min(maximum, value if type(value) is int else default))


def splitter_sizes(value, count, maximum):
    if type(value) is not list or len(value) != count or any(type(size) is not int for size in value):
        return None
    return [bounded_size(size, 80, max(80, maximum), 80) for size in value]


def family_parameters(value, defaults):
    """Whitelist indicator parameters; never quantities, accounts or money."""
    if type(value) is not dict:
        return {}
    result = {}
    for family, keys in defaults.items():
        parameters = value.get(family)
        if type(parameters) is dict:
            safe = {key: parameters[key] for key in keys if key in parameters}
            if set(safe) == set(keys) and all(type(item) in (str, int) and len(str(item)) <= 128 for item in safe.values()):
                result[family] = safe
    return result
