import pytest
from drf_spectacular.generators import SchemaGenerator


@pytest.mark.django_db
def test_openapi_schema_generates():
    schema = SchemaGenerator().get_schema(request=None, public=True)

    assert schema["openapi"].startswith("3.")
    assert "/commerce/orders/" in schema["paths"]
