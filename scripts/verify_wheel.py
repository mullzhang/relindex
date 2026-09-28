"""Check wheel metadata, a rebuilt sdist, and examples outside the checkout."""

import email
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd):
    subprocess.run([str(arg) for arg in args], cwd=cwd, check=True)


def main():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    stem = f"relindex-{project['version']}"
    wheel = ROOT / "dist" / f"{stem}-py3-none-any.whl"
    sdist = ROOT / "dist" / f"{stem}.tar.gz"
    with zipfile.ZipFile(wheel) as archive:
        members = archive.namelist()
        metadata = email.message_from_bytes(archive.read(f"{stem}.dist-info/METADATA"))
        if metadata.get_all("Requires-Dist"):
            raise RuntimeError("The core wheel must have no runtime dependencies")
        if "relindex/py.typed" not in members:
            raise RuntimeError("The wheel is missing its typing marker")
        original_source = {
            name: archive.read(name) for name in members if name.startswith("relindex/")
        }
    with tempfile.TemporaryDirectory(prefix="relindex-wheel-") as tmp:
        work = Path(tmp)
        run("uv", "build", "--wheel", sdist, "--out-dir", work / "rebuilt", cwd=work)
        with zipfile.ZipFile(work / "rebuilt" / wheel.name) as archive:
            rebuilt_source = {
                name: archive.read(name)
                for name in archive.namelist()
                if name.startswith("relindex/")
            }
        if rebuilt_source != original_source:
            raise RuntimeError("The source distribution does not reproduce the package source")

        environment = work / "venv"
        run("uv", "venv", environment, "--python", sys.executable, cwd=work)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run("uv", "pip", "install", "--python", python, "--no-deps", wheel, cwd=work)
        run(
            python,
            "-I",
            "-c",
            """
import importlib.metadata
from pathlib import Path
import sys
import relindex
from relindex import Relation
assert Path(relindex.__file__).is_relative_to(Path(sys.prefix))
assert set(d.metadata['Name'] for d in importlib.metadata.distributions()) == {'relindex'}
a = Relation([(1, 'x'), (1, 'x'), (2, 'y')], schema=('worker', 'skill'))
b = Relation([('task', 'x')], schema=('task', 'skill'))
e = a.join(b, on=('skill',)).project('worker', 'task')
assert e.tuples() == ((1, 'task'),)
d = Relation([('task',), ('uncovered',)], schema=('task',))
assert e.group_by('task', over=d)[('uncovered',)] == ()
m = Relation.from_mapping({'task': [1, 1], 'uncovered': []}, key='task', value='worker')
assert m.project('worker', 'task') == e
assert m.to_mapping(key='task', value='worker', over=d) == {'task': (1,), 'uncovered': ()}
print('Core wheel works with no installed dependencies outside the source tree.')
""",
            cwd=work,
        )

        requirements = work / "examples.txt"
        run(
            "uv",
            "export",
            "--locked",
            "--only-group",
            "examples",
            "--no-emit-project",
            "--no-header",
            "--no-annotate",
            "--output-file",
            requirements,
            "--quiet",
            cwd=ROOT,
        )
        run(
            "uv",
            "pip",
            "install",
            "--python",
            python,
            "--require-hashes",
            "-r",
            requirements,
            cwd=work,
        )
        for name in ("assignment.py", "network.py", "dictionary_assignment.py"):
            shutil.copy2(ROOT / "examples" / name, work / name)
            run(python, "-I", work / name, cwd=work)
    print("Wheel, sdist, and all standalone examples verified.")


if __name__ == "__main__":
    main()
