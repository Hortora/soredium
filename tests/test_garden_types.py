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


def test_valid_discovery_entry_passes():
    path = _write_entry(DISCOVERY_ENTRY)
    try:
        result = validate(path)
        assert result['criticals'] == [], result['criticals']
    finally:
        os.unlink(path)


def test_valid_patterns_entry_passes():
    path = _write_entry(PATTERNS_ENTRY)
    try:
        result = validate(path)
        assert result['criticals'] == [], result['criticals']
    finally:
        os.unlink(path)


def test_valid_evolution_entry_passes():
    path = _write_entry(EVOLUTION_ENTRY)
    try:
        result = validate(path)
        assert result['criticals'] == [], result['criticals']
    finally:
        os.unlink(path)


def test_valid_risk_entry_passes():
    path = _write_entry(RISK_ENTRY)
    try:
        result = validate(path)
        assert result['criticals'] == [], result['criticals']
    finally:
        os.unlink(path)


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
