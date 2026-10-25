"""Validate complete Markdown metadata, not just opening delimiters (CI-only PyYAML)."""
from pathlib import Path
import sys
import yaml

root = Path(__file__).resolve().parents[1]
for path in [*root.glob('skills/*/SKILL.md'), *root.glob('agents/*.md'), *root.glob('commands/*.md')]:
    parts = path.read_text().split('---', 2)
    if len(parts) != 3 or parts[0].strip():
        sys.exit(f'Missing frontmatter: {path}')
    data = yaml.safe_load(parts[1])
    if not isinstance(data, dict) or not isinstance(data.get('description'), str):
        sys.exit(f'Invalid metadata: {path}')
    if path.name == 'SKILL.md' and not data.get('name'):
        sys.exit(f'Missing skill name: {path}')
print('All skill/agent/command YAML frontmatter parses')
