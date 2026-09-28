"""Check local documentation links, code fences, and API examples."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    names = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "*.md"],
        cwd=ROOT,
        text=True,
    ).split("\0")
    paths = [ROOT / name for name in names if name and (ROOT / name).is_file()]
    for path in paths:
        text = path.read_text()
        if sum(line.startswith("```") for line in text.splitlines()) % 2:
            raise ValueError(f"Unclosed code fence in {path.relative_to(ROOT)}")
        for link in re.findall(r"\]\(([^)]+)\)", text):
            if "://" in link or link.startswith("#"):
                continue
            target = path.parent / link.split("#", 1)[0]
            if not target.exists():
                raise ValueError(f"Broken link in {path.relative_to(ROOT)}: {link}")
    for name in ("README.md", "docs/api.md"):
        namespace = {}
        for block in re.findall(r"```python\n(.*?)\n```", (ROOT / name).read_text(), re.S):
            exec(compile(block, name, "exec"), namespace)
    print(f"Local links and code fences checked in {len(paths)} files; API examples passed.")


if __name__ == "__main__":
    main()
