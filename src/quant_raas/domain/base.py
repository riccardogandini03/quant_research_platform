"""Base Pydantic configuration for durable domain contracts."""

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    """Strict, immutable value object used at module boundaries."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )
