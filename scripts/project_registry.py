"""CRUD for the Hortora project registry (registry/projects.yaml)."""
from pathlib import Path
import yaml

REQUIRED_FIELDS = {
    'project', 'url', 'domain', 'primary_language',
    'frameworks', 'last_processed_commit', 'notable_contributors',
}


class ProjectRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> list:
        data = yaml.safe_load(self.path.read_text()) or {}
        return data.get('projects', [])

    def _save(self, projects: list) -> None:
        self.path.write_text(yaml.dump({'projects': projects}, default_flow_style=False, sort_keys=False))

    def list(self) -> list:
        return self._load()

    def get(self, name: str) -> dict | None:
        return next((p for p in self._load() if p['project'] == name), None)

    def add(self, entry: dict) -> None:
        missing = REQUIRED_FIELDS - entry.keys()
        if missing:
            raise ValueError(f"Missing required fields: {missing}")
        projects = self._load()
        if any(p['project'] == entry['project'] for p in projects):
            raise ValueError(f"Project '{entry['project']}' already in registry")
        projects.append(entry)
        self._save(projects)

    def update_commit(self, name: str, commit: str) -> None:
        projects = self._load()
        for p in projects:
            if p['project'] == name:
                p['last_processed_commit'] = commit
                self._save(projects)
                return
        raise ValueError(f"Project '{name}' not found in registry")
