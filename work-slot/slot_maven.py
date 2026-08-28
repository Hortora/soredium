"""slot_maven.py — Maven settings generation and slot repo setup."""

import shutil
from pathlib import Path

from slot_core import _REGENERABLE_DIRS


def _write_slot_settings(slot_dir: Path) -> Path:
    """Generate a slot-specific settings.xml that adds the global ~/.m2/repository
    as a file:// fallback remote. This lets Maven resolve artifacts from the host
    cache without polluting it — writes go to the slot .m2, reads fall through."""
    settings_path = slot_dir / "slot-settings.xml"
    if settings_path.exists():
        return settings_path
    global_m2 = Path.home() / ".m2" / "repository"
    settings_path.write_text(f"""\
<settings>
  <profiles>
    <profile>
      <id>slot-host-fallback</id>
      <repositories>
        <repository>
          <id>host-m2</id>
          <url>file://{global_m2}</url>
          <releases><enabled>true</enabled></releases>
          <snapshots><enabled>true</enabled><updatePolicy>always</updatePolicy></snapshots>
        </repository>
      </repositories>
      <pluginRepositories>
        <pluginRepository>
          <id>host-m2-plugins</id>
          <url>file://{global_m2}</url>
          <releases><enabled>true</enabled></releases>
          <snapshots><enabled>true</enabled><updatePolicy>always</updatePolicy></snapshots>
        </pluginRepository>
      </pluginRepositories>
    </profile>
  </profiles>
  <activeProfiles>
    <activeProfile>slot-host-fallback</activeProfile>
  </activeProfiles>
</settings>
""")
    return settings_path


def setup_slot_repo(repo_worktree: Path, m2_path: Path) -> bool:
    slot_dir = m2_path.parent
    slot_settings = _write_slot_settings(slot_dir)

    mvn_dir = repo_worktree / ".mvn"
    mvn_dir.mkdir(parents=True, exist_ok=True)

    local_settings = mvn_dir / "slot-settings.xml"
    if not local_settings.exists():
        shutil.copy2(slot_settings, local_settings)

    config_file = mvn_dir / "maven.config"
    repo_line = f"-Dmaven.repo.local={m2_path}"
    settings_line = "--settings=.mvn/slot-settings.xml"
    if config_file.exists():
        content = config_file.read_text()
        lines = content.splitlines()
        fixed = [settings_line if l.strip().startswith("-s ") else l for l in lines]
        content = "\n".join(fixed) + "\n" if fixed else ""
        lines_to_add = []
        if repo_line not in content:
            lines_to_add.append(repo_line)
        if settings_line not in content:
            lines_to_add.append(settings_line)
        if lines_to_add:
            content = content.rstrip() + "\n" + "\n".join(lines_to_add) + "\n"
        config_file.write_text(content)
    else:
        config_file.write_text(repo_line + "\n" + settings_line + "\n")
    BASELINE_PATTERNS = [
        ".mvn/maven.config",
        ".mvn/slot-settings.xml",
        ".worktrees",
        ".worktrees/",
        ".claude",
        ".claude/",
    ]
    gitignore = repo_worktree / ".gitignore"
    if gitignore.exists():
        existing_lines = {line.strip() for line in gitignore.read_text().splitlines()}
        to_add = [p for p in BASELINE_PATTERNS if p not in existing_lines]
        if to_add:
            content = gitignore.read_text().rstrip()
            gitignore.write_text(content + "\n" + "\n".join(to_add) + "\n")
            return True
        return False
    else:
        gitignore.write_text("\n".join(BASELINE_PATTERNS) + "\n")
        return True
