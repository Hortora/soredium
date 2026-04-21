"""Structural feature extractor — regex-based, no compiler required."""
import re
from pathlib import Path

_JAVA_EXTS = {'.java', '.kt'}
_PYTHON_EXTS = {'.py'}
_SOURCE_EXTS = _JAVA_EXTS | _PYTHON_EXTS

_RE_JAVA_INTERFACE = re.compile(r'\b(?:interface|abstract\s+class)\b')
_RE_JAVA_INJECT = re.compile(r'@(?:Inject|Autowired|ApplicationScoped|RequestScoped|SessionScoped|Singleton)')
_RE_JAVA_EXTENDS = re.compile(r'\bclass\s+\w+(?:\s*<[^>]*>)?\s+(?:extends|implements)\b')
_RE_PYTHON_INJECT = re.compile(r'def __init__\s*\(self(?:,\s*\w+:\s*\w+)+\)')


def extract_features(root: Path) -> dict:
    root = Path(root)
    interface_count = 0
    injection_points = 0
    extension_signatures = 0
    spi_patterns = 0
    file_count = 0

    for path in root.rglob('*'):
        if not path.is_file():
            continue

        # SPI services files — any file in META-INF/services directory
        if 'META-INF/services' in str(path):
            spi_patterns += 1
            continue

        if path.suffix not in _SOURCE_EXTS:
            continue

        file_count += 1
        text = path.read_text(errors='replace')

        if path.suffix in _JAVA_EXTS:
            interface_count += len(_RE_JAVA_INTERFACE.findall(text))
            injection_points += len(_RE_JAVA_INJECT.findall(text))
            extension_signatures += len(_RE_JAVA_EXTENDS.findall(text))
        elif path.suffix in _PYTHON_EXTS:
            injection_points += len(_RE_PYTHON_INJECT.findall(text))

    abstraction_depth = round(interface_count / file_count, 3) if file_count else 0.0

    return {
        'interface_count': interface_count,
        'abstraction_depth': abstraction_depth,
        'injection_points': injection_points,
        'extension_signatures': extension_signatures,
        'file_count': file_count,
        'spi_patterns': spi_patterns,
    }