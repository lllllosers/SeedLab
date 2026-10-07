"""GER sowing and observation contracts shared by API and application code."""
from pydantic import AwareDatetime, BaseModel, Field


class SowDishesInput(BaseModel):
    dish_ids: list[str] = Field(min_length=1)
    sown_at: AwareDatetime


class CorrectSowingInput(BaseModel):
    sown_at: AwareDatetime


class CancelDishInput(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class ObservationEntry(BaseModel):
    dish_id: str
    new_germinated_count: int | None = Field(default=None, ge=0)
    notes: str | None = None


class BatchObservationInput(BaseModel):
    observed_at: AwareDatetime
    entries: list[ObservationEntry] = Field(min_length=1)


class ObservationInput(ObservationEntry):
    observed_at: AwareDatetime
    new_germinated_count: int = Field(ge=0)


class ObservationPatch(BaseModel):
    new_germinated_count: int | None = Field(default=None, ge=0)
    notes: str | None = None
