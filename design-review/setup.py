"""Workspace setup and session invocation for adversarial design review."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Final

SKILL_DIR: Final = Path(__file__).parent
TEMPLATES_DIR: Final = SKILL_DIR / "templates"

_HEADING_RE = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)
_ALREADY_ANNOTATED_RE = re.compile(r"^S\d+(?:\.\d+)?:\s")


def _derive_project_name(source_dirs: list[str]) -> str:
    if not source_dirs:
        return "unknown"
    first = Path(source_dirs[0])
    parts = first.parts
    for i, part in enumerate(parts):
        if part in ("casehub", "hortora") and i + 1 < len(parts):
            return f"{part}-{parts[i + 1]}"
    return first.name


def setup_review(
    spec_path: Path,
    title: str,
    source_dirs: list[str],
    adr_root: Path | None = None,
    issue: str | None = None,
    mode: str = "spec-review",
    arch_files: list[str] | None = None,
    diff_base: str | None = None,
) -> Path:
    if adr_root is None:
        adr_root = Path.home() / "adr"

    project_name = _derive_project_name(source_dirs)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    ws = adr_root / project_name / f"{title}-{timestamp}"
    ws.mkdir(parents=True, exist_ok=True)

    for subdir in ["responses", "decisions", "handovers"]:
        (ws / subdir).mkdir(exist_ok=True)

    for agent in ["reviewer", "implementor"]:
        (ws / "agents" / agent).mkdir(parents=True, exist_ok=True)

    # Store spec path, source dirs, issue, and mode — all needed on resume
    (ws / ".spec-path").write_text(str(spec_path.resolve()))
    (ws / ".source-dirs").write_text("\n".join(source_dirs))
    (ws / ".mode").write_text(mode)
    if issue:
        (ws / ".issue").write_text(issue)
    if arch_files:
        (ws / ".arch-files").write_text("\n".join(arch_files))
    if diff_base:
        (ws / ".diff-base").write_text(diff_base)

    # Symlink to spec for easy navigation from the review folder
    spec_link = ws / "spec.md"
    if not spec_link.exists():
        spec_link.symlink_to(spec_path.resolve())

    _generate_context_md(ws, source_dirs, spec_path, arch_files=arch_files)
    _generate_agent_claude_mds(ws, mode=mode)
    _init_review_git(ws, adr_root)

    return ws


def annotate_spec_headings(content: str) -> str:
    if not content.strip():
        return content

    lines = content.split("\n")
    result: list[str] = []
    h2_count = 0
    h3_count = 0
    current_h2_num = 0

    for line in lines:
        match = _HEADING_RE.match(line)
        if match:
            level = match.group(1)
            title = match.group(2).strip()

            if _ALREADY_ANNOTATED_RE.match(title):
                result.append(line)
                if level == "##":
                    h2_count += 1
                    current_h2_num = h2_count
                    h3_count = 0
                elif level == "###":
                    h3_count += 1
                continue

            if level == "##":
                h2_count += 1
                current_h2_num = h2_count
                h3_count = 0
                result.append(f"## S{current_h2_num}: {title}")
            elif level == "###":
                h3_count += 1
                result.append(f"### S{current_h2_num}.{h3_count}: {title}")
        else:
            result.append(line)

    return "\n".join(result)


def _generate_context_md(
    ws: Path, source_dirs: list[str], spec_path: Path | None = None,
    arch_files: list[str] | None = None,
) -> None:
    template = TEMPLATES_DIR / "context.md"
    if template.exists():
        content = template.read_text()
    else:
        content = _default_context_md()
    content = content.replace("{REVIEW_ROOT}", str(ws))

    if spec_path:
        content = content.replace("{SPEC_PATH}", str(spec_path.resolve()))

    source_lines = "\n## Project Sources\n\n"
    for sd in source_dirs:
        source_lines += f"- {sd}\n"
    source_lines += (
        "\nThese directories have full read access. Explore freely — "
        "ARC42STORIES.MD, specs, ADRs, source code, tests, journal.md, "
        "HANDOFF.md, and any other relevant files.\n"
    )
    content += source_lines

    if arch_files:
        arch_lines = "\n## Architectural Files\n\n"
        arch_lines += "These files are authoritative architectural context. Read them before reviewing:\n\n"
        for af in arch_files:
            arch_lines += f"- {af}\n"
        arch_lines += "\n"
        content += arch_lines

    (ws / "context.md").write_text(content)


_MODE_GENERATORS: dict = {}


def _generate_agent_claude_mds(ws: Path, mode: str = "spec-review") -> None:
    generators = _MODE_GENERATORS.get(mode, {})
    for role, template_name, default_fallback in [
        ("reviewer", "reviewer.md", _default_reviewer_md),
        ("implementor", "implementor.md", _default_implementor_md),
    ]:
        target = ws / "agents" / role / "CLAUDE.md"
        mode_template = TEMPLATES_DIR / mode / f"{role}.md"
        base_template = TEMPLATES_DIR / template_name
        if mode_template.exists():
            content = mode_template.read_text()
        elif base_template.exists():
            content = base_template.read_text()
        else:
            gen = generators.get(role, default_fallback)
            content = gen()
        content = content.replace("{REVIEW_ROOT}", str(ws))
        target.write_text(content)


def _init_review_git(ws: Path, adr_root: Path) -> None:
    if not (adr_root / ".git").exists():
        subprocess.run(["git", "init"], cwd=adr_root, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "adr-tool@local"],
                       cwd=adr_root, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "ADR Tool"],
                       cwd=adr_root, capture_output=True, check=True)
        (adr_root / ".gitignore").write_text("progress.log\n.system-prompt.md\n.spec-path\n.status\n.hil-timeout\n")
        subprocess.run(["git", "add", ".gitignore"], cwd=adr_root, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init: adr root"],
                       cwd=adr_root, capture_output=True, check=True)
    # Initial commit for this review in the shared root
    subprocess.run(["git", "add", "-A"], cwd=adr_root, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"review: {ws.parent.name}/{ws.name} setup"],
        cwd=adr_root, capture_output=True, check=True,
    )


def build_claude_command(
    role_dir: Path,
    context_md: Path,
    source_dirs: list[str],
    adr_root: Path,
    model: str,
    budget: float,
    effort: str,
    prompt: str,
    session_id: str | None = None,
) -> list[str]:
    role_claude_md = role_dir / "CLAUDE.md"
    combined = context_md.read_text()
    if role_claude_md.exists():
        combined += "\n\n" + role_claude_md.read_text()

    combined_file = adr_root / "agents" / role_dir.name / ".system-prompt.md"
    combined_file.write_text(combined)

    if session_id:
        return [
            "claude", "-p",
            "--ide",
            "--resume", session_id,
            "--append-system-prompt-file", str(combined_file),
            "--max-budget-usd", str(budget),
            "--effort", effort,
            "--output-format", "json",
            prompt,
        ]

    cmd = [
        "claude", "-p",
        "--ide",
        "--append-system-prompt-file", str(combined_file),
    ]

    for sd in source_dirs:
        cmd.extend(["--add-dir", sd])
    cmd.extend(["--add-dir", str(adr_root)])

    cmd.extend([
        "--model", model,
        "--permission-mode", "acceptEdits",
        "--max-budget-usd", str(budget),
        "--effort", effort,
        "--disallowedTools", "Skill",
        "--output-format", "json",
        prompt,
    ])

    return cmd


# ---------------------------------------------------------------------------
# Default templates (used when templates/ dir doesn't have files yet)
# ---------------------------------------------------------------------------

def _default_context_md() -> str:
    return """\
