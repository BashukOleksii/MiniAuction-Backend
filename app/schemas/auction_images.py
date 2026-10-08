from pydantic import BaseModel, ConfigDict, Field, model_validator


class SetAuctionCoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_id: str = Field(min_length=1)


class ReorderAuctionImagesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_ids: list[str] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def reject_duplicate_ids(self):
        if len(self.public_ids) != len(set(self.public_ids)):
            raise ValueError("Image identifiers must be unique")
        if any(not image_id for image_id in self.public_ids):
            raise ValueError("Image identifiers must be nonempty")
        return self
