import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from validate_pr import GARDEN_TYPES, GARDEN_DEFAULT


def test_all_six_gardens_present():
    expected = {'discovery', 'patterns', 'examples', 'evolution', 'risk', 'decisions'}
    assert set(GARDEN_TYPES.keys()) == expected


def test_each_garden_has_valid_types():
    for garden, cfg in GARDEN_TYPES.items():
        assert 'valid_types' in cfg, f"{garden} missing valid_types"
        assert len(cfg['valid_types']) > 0, f"{garden} has empty valid_types"


def test_each_garden_has_required_extra():
    for garden, cfg in GARDEN_TYPES.items():
        assert 'required_extra' in cfg, f"{garden} missing required_extra"
        assert isinstance(cfg['required_extra'], list)


def test_each_garden_has_staleness_default():
    for garden, cfg in GARDEN_TYPES.items():
        assert 'staleness_default' in cfg, f"{garden} missing staleness_default"
        assert isinstance(cfg['staleness_default'], int)


def test_discovery_valid_types():
    assert set(GARDEN_TYPES['discovery']['valid_types']) == {
        'gotcha', 'technique', 'undocumented'
    }


def test_patterns_valid_types():
    assert set(GARDEN_TYPES['patterns']['valid_types']) == {
        'architectural', 'migration', 'integration', 'testing'
    }


def test_examples_valid_types():
    assert GARDEN_TYPES['examples']['valid_types'] == ['code']


def test_evolution_valid_types():
    assert set(GARDEN_TYPES['evolution']['valid_types']) == {
        'breaking', 'deprecation', 'capability'
    }


def test_evolution_requires_changed_in():
    assert 'changed_in' in GARDEN_TYPES['evolution']['required_extra']


def test_risk_valid_types():
    assert set(GARDEN_TYPES['risk']['valid_types']) == {
        'failure-mode', 'antipattern', 'incident'
    }


def test_risk_requires_severity():
    assert 'severity' in GARDEN_TYPES['risk']['required_extra']


def test_decisions_valid_types():
    assert set(GARDEN_TYPES['decisions']['valid_types']) == {
        'architecture', 'technology', 'process'
    }


def test_default_garden_is_discovery():
    assert GARDEN_DEFAULT == 'discovery'


def test_patterns_staleness_longer_than_discovery():
    assert GARDEN_TYPES['patterns']['staleness_default'] > \
           GARDEN_TYPES['discovery']['staleness_default']


def test_risk_staleness_longer_than_evolution():
    assert GARDEN_TYPES['risk']['staleness_default'] > \
           GARDEN_TYPES['evolution']['staleness_default']


from validate_pr import validate
import tempfile, os


def _write_entry(content: str) -> str:
    """Write entry to a temp file and return its path."""
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False)
    try:
        f.write(content)
    finally:
        f.close()
    return f.name


DISCOVERY_ENTRY = """\
---
title: "Test gotcha"
garden: discovery
type: gotcha
domain: jvm
score: 10
tags: [java]
verified: true
staleness_threshold: 730
---

## Problem
Something breaks.

### Root cause
The cause.

### Fix
The fix.

### Why this is non-obvious
The insight.
"""

PATTERNS_ENTRY = """\
---
title: "Pluggable Evaluator Pattern"
garden: patterns
type: architectural
domain: jvm
score: 10
tags: [java, architecture]
verified: true
staleness_threshold: 3650
---

## Pattern
Description here.
"""

EVOLUTION_ENTRY = """\
---
title: "Quarkus 3.x breaks @ApplicationScoped on startup"
garden: evolution
type: breaking
domain: jvm
score: 10
tags: [quarkus]
verified: true
staleness_threshold: 1095
changed_in: "3.0.0"
---

## Change
What changed.
"""

RISK_ENTRY = """\
---
title: "Connection pool exhaustion under exception storm"
garden: risk
type: failure-mode
domain: jvm
score: 10
tags: [jdbc, connection-pool]
verified: true
staleness_threshold: 1825
severity: high
---

## Failure mode
Description.
"""



