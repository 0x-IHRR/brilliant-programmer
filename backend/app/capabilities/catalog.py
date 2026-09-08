"""Release-owned catalog. Model output and self-reports cannot edit its prerequisites."""

from graphlib import TopologicalSorter
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Difficulty = Literal["基础", "进阶", "综合"]


class CatalogModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EvidenceKey(CatalogModel):
    capability_id: str
    difficulty: Difficulty
    background_id: str


class Level(CatalogModel):
    difficulty: Difficulty
    required: tuple[EvidenceKey, ...] = ()
    alternatives: tuple[tuple[EvidenceKey, ...], ...] = ()

    def satisfied_by(self, verified: set[EvidenceKey]) -> bool:
        return all(key in verified for key in self.required) and all(
            any(key in verified for key in group) for group in self.alternatives
        )


class Capability(CatalogModel):
    id: str
    title: str
    criterion: str
    background_id: str
    levels: tuple[Level, ...]


class Example(CatalogModel):
    difficulty: Difficulty
    capability_ids: tuple[str, ...]
    task: str
    acceptable: str
    insufficient: str


class Domain(CatalogModel):
    id: str
    name: str
    capabilities: tuple[Capability, ...]
    examples: tuple[Example, ...]


class Background(CatalogModel):
    id: str
    name: str
    boundary: str


class Catalog(CatalogModel):
    version: str
    quality: str
    difficulty_criteria: dict[Difficulty, str]
    backgrounds: tuple[Background, ...]
    domains: tuple[Domain, ...] = Field(min_length=14, max_length=14)

    @model_validator(mode="after")
    def validate_graph(self) -> Self:
        difficulties = {"基础", "进阶", "综合"}
        backgrounds = {b.id for b in self.backgrounds}
        capabilities = [c for d in self.domains for c in d.capabilities]
        ids = {c.id for c in capabilities}
        if (
            len(backgrounds) != len(self.backgrounds)
            or len(ids) != len(capabilities)
            or len({d.id for d in self.domains}) != len(self.domains)
            or set(self.difficulty_criteria) != difficulties
        ):
            raise ValueError("duplicate IDs or incomplete difficulty criteria")
        graph: dict[EvidenceKey, set[EvidenceKey]] = {}
        levels: dict[EvidenceKey, Level] = {}
        for domain in self.domains:
            domain_ids = {c.id for c in domain.capabilities}
            if (
                not domain_ids
                or {e.difficulty for e in domain.examples} != difficulties
            ):
                raise ValueError("domain needs capabilities and three example tiers")
            for example in domain.examples:
                if (
                    not example.capability_ids
                    or not set(example.capability_ids) <= domain_ids
                ):
                    raise ValueError("example references unknown capability")
            for capability in domain.capabilities:
                if (
                    capability.background_id not in backgrounds
                    or len(capability.levels) != 3
                    or {level.difficulty for level in capability.levels} != difficulties
                ):
                    raise ValueError("unknown background or missing capability tier")
                for level in capability.levels:
                    if any(not group for group in level.alternatives):
                        raise ValueError("empty alternative group is a deadlock")
                    key = EvidenceKey(
                        capability_id=capability.id,
                        difficulty=level.difficulty,
                        background_id=capability.background_id,
                    )
                    levels[key] = level
                    graph[key] = set(level.required).union(*level.alternatives)
        if any(not dependencies <= graph.keys() for dependencies in graph.values()):
            raise ValueError(
                "prerequisite references unknown capability/tier/background"
            )
        # Reject cycles even when another alternative could bypass them: published
        # dependencies must stay explainable in either route.
        tuple(TopologicalSorter(graph).static_order())
        reachable: set[EvidenceKey] = set()
        while newly_reachable := {
            key
            for key, level in levels.items()
            if key not in reachable and level.satisfied_by(reachable)
        }:
            reachable.update(newly_reachable)
        if reachable != graph.keys():
            raise ValueError("prerequisite deadlock")
        if not any(key.difficulty == "基础" and not graph[key] for key in graph):
            raise ValueError("no prerequisite-free entry")
        return self


CATALOG = Catalog.model_validate_json(Path(__file__).with_name("v1.json").read_text())
