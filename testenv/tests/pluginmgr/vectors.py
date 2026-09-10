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
import json
import base64


# =====
# The conformance vectors are the shared test contract. Both repos vendor the
# identical contract/plugins tree and run their own suite against it, so a
# divergence between the Python and Go implementations is caught by each repo's
# own tests rather than at integration time.

CONTRACT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "contract", "plugins"))
VECTORS_PATH = os.path.join(CONTRACT_PATH, "vectors")


def load_vectors(name: str) -> dict:
    with open(os.path.join(VECTORS_PATH, name), "rb") as file:
        return json.loads(file.read())


def load_cases(name: str) -> list[dict]:
    cases = load_vectors(name)["cases"]
    assert cases, f"no vectors loaded from {name}"
    return cases


def load_blob(name: str) -> bytes:
    with open(os.path.join(VECTORS_PATH, "blobs", name), "rb") as file:
        return file.read()


def b64(text: str) -> bytes:
    return base64.b64decode(text)


def case_ids(cases: list[dict]) -> list[str]:
    return [case["id"] for case in cases]
