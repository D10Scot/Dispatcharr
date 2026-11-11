"""Claim to ``user_level`` mapping (SSO spec 3.6, 3.7, 4.2 step 1, D9, D17).

The mapping claim path is a dotted path into the ID token's claims, one key per segment, no
escaping and no wildcards. The value must be a string or a list of strings; anything else
matches nothing. The highest matched level wins. Nothing here writes, and nothing here logs a
claim value.
"""

import unicodedata

# Entra's JWT group limit; the identity stores at most this many values (spec 4.1).
MAX_STORED_VALUES = 200


def has_control_char(value):
    """True when ``value`` holds a Unicode control character (category Cc: C0, DEL, C1).

    PostgreSQL refuses U+0000 in a text column and in ``jsonb``, so such a value would end a
    callback in ``DataError``. An identity key or a mapping value carrying one is refused,
    never stripped: stripping could make two different values equal.
    """
    return any(unicodedata.category(c) == "Cc" for c in value)


def strip_control_chars(value):
    """``value`` without its control characters. Only for display fields, never for a key."""
    return "".join(c for c in value if unicodedata.category(c) != "Cc")


class GroupsOverage(Exception):
    """An Entra token that carries a groups-overage marker instead of ``groups``."""


def claim_values(claims, path):
    """The mapping claim's values as a list of strings, or ``None`` when absent or ill-typed."""
    if not path:
        return None
    node = claims
    for segment in path.split("."):
        if not isinstance(node, dict) or segment not in node:
            return None
        node = node[segment]
    if isinstance(node, str):
        return [node]
    if isinstance(node, list) and all(isinstance(v, str) for v in node):
        return list(node)
    return None


def check_groups_overage(provider, claims):
    """Spec 3.6: an Entra provider mapping on ``groups`` refuses an overage token."""
    if provider.kind != "entra" or provider.claim_path != "groups":
        return
    names = claims.get("_claim_names")
    if (isinstance(names, dict) and "groups" in names) or claims.get("hasgroups") is True:
        raise GroupsOverage()


def level_for(mappings, values):
    """The highest level any mapping grants for ``values``, or ``None`` for no match."""
    if not values or not isinstance(mappings, list):
        return None
    present = set(values)
    best = None
    for entry in mappings:
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        level = entry.get("user_level")
        if isinstance(value, str) and isinstance(level, int) and value in present:
            if best is None or level > best:
                best = level
    return best


def values_to_store(values, mappings):
    """At most ``MAX_STORED_VALUES`` distinct values, those the current mappings name first.

    A generic IdP may send more than 200 values. Keeping the mapped ones first means D17's
    recompute under unchanged mappings sees exactly what this login matched.
    """
    mapped = {
        e.get("value") for e in (mappings if isinstance(mappings, list) else []) if isinstance(e, dict)
    }
    ordered = [v for v in values or () if v in mapped] + [v for v in values or () if v not in mapped]
    seen = set()
    kept = []
    for value in ordered:
        if value in seen:
            continue
        seen.add(value)
        kept.append(value)
        if len(kept) >= MAX_STORED_VALUES:
            break
    return kept
