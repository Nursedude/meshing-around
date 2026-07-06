# pytest scaffolding for meshing-around
#
# The bot's modules import third-party packages (geopy, maidenhead, bs4,
# ephem) and read config.ini + write logs/ relative to the CWD at import
# time. This conftest makes the modules importable on any box — no radio,
# no full dependency install — by:
#   1. stubbing the third-party packages the tested logic never exercises
#   2. running the suite from a temp dir seeded with config.template
#
# mesh_bot.py itself is NOT importable (it opens the radio interface at
# import). Functions from it are tested via load_function(), which extracts
# a single function from the AST and exec's it against stub globals.

import ast
import shutil
import sys
import tempfile
import types
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _ensure_stub(name, **attrs):
    if name in sys.modules:
        return
    try:
        __import__(name)
        return  # real module available, prefer it
    except ImportError:
        pass
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod


class _StubNominatim:  # pragma: no cover - never exercised by tests
    def __init__(self, *args, **kwargs):
        pass

    def reverse(self, *args, **kwargs):
        raise RuntimeError("stub Nominatim used in tests")


_ensure_stub("geopy")
_ensure_stub("geopy.geocoders", Nominatim=_StubNominatim)
_ensure_stub("maidenhead", to_maiden=lambda lat, lon: "CM87")
_ensure_stub("bs4", BeautifulSoup=object)
_ensure_stub("ephem")

# run from a temp dir so modules.settings auto-config and modules.log file
# handlers never touch the repo checkout
_workdir = Path(tempfile.mkdtemp(prefix="meshing-around-tests-"))
shutil.copy(REPO_ROOT / "config.template", _workdir / "config.ini")
(_workdir / "logs").mkdir()
(_workdir / "data").mkdir()
os.chdir(_workdir)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


import pytest


@pytest.fixture(autouse=True)
def _clear_fetch_caches():
    """ttl_cache state must never leak between tests."""
    try:
        from modules.fetch_cache import clear_all_caches
    except ImportError:
        yield
        return
    clear_all_caches()
    yield
    clear_all_caches()


def load_function(relative_path, func_name, namespace):
    """Extract one function from a source file and exec it against stub
    globals. Lets tests drive mesh_bot.py logic without importing the
    radio stack."""
    source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    func = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == func_name
    )
    module = ast.Module(body=[func], type_ignores=[])
    exec(compile(module, str(relative_path), "exec"), namespace)
    return namespace[func_name]


def parsed_source(relative_path):
    source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    return ast.parse(source), source
