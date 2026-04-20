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
