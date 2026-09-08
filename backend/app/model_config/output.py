"""The same secret boundary for text and decoded model JSON values."""

import json
import re


def contains_secret(text: str) -> bool:
    return bool(
        re.search(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bAKIA[A-Z0-9]{16}\b|\bsk-[A-Za-z0-9_-]{24,}",
            text,
        )
    )


def check_output(raw: str, key: str) -> None:
    def check(value: str) -> None:
        if (key and key in value) or contains_secret(value):
            raise ValueError("unsafe model output")

    check(raw)
    try:
        value = json.loads(raw, parse_int=str, parse_float=str)
    except ValueError, RecursionError:
        # Leave malformed-candidate handling/correction to the existing caller.
        return
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            check(item)
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