def test_unknown_garden_fails():
    entry = DISCOVERY_ENTRY.replace('garden: discovery', 'garden: unknown-garden')
    path = _write_entry(entry)
    try:
        result = validate(path)
        assert any('garden' in c.lower() for c in result['criticals'])
    finally:
        os.unlink(path)


def test_type_invalid_for_garden_fails():
    # 'gotcha' is valid for discovery but not for patterns
    entry = PATTERNS_ENTRY.replace('type: architectural', 'type: gotcha')
    path = _write_entry(entry)
    try:
        result = validate(path)
        assert any('type' in c.lower() for c in result['criticals'])
    finally:
        os.unlink(path)


def test_evolution_missing_changed_in_fails():
    entry = EVOLUTION_ENTRY.replace('changed_in: "3.0.0"\n', '')
    path = _write_entry(entry)
    try:
        result = validate(path)
        assert any('changed_in' in c for c in result['criticals'])
    finally:
        os.unlink(path)


def test_risk_missing_severity_fails():
    entry = RISK_ENTRY.replace('severity: high\n', '')
    path = _write_entry(entry)
    try:
        result = validate(path)
        assert any('severity' in c for c in result['criticals'])
    finally:
        os.unlink(path)


def test_no_garden_field_defaults_to_discovery():
    # Existing entries without garden field — backward compatible
    entry = DISCOVERY_ENTRY.replace('garden: discovery\n', '')
    path = _write_entry(entry)
    try:
        result = validate(path)
        assert result['criticals'] == [], result['criticals']
    finally:
        os.unlink(path)


EXAMPLES_ENTRY = """\
---
title: "Multi-datasource Quarkus configuration"
garden: examples
type: code
domain: jvm
score: 9
tags: [quarkus, datasource]
verified: true
staleness_threshold: 1095
---

## Example

Minimal working example here.
"""

DECISIONS_ENTRY = """\
---
title: "Vert.x over Netty as Quarkus reactive engine"
garden: decisions
type: architecture
domain: jvm
score: 10
tags: [quarkus, vertx, netty]
verified: true
staleness_threshold: 3650
---

## Decision
Chose Vert.x.

### Alternatives considered
- Netty: lower-level, more boilerplate
"""


def test_all_six_gardens_happy_path():
    """Each garden type must produce a passing validation with a valid entry."""
    entries = {
        'discovery': DISCOVERY_ENTRY,
        'patterns': PATTERNS_ENTRY,
        'examples': EXAMPLES_ENTRY,
        'evolution': EVOLUTION_ENTRY,
        'risk': RISK_ENTRY,
        'decisions': DECISIONS_ENTRY,
    }
    for garden, content in entries.items():
        path = _write_entry(content)
        try:
            result = validate(path)
            assert result['criticals'] == [], \
                f"{garden}-garden entry failed: {result['criticals']}"
        finally:
            os.unlink(path)


def test_each_invalid_type_rejected_per_garden():
    """Types from other gardens are rejected by each garden."""
    cross_type_cases = [
        ('patterns', 'gotcha'),
        ('examples', 'architectural'),
        ('evolution', 'code'),
        ('risk', 'breaking'),
        ('decisions', 'failure-mode'),
        ('discovery', 'architecture'),
    ]
    base_entries = {
        'patterns': PATTERNS_ENTRY,
        'examples': EXAMPLES_ENTRY,
        'evolution': EVOLUTION_ENTRY,
        'risk': RISK_ENTRY,
        'decisions': DECISIONS_ENTRY,
        'discovery': DISCOVERY_ENTRY,
    }
    for garden, wrong_type in cross_type_cases:
        fixture = base_entries[garden]
        # Find the valid type that actually appears in the fixture
        original_type = next(
            t for t in GARDEN_TYPES[garden]['valid_types']
            if f'type: {t}' in fixture
        )
        entry = fixture.replace(f'type: {original_type}', f'type: {wrong_type}')
        path = _write_entry(entry)
        try:
            result = validate(path)
            assert any('type' in c.lower() for c in result['criticals']), \
                f"{garden}-garden accepted invalid type '{wrong_type}'"
        finally:
            os.unlink(path)


