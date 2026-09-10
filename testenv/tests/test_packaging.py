# ========================================================================== #
#                                                                            #
#    KVMD - The main PiKVM daemon.                                           #
#                                                                            #
#    Copyright (C) 2018-2024  Maxim Devaev <mdevaev@gmail.com>               #
#                                                                            #
#    This program is free software: you can redistribute it and/or modify    #
#    it under the terms of the GNU General Public License as published by    #
#    the Free Software Foundation, either version 3 of the License, or       #
#    (at your option) any later version.                                     #
#                                                                            #
#    This program is distributed in the hope that it will be useful,         #
#    but WITHOUT ANY WARRANTY; without even the implied warranty of          #
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the           #
#    GNU General Public License for more details.                            #
#                                                                            #
#    You should have received a copy of the GNU General Public License       #
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.  #
#                                                                            #
# ========================================================================== #


import os
import ast


# =====
# setup.py enumerates packages by hand rather than using find_packages(), so a
# new subpackage ships only if someone remembers to add it. Nobody did, five
# times: kvmd.pluginmgr, kvmd.apps.kvmd.switch, kvmd.apps.localhid,
# kvmd.apps.media and kvmd.apps.swctl all had an __init__.py on disk and no
# entry in `packages`.
#
# kvmd.apps.kvmd.switch is the one that was already live rather than latent --
# kvmd/apps/kvmd/__init__.py imports `from .switch import Switch`
# unconditionally, so an installed kvmd would have failed at import. Nothing
# caught it because the test suite runs from a source checkout, where every
# directory is importable whether or not it is packaged.
#
# This is the same shape as the guards this project keeps finding vacuous: the
# thing that would notice was scoped somewhere it could not see.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _declared_packages() -> set:
    with open(os.path.join(_ROOT, "setup.py"), encoding="utf-8") as file:
        tree = ast.parse(file.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "packages":
            return {element.value for element in node.value.elts}
    raise AssertionError("setup.py has no packages= keyword")


def _packages_on_disk() -> set:
    found = set()
    for (dirpath, dirnames, filenames) in os.walk(os.path.join(_ROOT, "kvmd")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        if "__init__.py" in filenames:
            rel = os.path.relpath(dirpath, _ROOT)
            found.add(rel.replace(os.sep, "."))
    return found


def test_root_resolves_to_the_repo_not_one_level_short() -> None:
    # The _ROOT hazard: testenv/tests has the repo root as its GRANDPARENT, and
    # a path one level short makes every check below pass vacuously.
    assert os.path.isfile(os.path.join(_ROOT, "setup.py")), _ROOT
    assert os.path.isdir(os.path.join(_ROOT, "kvmd")), _ROOT


def test_every_package_on_disk_is_declared_in_setup_py() -> None:
    on_disk = _packages_on_disk()
    assert len(on_disk) > 30, f"only found {len(on_disk)} packages; _ROOT is probably wrong"
    missing = sorted(on_disk - _declared_packages())
    assert not missing, f"packages with an __init__.py that setup.py will not ship: {missing}"


def test_setup_py_declares_nothing_that_is_not_on_disk() -> None:
    # The other direction: a stale entry means a rename shipped a phantom.
    stale = sorted(_declared_packages() - _packages_on_disk())
    assert not stale, f"setup.py declares packages that do not exist: {stale}"
