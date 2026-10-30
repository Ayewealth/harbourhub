import pytest
from drf_spectacular.generators import SchemaGenerator

from .factories import UserFactory


@pytest.mark.django_db
def test_openapi_schema_generates():
    schema = SchemaGenerator().get_schema(request=None, public=True)

    assert schema["openapi"].startswith("3.")
    assert "/commerce/orders/" in schema["paths"]


@pytest.mark.django_db
def test_operation_ids_are_unique():
    """drf-spectacular suffixes duplicates silently; keep the contract stable."""
    schema = SchemaGenerator().get_schema(request=None, public=True)

    seen = {}
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            operation_id = operation.get("operationId")
            if not operation_id:
                continue
            assert operation_id not in seen, (
                f"{operation_id} is used by both {seen[operation_id]} "
                f"and {(path, method)}"
            )
            seen[operation_id] = (path, method)


@pytest.mark.django_db
def test_cart_collection_and_detail_split_methods():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    collection = schema["paths"]["/commerce/cart/items/"]
    detail = schema["paths"]["/commerce/cart/items/{item_id}/"]

    assert "post" in collection
    assert "patch" not in collection
    assert "delete" not in collection
    assert {"patch", "delete"} <= set(detail)


@pytest.mark.django_db
def test_cart_collection_patch_is_method_not_allowed(api_client):
    """Regression: PATCH on the collection route used to 500 instead of 405."""
    api_client.force_authenticate(user=UserFactory())

    response = api_client.patch("/commerce/cart/items/", {}, format="json")

    assert response.status_code == 405
