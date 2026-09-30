"""Responses of the liveness and readiness probes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]


class ReadinessOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]
    checks: dict[str, Literal["ok"]] = Field(
        description="The result of each dependency check, keyed by dependency."
    )