# Adversarial Design Review — Review Context

## Review Root

Your working directory is:
{REVIEW_ROOT}

File paths in prompts use this absolute path. The paths below
are relative to it.

## Spec Location

The spec under review is at: {SPEC_PATH}
The implementor modifies it in place and commits to the project repo.

## Directory Layout

- tracker.md — issue tracker (maintained by the orchestration script, no agent modifies this)
- responses/ — numbered response files per round (each agent writes only its own)
- decisions/ — human decisions recorded during review pauses
- handovers/ — session sweep outputs for continuity across resets

## Structured Output Format

Your response file MUST use these conventions. The orchestration script
parses them mechanically — deviations cause parse failures.

### Issue headings (reviewer: new issues)

    ### Missing failure mode for payment timeout

### Issue response headings (implementor: responding to issues)

    ### R1-01: FIXED
    ### R1-06: REJECTED
    ### R2-01: ESCALATED

Status must be one of: FIXED, REJECTED, ESCALATED.

Note: FIXED (implementor accepts critique and updates spec) is distinct from
the tracker's ACCEPTED status (reviewer accepts implementor's rejection).

### Section references (implementor: FIXED items)

    Updated §4.1 with terminal PAYMENT_FAILED state.

### Addressed item confirmations (reviewer: rounds 2+)

    ## Addressed Items
    - R1-01: resolved
    - R1-02: still open — no terminal failure state defined

