from typing import Annotated, Literal

from pydantic import Field

from app.training.schema import Strict, Text

Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]


class Repository(Strict):
    owner: str
    name: str
    commit: Sha
    tree: Sha
    ref: str
    focus: str = ""
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class FileEntry(Strict):
    path: str
    sha: Sha
    kind: Literal["tree", "blob", "commit"]
    mode: str
    size: int = Field(default=0, ge=0)


class Fragment(Strict):
    path: str
    blob: Sha
    start: int = Field(ge=1)
    end: int = Field(ge=1)
    total_lines: int = Field(ge=1)
    text: str


class Location(Strict):
    path: Text
    start: int = Field(ge=1)
    end: int = Field(ge=1)
    quote: Text


class Finding(Strict):
    kind: Literal["module", "entry", "call", "state", "storage"]
    subject: Text
    relation: Text
    target: Text
    evidence: list[Location] = Field(min_length=1, max_length=4)


class MapCandidate(Strict):
    findings: list[Finding] = Field(max_length=40)
    missing: list[Text] = Field(max_length=20)


class ProjectMap(Strict):
    confirmed: list[Finding] = Field(default_factory=list)
    # References establish where a claim came from, not whether it is true.
    unverified: list[Finding] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class Snapshot(Strict):
    repository: Repository
    entries: list[FileEntry] = Field(default_factory=list)
    fragments: list[Fragment] = Field(default_factory=list)
    excluded: dict[str, str] = Field(default_factory=dict)
    directories: list[FileEntry] = Field(default_factory=list)
    files: list[FileEntry] = Field(default_factory=list)
    offsets: dict[str, Annotated[int, Field(ge=1)]] = Field(default_factory=dict)
    requests: int = 0
    bytes: int = 0
    listing_complete: bool = False


def validate_map(raw: str, fragments: list[Fragment], key: str) -> MapCandidate:
    if key and key in raw:
        raise ValueError("secret echoed")
    candidate = MapCandidate.model_validate_json(raw)
    for finding in candidate.findings:
        for location in finding.evidence:
            if not any(
                fragment.path == location.path
                and fragment.start <= location.start <= location.end <= fragment.end
                and location.quote
                == "\n".join(
                    fragment.text.splitlines()[
                        location.start - fragment.start : location.end
                        - fragment.start
                        + 1
                    ]
                )
                for fragment in fragments
            ):
                raise ValueError("unread or forged reference")
    return candidate
