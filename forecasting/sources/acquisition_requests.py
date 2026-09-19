"""Discriminated acquisition inputs for the first migrated source adapters.

Import policy (ratings, deduplication, watches) is deliberately not acquisition
configuration. Compatibility mappings extract only the selected adapter's fields.
"""

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationInfo,
    field_validator,
)

from forecasting.sources.requests import CommonSourceOptions


class AcquisitionRequest(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True, str_strip_whitespace=True
    )

    source: str = Field(min_length=1)
    api_base_url: str | None = None

    @field_validator("api_base_url")
    @classmethod
    def endpoint(cls, value: str | None) -> str | None:
        return CommonSourceOptions.validate_endpoint(value)


class EconomicAcquisitionRequest(AcquisitionRequest):
    limit: int = Field(default=10, gt=0)
    since: str | None = None

    @field_validator("since")
    @classmethod
    def date_filter(cls, value: str | None) -> str | None:
        return CommonSourceOptions.validate_since(value)


class FredAcquisitionRequest(EconomicAcquisitionRequest):
    adapter: Literal["fred"] = "fred"


class BlsAcquisitionRequest(EconomicAcquisitionRequest):
    adapter: Literal["bls"] = "bls"
    start_year: int | None = Field(default=None, ge=1, le=9999)
    end_year: int | None = Field(default=None, ge=1, le=9999)

    @field_validator("end_year")
    @classmethod
    def year_order(cls, value: int | None, info: ValidationInfo) -> int | None:
        start = info.data.get("start_year")
        if start is not None and value is not None and start > value:
            raise ValueError("end_year cannot be before start_year")
        return value


class KalshiAcquisitionRequest(AcquisitionRequest):
    adapter: Literal["kalshi"] = "kalshi"


class PolymarketAcquisitionRequest(AcquisitionRequest):
    adapter: Literal["polymarket"] = "polymarket"


SourceAcquisitionRequest = Annotated[
    FredAcquisitionRequest
    | BlsAcquisitionRequest
    | KalshiAcquisitionRequest
    | PolymarketAcquisitionRequest,
    Field(discriminator="adapter"),
]
REQUEST_ADAPTER = TypeAdapter(SourceAcquisitionRequest)


def acquisition_request(
    adapter: str, source: str, options: dict[str, Any]
) -> SourceAcquisitionRequest:
    """Translate legacy tool/import options into the selected acquisition contract.

    Unrelated import controls are not sent to the provider. Direct typed callers
    receive extra-field rejection rather than unrestricted keyword forwarding.
    Errors name fields only; endpoints may contain credentials.
    """
    from pydantic import ValidationError

    fields = {"api_base_url"}
    if adapter in {"fred", "bls"}:
        fields.update({"limit", "since"})
    if adapter == "bls":
        fields.update({"start_year", "end_year"})
    values = {key: options[key] for key in fields if key in options}
    try:
        return REQUEST_ADAPTER.validate_python({
            "adapter": adapter,
            "source": source,
            **values,
        })
    except ValidationError as exc:
        names = sorted({
            str(item["loc"][-1]) if item["loc"] else "request" for item in exc.errors()
        })
        raise ValueError("invalid acquisition request: " + ", ".join(names)) from None
