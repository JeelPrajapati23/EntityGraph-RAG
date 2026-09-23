"""Load the pinned corpus roots from config/projects.yaml."""

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_PROJECTS_PATH = Path(__file__).resolve().parent.parent.parent.parent / "config" / "projects.yaml"


@dataclass(frozen=True)
class Project:
    name: str
    version: str
    resolve_before: str  # ISO date, passed to `npm install --before`

    @property
    def spec(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def slug(self) -> str:
        """Filesystem-safe directory name, e.g. "@vue/cli-service" 4.5.13 -> "vue__cli-service@4.5.13"."""
        return f"{self.name.lstrip('@').replace('/', '__')}@{self.version}"


def load_projects(path: Path = DEFAULT_PROJECTS_PATH) -> list[Project]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        Project(name=p["name"], version=str(p["version"]), resolve_before=str(p["resolve_before"]))
        for p in raw["projects"]
    ]