### Assumptions

    ASSUMPTION: Event store supports exactly-once delivery

### Settled decisions (implementor only)

    SETTLED: Strong consistency for all financial aggregate writes (from R1-04)

### Signal (must be the last section of your response)

    ---
    SIGNAL: CONTINUE

Valid signals:
- Reviewer: CONTINUE, APPROVED, DECISION_NEEDED: {description}
- Implementor: CONTINUE, DECISION_NEEDED: {description}

## File Ownership

| Role | May write | Must NOT modify |
|------|-----------|-----------------|
| Reviewer | responses/reviewer-{n}.md | the spec, tracker.md, implementor files |
| Implementor | the spec (at its original path), responses/implementor-{n}.md | tracker.md, reviewer files |

Modifying files outside your ownership will corrupt the review state.
"""


# ---------------------------------------------------------------------------
# Composable constraint elements — each is a self-contained instruction
# ---------------------------------------------------------------------------

_CORE_APPROACH_REVIEWER = """\
Be skeptical and adversarial for the goal of building a better design.
Go deep — be systematic, exhaustive and diligent. Always find and start
with the roots of a problem or design and use first principles. Don't
speculate or guess — always verify, validate and make decisions based on
evidence. Prioritise consistency and coherence, and architectural
consolidation where it makes sense."""

_CORE_APPROACH_IMPLEMENTOR = """\
Go deep — be systematic, exhaustive and diligent. Always find and start
with the roots of a problem or design and use first principles. Don't
speculate or guess — always verify, validate and make decisions based on
evidence. Prioritise consistency and coherence, and architectural
consolidation where it makes sense."""

_IMPLEMENTOR_SKEPTICISM = """\
Be skeptical of the reviewer's critiques, for the goal of building a
better design — verify their evidence and question their proposed
solutions."""

_TODO_CHECK = """\
Look for existing TODO comments in the codebase that the spec's changes
touch or build on — unaddressed TODOs are design debt the spec should
acknowledge."""

_REVIEWER_STARTING_POINTS = """\
Starting points (not restrictions — go beyond these):
- Does the spec's approach align with the epic/issue it references?
- If the spec claims to close an epic/issue, enumerate ALL requirements
  from that epic and check each is addressed. Deferred items are gaps —
  can the epic honestly be closed with them missing?
- Does this hold under load, failure, and evolution?
- Are concepts genuinely distinct or just differently named?
- Does this contradict ARC42STORIES, PLATFORM.md, or protocols?
- What failure modes, edge cases, or completeness gaps exist?
- Do the parts of the spec support each other?
- What does the spec NOT cover that it should?"""

_DEFERRED_ITEMS = """\
Any deferred concerns or out-of-scope items must be captured as GitHub
issues, not just noted in the spec."""

_INTELLIJ_OPEN = """\
Open ONLY your project repo using ide_open_project with the first
source directory from your prompt. Do NOT use ide_open_workspace —
aggregate workspaces with 100+ projects make every MCP call slow.
If you need a second repo for cross-project context, use
ide_import_modules to add just that repo. If ide_open_project fails,
STOP and write "ABORTED: IntelliJ MCP not available.\""""

_INTELLIJ_USE = """\
Use IntelliJ index MCP for all code navigation — never bash grep/find.
Pass project_path on EVERY MCP call to scope to your project — without
it, calls search all open projects and are orders of magnitude slower.
Use ide_find_class, ide_find_references, ide_find_symbol,
ide_find_definition, ide_type_hierarchy, ide_call_hierarchy. When you
need to analyse bytecode of a dependency, use ide_read_file with the
qualified class name — do not download jars."""

_NARRATION = """\
Write a one-line status to {REVIEW_ROOT}/agents/{ROLE}/.status whenever
you start a significant action — reading a file, navigating code,
analysing a section, writing findings. Examples:
  "Reading ARC42STORIES.MD for architectural context"
  "Navigating WorkItemRef type hierarchy via ide_type_hierarchy"
  "Analysing §4.1 payment flow for failure modes"
  "Writing review findings to response file"
This is monitored by the orchestrator and shown in progress.log.
Without it, progress.log is silent for 10+ minutes."""