from validate_pr import validate_patterns_extended


def test_patterns_extended_valid_observed_in_no_warnings():
    fm = {
        'observed_in': [
            {'project': 'serverless-workflow', 'url': 'https://github.com/x', 'first_seen': '2022-03-14'}
        ]
    }
    warnings = validate_patterns_extended(fm)
    assert warnings == []


def test_patterns_extended_observed_in_not_list():
    fm = {'observed_in': 'serverless-workflow'}
    warnings = validate_patterns_extended(fm)
    assert any('observed_in' in w and 'list' in w.lower() for w in warnings)


def test_patterns_extended_observed_in_item_missing_project():
    fm = {'observed_in': [{'url': 'https://github.com/x'}]}
    warnings = validate_patterns_extended(fm)
    assert any('observed_in' in w and 'project' in w for w in warnings)


def test_patterns_extended_valid_authors_no_warnings():
    fm = {
        'authors': [
            {'github_handle': 'fabian-martinez', 'role': 'originator'},
            {'github_handle': 'sanne-grinovero', 'role': 'innovator'},
        ]
    }
    warnings = validate_patterns_extended(fm)
    assert warnings == []


def test_patterns_extended_authors_not_list():
    fm = {'authors': {'github_handle': 'fabian-martinez', 'role': 'originator'}}
    warnings = validate_patterns_extended(fm)
    assert any('authors' in w and 'list' in w.lower() for w in warnings)


def test_patterns_extended_authors_item_missing_github_handle():
    fm = {'authors': [{'role': 'originator'}]}
    warnings = validate_patterns_extended(fm)
    assert any('authors' in w and 'github_handle' in w for w in warnings)


def test_patterns_extended_authors_invalid_role():
    fm = {'authors': [{'github_handle': 'fabian-martinez', 'role': 'creator'}]}
    warnings = validate_patterns_extended(fm)
    assert any('authors' in w and 'role' in w for w in warnings)


def test_patterns_extended_authors_item_missing_role():
    fm = {'authors': [{'github_handle': 'fabian-martinez'}]}
    warnings = validate_patterns_extended(fm)
    assert any('authors' in w and 'role' in w for w in warnings)


def test_patterns_extended_empty_fm_no_warnings():
    warnings = validate_patterns_extended({})
    assert warnings == []


import subprocess
import json

SCRIPT = str(Path(__file__).parent.parent / 'scripts' / 'validate_pr.py')


def test_cli_discovery_entry_exits_zero():
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False)
    try:
        f.write(DISCOVERY_ENTRY)
    finally:
        f.close()
    try:
        r = subprocess.run(['python3', SCRIPT, f.name], capture_output=True, text=True)
        data = json.loads(r.stdout)
        assert r.returncode == 0, f"Expected exit 0, got {r.returncode}: {data}"
        assert data['criticals'] == []
    finally:
        os.unlink(f.name)


def test_cli_invalid_garden_exits_one():
    entry = DISCOVERY_ENTRY.replace('garden: discovery', 'garden: bogus')
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False)
    try:
        f.write(entry)
    finally:
        f.close()
    try:
        r = subprocess.run(['python3', SCRIPT, f.name], capture_output=True, text=True)
        assert r.returncode == 1
        data = json.loads(r.stdout)
        assert any('garden' in c.lower() for c in data['criticals'])
    finally:
        os.unlink(f.name)


def test_cli_all_six_gardens_exit_zero():
    entries = [
        DISCOVERY_ENTRY, PATTERNS_ENTRY, EXAMPLES_ENTRY,
        EVOLUTION_ENTRY, RISK_ENTRY, DECISIONS_ENTRY,
    ]
    for content in entries:
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False)
        try:
            f.write(content)
        finally:
            f.close()
        try:
            r = subprocess.run(['python3', SCRIPT, f.name], capture_output=True, text=True)
            data = json.loads(r.stdout)
            assert r.returncode == 0, f"CLI failed: {data['criticals']}"
        finally:
            os.unlink(f.name)
