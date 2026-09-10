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

from typing import Any


# =====
# A STATIC inventory of every @exposed_http route declared under
# kvmd/apps/kvmd/, used as the before-and-after guard for the kvmd-lean strip
# (docs/lean-plan.md step 2). It exists so that removing a module proves it
# removed exactly the routes it was supposed to and no others.
#
# Static, not runtime, for three reasons: it needs no server instance and no
# MODEL_PATH monkeypatch; it catches multi-line decorators that a line-oriented
# grep misses (the tree's only one, api/upgrade.py's GET /upgrade/gui_compare,
# went with step 6 -- the AST walk stays so a reintroduced one cannot slip the
# inventory); and it is honest about conditional registration. SwitchApi is only registered
# when the hardware model is rm4pe (apps/kvmd/__init__.py), so its routes are
# DECLARED here but are not served on an RM1PE. This file answers "what does
# the source declare", which is the question a strip needs answered.
#
# To regenerate after an intentional change:
#   python3 -c "import testenv.tests.test_routes as t; print(t.dump_routes())" \
#       > testenv/tests/routes.txt
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "kvmd", "apps", "kvmd")
_FIXTURE = os.path.join(os.path.dirname(__file__), "routes.txt")


def _literal(node: (ast.AST | None), default: Any) -> Any:
    if node is None:
        return default
    try:
        return ast.literal_eval(node)
    except ValueError:
        return "<non-literal>"


def _format_route(call: ast.Call) -> str:
    args = list(call.args)
    kwargs = {kw.arg: kw.value for kw in call.keywords if kw.arg is not None}

    method = _literal(args[0] if len(args) > 0 else kwargs.get("http_method"), "?")
    path = _literal(args[1] if len(args) > 1 else kwargs.get("path"), "?")
    auth = _literal(args[2] if len(args) > 2 else kwargs.get("auth_required"), True)
    usc = _literal(args[3] if len(args) > 3 else kwargs.get("allow_usc"), True)
    exes = _literal(args[4] if len(args) > 4 else kwargs.get("allowed_exe_paths"), None)

    exe_text = ",".join(sorted(exes)) if exes else "-"
    return f"{method} {path} auth={auth} usc={usc} exe={exe_text}"


def collect_routes() -> list[str]:
    routes: list[str] = []
    for (dirpath, _, filenames) in os.walk(_ROOT):
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8") as file:
                tree = ast.parse(file.read(), filename=path)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
                        if dec.func.id == "exposed_http":
                            routes.append(_format_route(dec))
    return sorted(routes)


def dump_routes() -> str:
    return "\n".join(collect_routes())


# =====
def test_ok__route_inventory_unchanged() -> None:
    with open(_FIXTURE, encoding="utf-8") as file:
        expected = file.read().strip().split("\n")
    actual = collect_routes()

    missing = [r for r in expected if r not in actual]
    added = [r for r in actual if r not in expected]

    assert not missing, f"routes disappeared from the source: {missing}"
    assert not added, f"routes appeared in the source: {added}"
    assert len(actual) == len(expected)
