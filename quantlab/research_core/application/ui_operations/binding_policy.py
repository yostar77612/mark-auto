"""Existing binding_policy worker use cases; concrete dependencies arrive through ports."""


def provider_binding_options(options):
    return {
        key: value
        for key, value in options.items()
        if key != 'network_opt_in' and (not (options.get('mode') == 'local' and key == 'owner')) and (not (key == 'output_mode' and value == 'json_object'))
    }
