"""Tests for the pagination envelope, base schemas, and PaginationParams dependency.

Covers Requirements 21.2 and 29.2.
"""

import pytest
from pydantic import ValidationError

from app.api.deps import PaginationParams
from app.schemas.base import (
    BaseCreateSchema,
    BaseSchema,
    BaseUpdateSchema,
    IDMixin,
    PaginatedResponse,
    TimestampMixin,
)


# ---------------------------------------------------------------------------
# PaginatedResponse tests
# ---------------------------------------------------------------------------


class TestPaginatedResponse:
    """Tests for the generic PaginatedResponse envelope."""

    def test_paginated_response_with_strings(self):
        resp = PaginatedResponse[str](
            items=["a", "b", "c"], page=1, page_size=25, total=3
        )
        assert resp.items == ["a", "b", "c"]
        assert resp.page == 1
        assert resp.page_size == 25
        assert resp.total == 3

    def test_paginated_response_with_dicts(self):
        resp = PaginatedResponse[dict](
            items=[{"id": 1}, {"id": 2}], page=2, page_size=10, total=15
        )
        assert len(resp.items) == 2
        assert resp.page == 2
        assert resp.total == 15

    def test_paginated_response_empty_items(self):
        resp = PaginatedResponse[str](items=[], page=1, page_size=25, total=0)
        assert resp.items == []
        assert resp.total == 0

    def test_paginated_response_serialization(self):
        resp = PaginatedResponse[int](items=[1, 2], page=1, page_size=10, total=2)
        data = resp.model_dump()
        assert data == {"items": [1, 2], "page": 1, "page_size": 10, "total": 2}


# ---------------------------------------------------------------------------
# PaginationParams tests
# ---------------------------------------------------------------------------


class TestPaginationParams:
    """Tests for the PaginationParams dependency."""

    def test_defaults(self):
        """When used via DI, FastAPI resolves Query defaults. Direct instantiation
        needs explicit values; we test the resolved behavior."""
        params = PaginationParams(page=1, page_size=25)
        assert params.page == 1
        assert params.page_size == 25

    def test_offset_page_1(self):
        params = PaginationParams(page=1, page_size=25)
        assert params.offset == 0

    def test_offset_page_2(self):
        params = PaginationParams(page=2, page_size=25)
        assert params.offset == 25

    def test_offset_page_3_custom_size(self):
        params = PaginationParams(page=3, page_size=10)
        assert params.offset == 20

    def test_custom_page_size(self):
        params = PaginationParams(page=1, page_size=50)
        assert params.page_size == 50
        assert params.offset == 0


# ---------------------------------------------------------------------------
# Base schema tests
# ---------------------------------------------------------------------------


class TestBaseSchemas:
    """Tests for BaseSchema, BaseCreateSchema, BaseUpdateSchema."""

    def test_base_schema_from_attributes(self):
        """Verify BaseSchema has from_attributes=True for ORM compatibility."""
        assert BaseSchema.model_config.get("from_attributes") is True

    def test_base_create_schema_from_attributes(self):
        assert BaseCreateSchema.model_config.get("from_attributes") is True

    def test_base_update_schema_from_attributes(self):
        assert BaseUpdateSchema.model_config.get("from_attributes") is True

    def test_base_schema_populate_by_name(self):
        assert BaseSchema.model_config.get("populate_by_name") is True


# ---------------------------------------------------------------------------
# Mixin tests
# ---------------------------------------------------------------------------


class TestMixins:
    """Tests for IDMixin and TimestampMixin."""

    def test_id_mixin_fields(self):
        fields = IDMixin.model_fields
        assert "id" in fields

    def test_timestamp_mixin_fields(self):
        fields = TimestampMixin.model_fields
        assert "created_at" in fields
        assert "updated_at" in fields
