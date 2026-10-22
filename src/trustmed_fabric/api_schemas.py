"""HTTP request/response contracts for the public API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from trustmed_fabric.models import Audience, Channel, Market


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    market: Market
    audience: Audience
    channel: Channel
    experience_id: str | None = None
    for_publication: bool = False


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    experience_id: str
    destination: str = Field(min_length=8, max_length=300)


class ClaimCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    market: Market
