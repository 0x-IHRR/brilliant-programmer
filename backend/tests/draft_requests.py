"""Build real draft writes with the collection read by this simulated device."""

import uuid

from tests.test_accounts import client


def put(path, *, headers, json):
    state = client.get(path + "/versions", headers=headers).json()
    tokens = {
        name: state.get(name, str(uuid.uuid4())) for name in ("revision", "generation")
    }
    return client.put(
        path,
        headers=headers,
        json={
            "observed_revision": tokens["revision"],
            "generation": tokens["generation"],
            **json,
        },
    )


def snapshot(response):
    return {k: v for k, v in response.items() if k not in {"revision", "generation"}}