_ARCH_DOCS = """\
Use ARC42STORIES.MD (look in each source directory listed in context.md),
~/claude/casehub/parent/docs/PLATFORM.md,
~/claude/casehub/parent/docs/APPLICATIONS.md,
~/claude/casehub/garden/docs/protocols/ (start with INDEX.md to find
the relevant sub-index and protocols). These are authoritative — the
spec must be coherent with them."""

_SPECS_AND_ADRS = """\
Prior specs, ADRs, and research are in the docs/ folder of each source
directory listed in context.md, and in ~/claude/casehub/parent/docs/.
Check docs/specs/, docs/adr/, docs/superpowers/specs/, and any other
.md files under docs/ — relevant context can be anywhere. Check all
source directories for cross-cutting decisions."""

_DIARIES = """\
Published diaries at ~/claude/mdproctor.github.io/ contain architectural
decisions, design rationale, and context behind the platform's evolution."""

_GIT_ISSUES = """\
Use `git log`, `git blame`, and `gh issue view` to explore in both
directions: from the spec's referenced issues outward (linked epics,
related commits) and from the topic inward (what relevant history
exists that the spec may not mention)."""

_INTERNET = """\
Search the internet and Google Scholar if you feel the information
available is not comprehensive to drive the best decision making."""

_NO_END_USERS = """\
This platform has no end users — breaking changes cost nothing externally.
Prefer fixing the design over protecting callers. Think on whether early
rearchitecting could lead to cleaner solutions."""

_DESIGN_QUALITY = """\
Design for quality alone — bold, forward-looking, platform-coherent.
- Never let blast radius, call-site count, migration complexity,
  backwards compatibility, or time to implement constrain a design.
- It's OK if a change breaks method calls — the migration is mechanical
  and the breakage is the point, it forces every caller to be explicit.
- Cost (files, migrations, API breaks) is always worth paying.
  Unnecessary complexity (abstractions or layers with no architectural
  benefit) is bad design regardless of cost.
- Before proposing any workaround, wrapper, or backward-compatibility
  shim — stop and ask: is this the right design? If not, fix the design.
- Workarounds and wrappers are bad design unless explicitly asked to
  preserve backward compatibility for this task.
- If "simpler is better" crosses your mind, ask whether the simplicity
  serves the architecture or just avoids work."""

_IMPLEMENTOR_STAND_GROUND = """\
Stand your ground on sound design choices. If a choice is intentional
and defensible, defend it with clear rationale. Convergence toward the
safest common denominator is a failure mode — the goal is the best
design, not the least controversial one."""

# ---------------------------------------------------------------------------
# Pre-review specific constraints
# ---------------------------------------------------------------------------

_PRE_REVIEW_APPROACH_REVIEWER = """\
Be skeptical and adversarial for the goal of finding the best approach.
Challenge the approach itself, not the details — the spec may be an
outline or early draft and implementation details will come later. Focus
on whether this is the right way to solve the problem at all."""

_PRE_REVIEW_STARTING_POINTS = """\
Starting points (not restrictions — go beyond these):
- Are there simpler ways to achieve the same goal?
- Does this align with the platform's architectural trajectory?
- Are there proven patterns, libraries, or industry practices this ignores?
- Will this design age well or create technical debt?
- Is the scope right — too much, too little?
- Does this contradict existing architecture (ARC42STORIES, PLATFORM.md)?
- What are the strongest arguments AGAINST this approach?"""

_PRE_REVIEW_APPROACH_IMPLEMENTOR = """\
You chose this approach for a reason. Defend it where it's sound, pivot
where the reviewer raises a genuine concern. The goal is to commit to
the right approach before investing in detailed spec writing."""

_PRE_REVIEW_IMPLEMENTOR_SKEPTICISM = """\
Be skeptical of the reviewer's alternatives — verify they actually solve
the problem better, not just differently. A genuine improvement is worth
pivoting for; a lateral move is not."""

# ---------------------------------------------------------------------------
# Code review specific constraints
# ---------------------------------------------------------------------------

_CODE_REVIEW_APPROACH_REVIEWER = """\
You are reviewing implementation code against a reviewed design spec.
Read the spec first to understand what was promised, then read the code
to verify it delivers. Your stance is adversarial — assume the code
drifted from the spec until proven otherwise."""

