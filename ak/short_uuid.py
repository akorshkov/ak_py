"""Tools for parsing 'short' uuids.

Standard string form of uuid looks like: 'de22bbe0-43bf-448d-9b83-2ee57e663285'
There is an equivalent shorter form:     'hfDoPxAatD8tiFaSAL3oXh'

Looks like standard python library does not support it.

"""

import uuid


_ALPHABET = list("23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
                 "abcdefghijkmnopqrstuvwxyz")
_INDEX_ALPHABET = dict(
    (char, pos) for pos, char in enumerate(_ALPHABET))
_SHORT_GUID_LEN = 22  # log(128 bits in uuid) / log(57 characters in alphabet)


def uuid_from_short_str(uuid_short_str):
    """short_string -> uuid."""
    if not isinstance(uuid_short_str, str) or len(uuid_short_str) != _SHORT_GUID_LEN:
        raise ValueError(f"'{uuid_to_short_str}' is not a valid uuid short string")

    try:
        uuid_number = _str_to_int(uuid_short_str)
        uuid_obj = uuid.UUID(int=uuid_number)
    except ValueError as err:
        raise ValueError(f"'{uuid_to_short_str}' is not a valid uuid short string") from err

    return uuid_obj


def uuid_to_short_str(uuid_obj):
    """uuid -> short_string"""
    return _int_to_str(uuid_obj.int)


def uuid_from_str(uuid_str):
    """create uuid either from usual or from short string."""
    try:
        uuid_obj = uuid.UUID(uuid_str)
        return uuid_obj
    except ValueError:
        pass

    return uuid_from_short_str(uuid_str)


def _str_to_int(string):
    # helper for short uuid parsing
    # string representing the number in 57-base format (reversed) -> integer
    number = 0
    alpha_len = len(_ALPHABET)
    for char in string[::-1]:
        number = number * alpha_len + _INDEX_ALPHABET[char]
    return number


def _int_to_str(number):
    # helper for short uuid parsing
    # integer -> string representing the number in 57-base format (reversed)
    out = ""
    alpha_len = len(_ALPHABET)
    while number:
        number, digit = divmod(number, alpha_len)
        out += _ALPHABET[digit]
    remainder_len = _SHORT_GUID_LEN - len(out)
    out += _ALPHABET[0] * remainder_len
    return out
