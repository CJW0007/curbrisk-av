"""Fail closed before labeling inputs as the frozen source revision."""
from pathlib import Path
import hashlib

SOURCE_COMMIT = '06fdb2e928ab133f799015ae01323c991669ddcd'
EXPECTED_HASHES = {
    'data/AV-Brick-Report.xlsx': 'cd01c0ec475a979b03dc74078dbd4ed97fc216d3342c9621f0ddf27051b60a54',
    'data/AV-Brick-Report-analyzed.xlsx': 'e18d64c797a6548d81f1b23c6e3ec869b7e3907e358ce4fdfd22e130430edee1',
    'data/labels/scope_exclusions.csv': '8d0d7e97232bed52d22dc381473981b7c1b39faf401e51ba1ba21722bc610f2d',
    'data/labels/evidence_flags.csv': '16276ee94b84589436bbbf6e29aa04ddd3ceb0cacef77372dbcd3e73915f255e',
}

def verify_source(source_dir):
    actual = {}
    for relative, expected in EXPECTED_HASHES.items():
        path = Path(source_dir) / relative
        if not path.is_file():
            raise ValueError(f'Missing frozen source file: {relative}')
        actual[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual[relative] != expected:
            raise ValueError(f'Source hash mismatch: {relative}; do not assign the pinned commit to this input')
    return actual