_CODE_REVIEW_STARTING_POINTS = """\
Starting points (not restrictions — go beyond these):
- Does the code deliver every capability the spec promises?
- Are edge cases identified in the spec review handled in the code?
- Are design decisions from the spec reflected in the implementation?
- Is there scope creep — code that does more than the spec specified?
- Are error handling strategies from the spec implemented correctly?
- Do naming conventions in the code match the spec's domain model?
- Are any spec requirements silently dropped or deferred without a TODO?
- Does the test coverage match the spec's stated quality requirements?"""

_CODE_REVIEW_APPROACH_IMPLEMENTOR = """\
You wrote this code to implement the reviewed spec. Defend your
implementation choices where they are sound, fix them where they
genuinely diverge from the spec. If you deliberately deviated from
the spec, explain why — the reviewer needs to know if the spec
should be updated to match."""

_CODE_REVIEW_IMPLEMENTOR_SKEPTICISM = """\
Be skeptical of the reviewer's spec interpretations. The reviewer
reads the spec; you wrote the code AND read the spec. When they
claim a divergence, verify their reading of the spec is correct
before accepting the critique."""


# ---------------------------------------------------------------------------
# Assembly — role-specific composition from shared elements
# ---------------------------------------------------------------------------

def _assemble_constraints(items: list[str]) -> str:
    heading = "## Behavioral constraints — mandatory, do not skip any section below\n\nUse ultrathink.\n\n"
    numbered = []
    n = 0
    for item in items:
        if item.startswith("### "):
            numbered.append(f"\n{item}\n")
        else:
            n += 1
            indented = item.replace("\n", "\n   ")
            numbered.append(f"{n}) {indented}")
    return heading + "\n\n".join(numbered)


def _default_reviewer_md() -> str:
    constraints = _assemble_constraints([
        _CORE_APPROACH_REVIEWER,
        _TODO_CHECK,
        _REVIEWER_STARTING_POINTS,
        _DEFERRED_ITEMS,
        "### Code navigation",
        _INTELLIJ_OPEN,
        _INTELLIJ_USE,
        "### Progress narration",
        _NARRATION.replace("{ROLE}", "reviewer"),
        "### Context sources",
        _ARCH_DOCS,
        _SPECS_AND_ADRS,
        _DIARIES,
        _GIT_ISSUES,
        _INTERNET,
        "### Design philosophy",
        _NO_END_USERS,
        _DESIGN_QUALITY,
    ])
    return f"""\
# Role: Adversarial Design Reviewer

You are an adversarial reviewer of a design specification. Your default stance
is skepticism. Validate what's correct, find what will fail, and propose
better alternatives where the design can be improved.

{constraints}
"""


def _default_implementor_md() -> str:
    constraints = _assemble_constraints([
        _CORE_APPROACH_IMPLEMENTOR,
        _IMPLEMENTOR_SKEPTICISM,
        _DEFERRED_ITEMS,
        "### Code navigation",
        _INTELLIJ_OPEN,
        _INTELLIJ_USE,
        "### Progress narration",
        _NARRATION.replace("{ROLE}", "implementor"),
        "### Context sources",
        _ARCH_DOCS,
        _SPECS_AND_ADRS,
        _DIARIES,
        _GIT_ISSUES,
        _INTERNET,
        "### Design philosophy",
        _NO_END_USERS,
        _DESIGN_QUALITY,
    ])
    return f"""\
# Role: Design Implementor

You are the author of the design specification under review. Revise the spec
where you agree, push back where you don't (with reasoning).

{constraints}

## Your responsibilities

- Address every open item from the tracker
- Even when a critique is valid, explore whether the reviewer's proposed
  solution is the best way. Propose a better approach if you see one —
  present it in your response for the reviewer to evaluate next round.
- Reject invalid critiques with clear, specific rationale
- Escalate genuine design decisions to the human (DECISION_NEEDED)

{_IMPLEMENTOR_STAND_GROUND}
"""


# ---------------------------------------------------------------------------
# Pre-review mode generators
# ---------------------------------------------------------------------------

def _pre_review_reviewer_md() -> str:
    constraints = _assemble_constraints([
        _PRE_REVIEW_APPROACH_REVIEWER,
        _PRE_REVIEW_STARTING_POINTS,
        "### Code navigation",
        _INTELLIJ_OPEN,
        _INTELLIJ_USE,
        "### Progress narration",
        _NARRATION.replace("{ROLE}", "reviewer"),
        "### Context sources",
        _ARCH_DOCS,
        _SPECS_AND_ADRS,
        _DIARIES,
        _GIT_ISSUES,
        _INTERNET,
        "### Design philosophy",
        _NO_END_USERS,
        _DESIGN_QUALITY,
    ])
    return f"""\
# Role: Approach Reviewer

You are reviewing a proposed approach before detailed spec writing begins.
Your job is to challenge the approach itself — is this the right way to
solve the problem? Are there better alternatives? Will this age well?

Do not critique implementation details, section structure, or completeness
of edge cases — those belong in the spec review phase. Focus on the
fundamental direction.

{constraints}
"""


