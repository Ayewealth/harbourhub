import re
import uuid

import pytest
from django.urls import URLPattern, URLResolver, get_resolver

from .factories import UserFactory

# Routes that must not be probed with GET: they mutate, call an external
# gateway, or are HTML-only.
SKIP_PREFIXES = (
    "/admin/",
    "/api/schema/",
    "/api/docs/",
    "/api/redoc/",
    "/commerce/payment/",
    "/commerce/checkout/",
    "/auth/logout",
)

PARAM_VALUES = {
    "int": "1",
    "str": "sample",
    "slug": "sample",
    "uuid": str(uuid.uuid4()),
}


def _walk(patterns, prefix=""):
    for entry in patterns:
        route = prefix + str(entry.pattern)
        if isinstance(entry, URLResolver):
            yield from _walk(entry.url_patterns, route)
        elif isinstance(entry, URLPattern):
            yield route


def _materialise(route):
    def replace(match):
        converter = match.group(1)
        return PARAM_VALUES.get(converter, "sample")

    path = re.sub(r"<(?:(int|str|slug|uuid):)?[^>]+>", replace, route)
    if not path.startswith("/"):
        path = "/" + path
    return path


@pytest.mark.django_db
def test_every_gettable_route_returns_below_500(api_client):
    admin = UserFactory(role="admin", is_staff=True, is_superuser=True)
    api_client.force_authenticate(user=admin)

    failures = []
    probed = []
    for route in _walk(get_resolver().url_patterns):
        path = _materialise(route)
        if any(path.startswith(prefix) for prefix in SKIP_PREFIXES):
            continue
        probed.append(path)
        response = api_client.get(path)
        if response.status_code >= 500:
            failures.append((path, response.status_code))

    # Guard against a vacuous pass if the resolver walk ever stops working.
    assert len(probed) > 50, probed
    assert "/listings/" in probed
    assert "/commerce/orders/" in probed
    assert failures == []
