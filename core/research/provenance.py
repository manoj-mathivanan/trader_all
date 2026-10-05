"""Identify the actual working sources, including uncommitted code, for replay."""
import hashlib
import platform
import subprocess
import sys
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError

ROOT = Path(__file__).resolve().parents[2]


def capture():
    files = {}
    for folder in ('core', 'strategies', 'dashboard', 'reference_data'):
        for path in sorted((ROOT / folder).rglob('*')):
            if path.is_file() and path.suffix in ('.py', '.js', '.json', '.html', '.css') and 'vendor' not in path.parts:
                files[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ('requirements-lock.txt', 'package-lock.json'):
        path = ROOT / name
        if path.exists():
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    import json
    git = {'commit': None, 'dirty': None}
    try:
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, timeout=5)
        status = subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True, timeout=5)
        if commit.returncode == 0:
            git['commit'] = commit.stdout.strip()
        if status.returncode == 0:
            git['dirty'] = bool(status.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass  # Docker may not include .git; exact source hashes remain available.
    packages = {}
    for name in ('pydantic', 'fastapi', 'httpx', 'cryptography'):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {'version': 1, 'git': git, 'python': sys.version.split()[0], 'platform': platform.system(),
            'packages': packages, 'source_files': files,
            'source_tree_sha256': hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}
