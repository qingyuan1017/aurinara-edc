"""Versioned, safe rule and derivation contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ScopedFieldReference(RuleModel):
    item_oid: str = Field(alias="itemOID")
    study_event_oid: str | None = Field(None, alias="studyEventOID")
    form_oid: str | None = Field(None, alias="formOID")
    item_group_oid: str | None = Field(None, alias="itemGroupOID")
    repeat: Literal["current", "first", "last", "any", "all"] = "current"


class RuleCondition(RuleModel):
    operator: Literal[
        "is_null", "not_null", "==", "!=", ">", ">=", "<", "<=", "in",
        "not_in", "matches", "before", "after", "within_days", "changed",
        "exists", "any", "all", "count",
    ]
    field: ScopedFieldReference | None = None
    value: Any = None
    other_field: ScopedFieldReference | None = Field(None, alias="otherField")
    children: list[RuleCondition] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_shape(self) -> RuleCondition:
        aggregate = self.operator in {"any", "all", "count"}
        if aggregate and not self.children:
            raise ValueError(f"{self.operator} requires children")
        if not aggregate and self.field is None:
            raise ValueError(f"{self.operator} requires a field")
        return self


class RuleAction(RuleModel):
    type: Literal[
        "open_query", "close_query", "set_value", "clear_value", "show", "hide",
        "enable", "disable", "require", "make_optional", "set_subject_status",
        "send_notification", "configure_search_list",
    ]
    target: ScopedFieldReference | None = None
    value: Any = None
    message: str | None = Field(None, max_length=2000)


class RuleExecution(RuleModel):
    trigger: Literal["form_save", "field_change", "subject_transition", "manual"] = "form_save"
    priority: int = Field(default=100, ge=0, le=10000)
    stop_on_failure: bool = Field(default=True, alias="stopOnFailure")


class RuleDefinitionV2(RuleModel):
    schema_version: Literal[2] = Field(default=2, alias="schemaVersion")
    scope: dict[str, Any] = Field(default_factory=dict)
    condition: RuleCondition
    actions: list[RuleAction] = Field(default_factory=list, max_length=50)
    execution: RuleExecution = Field(default_factory=RuleExecution)


__all__ = ["RuleAction", "RuleCondition", "RuleDefinitionV2", "ScopedFieldReference"]