def _pre_review_implementor_md() -> str:
    constraints = _assemble_constraints([
        _PRE_REVIEW_APPROACH_IMPLEMENTOR,
        _PRE_REVIEW_IMPLEMENTOR_SKEPTICISM,
        "### Code navigation",
        _INTELLIJ_OPEN,
        _INTELLIJ_USE,
        "### Progress narration",
        _NARRATION.replace("{ROLE}", "implementor"),
        "### Context sources",
        _ARCH_DOCS,
        _SPECS_AND_ADRS,
        _DIARIES,
        _GIT_ISSUES,
        _INTERNET,
        "### Design philosophy",
        _NO_END_USERS,
        _DESIGN_QUALITY,
    ])
    return f"""\
# Role: Approach Author

You proposed this approach. Defend it where it's sound, pivot where the
reviewer raises a genuine concern. The goal is to commit to the right
approach before investing in detailed spec writing.

{constraints}

## Your responsibilities

- Address every challenge from the tracker
- If the reviewer proposes a better approach, evaluate it honestly —
  pivot if it's genuinely better, not just different
- Reject challenges that misunderstand the problem or the constraints
- Escalate genuine strategic decisions to the human (DECISION_NEEDED)

{_IMPLEMENTOR_STAND_GROUND}
"""


_MODE_GENERATORS["pre-review"] = {
    "reviewer": _pre_review_reviewer_md,
    "implementor": _pre_review_implementor_md,
}


# ---------------------------------------------------------------------------
# Code review mode generators
# ---------------------------------------------------------------------------

def _code_review_reviewer_md() -> str:
    constraints = _assemble_constraints([
        _CODE_REVIEW_APPROACH_REVIEWER,
        _CODE_REVIEW_STARTING_POINTS,
        _TODO_CHECK,
        _DEFERRED_ITEMS,
        "### Code navigation",
        _INTELLIJ_OPEN,
        _INTELLIJ_USE,
        "### Progress narration",
        _NARRATION.replace("{ROLE}", "reviewer"),
        "### Context sources",
        _ARCH_DOCS,
        _SPECS_AND_ADRS,
        _GIT_ISSUES,
        _INTERNET,
    ])
    return f"""\
# Role: Code vs Spec Reviewer

You are reviewing implementation code against a reviewed design specification.
Your job is to verify the code delivers what the spec promised — every
capability, every edge case, every design decision. Find divergences,
scope creep, and silent omissions.

Do not re-review the spec itself — it has already been through adversarial
review. Focus on whether the code faithfully implements it.

{constraints}
"""


def _code_review_implementor_md() -> str:
    constraints = _assemble_constraints([
        _CODE_REVIEW_APPROACH_IMPLEMENTOR,
        _CODE_REVIEW_IMPLEMENTOR_SKEPTICISM,
        _DEFERRED_ITEMS,
        "### Code navigation",
        _INTELLIJ_OPEN,
        _INTELLIJ_USE,
        "### Progress narration",
        _NARRATION.replace("{ROLE}", "implementor"),
        "### Context sources",
        _ARCH_DOCS,
        _SPECS_AND_ADRS,
        _GIT_ISSUES,
        _INTERNET,
    ])
    return f"""\
# Role: Implementation Author

You wrote the code that implements the reviewed spec. Defend your
implementation where it is faithful to the spec. Fix genuine divergences.
Explain deliberate deviations — the spec may need updating to match.

{constraints}

## Your responsibilities

- Address every divergence the reviewer identifies
- Where you deliberately deviated from the spec, explain why and propose
  a spec update if the deviation is an improvement
- Where the reviewer misreads the spec, cite the specific section that
  supports your implementation
- Escalate genuine spec-vs-code conflicts to the human (DECISION_NEEDED)

{_IMPLEMENTOR_STAND_GROUND}
"""


_MODE_GENERATORS["code-review"] = {
    "reviewer": _code_review_reviewer_md,
    "implementor": _code_review_implementor_md,
}


