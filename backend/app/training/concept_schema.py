"""Content checks are model inferences, never proof of learning or human approval."""

from typing import Literal, Protocol

from pydantic import Field

from app.training.schema import Strict, Text

Direction = Literal["neutral", "directional", "uncertain"]
Section = Literal["plain", "example", "relation", "principle"]


class ConceptContent(Strict):
    plain: Text
    example: Text
    relation: Text
    evidence_ids: list[Text] = Field(min_length=1, max_length=12)
    principle: Text | None = None

    def sections(self) -> dict[str, str]:
        result: dict[str, str] = {
            "plain": self.plain,
            "example": self.example,
            "relation": self.relation,
        }
        if self.principle is not None:
            result["principle"] = self.principle
        return result


class SectionReview(Strict):
    section: Text
    quote: Text
    direction: Direction
    reason: Text
    accuracy: Literal["supported", "unsupported", "uncertain"]
    unsafe: bool
    claims_understanding: bool


class ContentReview(Strict):
    sections: list[SectionReview] = Field(min_length=1, max_length=512)


class InspectedContent(Protocol):
    def sections(self) -> dict[str, str]: ...


def classify_content(content: InspectedContent, review: ContentReview) -> Direction:
    sections = content.sections()
    if (
        len(review.sections) != len(sections)
        or {item.section for item in review.sections} != sections.keys()
    ):
        raise ValueError("incomplete content inspection")
    for item in review.sections:
        if item.quote != sections[item.section]:
            raise ValueError("inspection does not match delivered content")
        if item.unsafe or item.claims_understanding or item.accuracy == "unsupported":
            raise ValueError("content rejected")
    # These labels remain semantic inferences. No confidence score or JSON shape
    # establishes neutrality or correctness; controlled tests are not human validation.
    if getattr(content, "direction", None) == "directional" or any(
        item.direction == "directional" for item in review.sections
    ):
        return "directional"
    if any(
        item.direction == "uncertain" or item.accuracy == "uncertain"
        for item in review.sections
    ):
        return "uncertain"
    return "neutral"


class HelpAnswer(Strict):
    judgment_id: Text
    value: int | list[int] | str | None = None
    reason: str = Field(default="", max_length=6000)


class HelpInput(Strict):
    question: Text
    depth: Literal["basic", "deep"] = "basic"
    answers: list[HelpAnswer] = Field(default_factory=list, max_length=4)
