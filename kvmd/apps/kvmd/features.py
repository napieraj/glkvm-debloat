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


"""The feature registry: an extension point for API components.

Route DISCOVERY was always dynamic -- `HttpServer._add_exposed()` reflects over
any object for `@exposed_http` and `@exposed_ws` methods, so a component needs
no registration to have its routes bound. What was hardcoded is the LIST: a
literal in `server.py` naming every component. Anything wanting an endpoint had
to be added to it, which is why WebAuthn and MCP both edit `server.py` despite
being otherwise self-contained, and why `SwitchApi` sits in that list commented
out with a conditional append below it. Three instances of the same pressure.

This module turns the list into a registry. A feature declares itself and is
built only when enabled, so `kvmd/plugins/`'s five DRIVER categories (atx, auth,
hid, msd, ugpio) are joined by a category for FEATURES -- things that add an
endpoint rather than drive a piece of hardware.

## The pre-auth declaration is the point

A registry that only assembled components would be a convenience. The reason
this one is worth having is that it makes the unauthenticated surface a
per-feature contract instead of a global count.

`testenv/tests/test_attestation.py` asserts the whole daemon exposes at most a
handful of routes with `auth_required=False`. That assertion is correct and it
is also brittle in a specific way: every feature that legitimately needs a
pre-auth endpoint trips it, and the cheap way out is to raise the bound -- which
silently also licenses the NEXT one. Merging the WebAuthn branch trips it
exactly this way, because a challenge must be obtainable before anyone is
authenticated.

So a feature must declare, by name, every `(method, path)` it exposes without
authentication. `build_enabled()` compares the declaration against what the
component actually exposes and refuses on ANY difference:

  * a route exposed pre-auth but NOT declared is privilege escalation by
    accident -- the case this exists to stop;
  * a route declared but NOT exposed is a stale declaration, and it is the
    dangerous direction, because it is a licence sitting unused that a later
    edit can silently fill.

Refusal is a hard failure at construction, not a log line: a daemon that came up
with an undeclared pre-auth endpoint would be exactly the outcome the check is
for. The attestation test then sums the declarations of enabled features, so
adding a pre-auth route takes two deliberate acts in two files.

## Rule 6

Every feature states its mode (local-only / cloud-managed / both) and the core
interface it registers against, because a module that does not say what it needs
cannot be reasoned about when it is disabled.
"""

import dataclasses

from typing import Callable
from typing import Iterable

from ...htserver import get_exposed_http


# =====
MODES = ("local-only", "cloud-managed", "both")


class FeatureError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class Feature:
    name: str
    mode: str
    core: str
    unauth: frozenset  # of (METHOD, path) exposed without authentication
    build: Callable    # (**deps) -> object, the API component

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("_", "").isalnum():
            raise FeatureError(f"Bad feature name {self.name!r}")
        if self.mode not in MODES:
            raise FeatureError(f"Feature {self.name!r} declares mode {self.mode!r}, expected one of {MODES}")
        if not self.core:
            raise FeatureError(f"Feature {self.name!r} declares no core dependency")
        for item in self.unauth:
            if not (isinstance(item, tuple) and len(item) == 2):
                raise FeatureError(f"Feature {self.name!r} has a malformed unauth entry {item!r}")


_REGISTRY: dict = {}


def register(feature: Feature) -> Feature:
    if feature.name in _REGISTRY:
        raise FeatureError(f"Feature {feature.name!r} is already registered")
    _REGISTRY[feature.name] = feature
    return feature


def get(name: str) -> Feature:
    if name not in _REGISTRY:
        # Unknown means refuse, never skip: a typo in a config must not read as
        # "that feature is off".
        raise FeatureError(f"Unknown feature {name!r}; registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def names() -> list:
    return sorted(_REGISTRY)


def declared_unauth(enabled: Iterable) -> set:
    """The pre-auth surface the enabled features are permitted, as declared."""

    surface: set = set()
    for name in enabled:
        surface |= set(get(name).unauth)
    return surface


def _actual_unauth(component: object) -> set:
    exposed: list = get_exposed_http(component)
    return {(item.method, item.path) for item in exposed if not item.auth_required}


def build_enabled(enabled: Iterable, **deps) -> list:
    """Builds each enabled feature and verifies its declared pre-auth surface.

    Raises FeatureError rather than returning a partial list: coming up with an
    undeclared unauthenticated endpoint is the failure this exists to prevent,
    so it must not be survivable.
    """

    components: list = []
    for name in enabled:
        feature = get(name)
        component = feature.build(**deps)
        actual = _actual_unauth(component)
        declared = set(feature.unauth)
        undeclared = actual - declared
        if undeclared:
            raise FeatureError(
                f"Feature {name!r} exposes unauthenticated routes it does not declare: "
                f"{sorted(undeclared)}. Add them to the feature's `unauth` set and to the "
                f"attestation bound, deliberately.")
        stale = declared - actual
        if stale:
            raise FeatureError(
                f"Feature {name!r} declares unauthenticated routes it does not expose: "
                f"{sorted(stale)}. A declaration wider than reality is a licence a later "
                f"edit fills silently; narrow it.")
        components.append(component)
    return components
