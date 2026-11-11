"""Contract loading and validation for market trades and social posts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_DIR = ROOT / "contracts"
SCHEMA_VERSION = "1.0"
MAX_CLOCK_SKEW = timedelta(minutes=2)
SOCIAL_MAX_AGE = timedelta(days=30)


@dataclass(frozen=True)
class ContractIssue:
    path: str
    message: str


@dataclass
class ValidationResult:
    ok: bool
    model: BaseModel | None = None
    errors: list[ContractIssue] = field(default_factory=list)


def _load_schema(name: str) -> dict[str, Any]:
    with (CONTRACT_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


MARKET_SCHEMA = _load_schema("market_trade.v1.json")
SOCIAL_SCHEMA = _load_schema("social_post.v1.json")
_MARKET_VALIDATOR = Draft202012Validator(MARKET_SCHEMA)
_SOCIAL_VALIDATOR = Draft202012Validator(SOCIAL_SCHEMA)


def _format_path(parts: list[Any]) -> str:
    if not parts:
        return "$"
    rendered = "$"
    for part in parts:
        if isinstance(part, int):
            rendered += f"[{part}]"
        else:
            rendered += f".{part}"
    return rendered


def _schema_errors(validator: Draft202012Validator, payload: dict[str, Any]) -> list[ContractIssue]:
    issues = []
    for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path)):
        issues.append(ContractIssue(_format_path(list(error.path)), error.message))
    return issues


def _model_errors(exc: ValidationError) -> list[ContractIssue]:
    issues = []
    for error in exc.errors():
        parts = [part for part in error["loc"] if part != "__root__"]
        issues.append(ContractIssue(_format_path(parts), error["msg"]))
    return issues


class MarketTradeV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    symbol: Literal["BTCUSDT"]
    trade_id: int = Field(gt=0)
    event_ts: AwareDatetime
    price: Decimal = Field(gt=0)
    qty: Decimal = Field(gt=0)
    is_buyer_maker: bool
    ingest_ts: AwareDatetime
    source: Literal["binance_ws", "binance_vision", "binance_rest"]
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("event_ts")
    @classmethod
    def _event_not_in_future(cls, value: datetime) -> datetime:
        if value > datetime.now(UTC) + MAX_CLOCK_SKEW:
            raise ValueError("event_ts is in the future")
        return value

    @model_validator(mode="after")
    def _ingest_not_before_event(self) -> MarketTradeV1:
        if self.ingest_ts < self.event_ts - timedelta(seconds=1):
            raise ValueError("ingest_ts is more than 1 second before event_ts")
        return self


class SocialPostV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    post_uri: str = Field(min_length=8, max_length=512, pattern=r"^at://")
    author_did: str = Field(min_length=3)
    author_handle: str | None = None
    created_at: AwareDatetime
    lang: str | None = None
    text: str = Field(min_length=1, max_length=2000)
    hashtags: list[str] = Field(default_factory=list, max_length=20)
    like_count: int = Field(ge=0)
    repost_count: int = Field(ge=0)
    reply_count: int = Field(ge=0)
    quote_count: int = Field(ge=0)
    source: Literal["bluesky"] = "bluesky"
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    raw_ref: str = Field(min_length=3)
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("created_at")
    @classmethod
    def _created_at_window(cls, value: datetime) -> datetime:
        now = datetime.now(UTC)
        if value > now + MAX_CLOCK_SKEW:
            raise ValueError("created_at is in the future")
        if value < now - SOCIAL_MAX_AGE:
            raise ValueError("created_at is older than 30 days")
        return value


def validate_market_trade(payload: dict[str, Any]) -> ValidationResult:
    issues = _schema_errors(_MARKET_VALIDATOR, payload)
    if issues:
        return ValidationResult(ok=False, errors=issues)
    try:
        model = MarketTradeV1.model_validate(payload)
    except ValidationError as exc:
        return ValidationResult(ok=False, errors=_model_errors(exc))
    return ValidationResult(ok=True, model=model)


def validate_social_post(payload: dict[str, Any]) -> ValidationResult:
    issues = _schema_errors(_SOCIAL_VALIDATOR, payload)
    if issues:
        return ValidationResult(ok=False, errors=issues)
    try:
        model = SocialPostV1.model_validate(payload)
    except ValidationError as exc:
        return ValidationResult(ok=False, errors=_model_errors(exc))
    return ValidationResult(ok=True, model=model)


def load_fixture(name: str) -> dict[str, Any]:
    with (ROOT / "tests" / "fixtures" / name).open(encoding="utf-8") as handle:
        return json.load(handle)
