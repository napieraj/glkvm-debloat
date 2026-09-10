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


from typing import Generator

import pytest

from kvmd.htserver import exposed_http
from kvmd.apps.kvmd import features
from kvmd.apps.kvmd.features import Feature
from kvmd.apps.kvmd.features import FeatureError


# =====
@pytest.fixture(autouse=True)
def _isolated_registry() -> Generator[None, None, None]:
    # The registry is module-global and server.py registers into it at import
    # time, so a test that added to it without restoring would leak into every
    # later test in the session.
    saved = dict(features._REGISTRY)  # pylint: disable=protected-access
    try:
        yield
    finally:
        features._REGISTRY.clear()  # pylint: disable=protected-access
        features._REGISTRY.update(saved)  # pylint: disable=protected-access


class _Quiet:
    @exposed_http("GET", "/quiet/state")
    async def _state(self, _req: object) -> None:
        pass


class _Loud:
    # Two routes, one of them pre-auth.
    @exposed_http("GET", "/loud/state")
    async def _state(self, _req: object) -> None:
        pass

    @exposed_http("GET", "/loud/challenge", auth_required=False)
    async def _challenge(self, _req: object) -> None:
        pass


def _feature(name: str, cls: type, unauth: frozenset) -> Feature:
    return Feature(name=name, mode="local-only", core="test", unauth=unauth,
                   build=(lambda **_: cls()))


# ===== the registry itself =====
def test_ok__a_correctly_declared_feature_builds() -> None:
    features.register(_feature("quiet", _Quiet, frozenset()))
    built = features.build_enabled(["quiet"])
    assert len(built) == 1 and isinstance(built[0], _Quiet)


def test_ok__a_declared_pre_auth_route_is_permitted() -> None:
    features.register(_feature("loud", _Loud, frozenset({("GET", "/loud/challenge")})))
    assert len(features.build_enabled(["loud"])) == 1


def test_fail__an_undeclared_pre_auth_route_is_refused() -> None:
    """
    The escalation direction. A feature that quietly exposes an
    unauthenticated endpoint is exactly what the registry exists to stop, and
    it must fail at construction rather than log -- a daemon that came up
    serving an undeclared pre-auth route has already lost.
    """

    features.register(_feature("loud", _Loud, frozenset()))
    with pytest.raises(FeatureError) as caught:
        features.build_enabled(["loud"])
    assert "/loud/challenge" in str(caught.value)


def test_fail__a_declared_but_unexposed_route_is_refused() -> None:
    """
    The vacuity direction, and the one that reads as safe.

    A declaration wider than reality breaks nothing today. It is a licence
    sitting unused, and the next edit that adds `/quiet/challenge` pre-auth
    passes the check silently because permission was already granted. Every
    other vacuous guard in this project had this shape.
    """

    features.register(_feature("quiet", _Quiet, frozenset({("GET", "/quiet/challenge")})))
    with pytest.raises(FeatureError) as caught:
        features.build_enabled(["quiet"])
    assert "/quiet/challenge" in str(caught.value)


def test_fail__an_unknown_feature_is_refused_not_skipped() -> None:
    # A typo in a config must not read as "that feature is off".
    with pytest.raises(FeatureError):
        features.build_enabled(["nosuchfeature"])


def test_fail__a_duplicate_registration_is_refused() -> None:
    features.register(_feature("quiet", _Quiet, frozenset()))
    with pytest.raises(FeatureError):
        features.register(_feature("quiet", _Quiet, frozenset()))


@pytest.mark.parametrize("mode", ["", "local", "cloud", "LOCAL-ONLY", None])
def test_fail__an_undeclared_or_bogus_mode_is_refused(mode: object) -> None:
    # Rule 6: a module that does not say what it is cannot be reasoned about.
    with pytest.raises(FeatureError):
        Feature(name="x", mode=mode, core="test", unauth=frozenset(), build=(lambda **_: None))


def test_fail__a_missing_core_dependency_is_refused() -> None:
    with pytest.raises(FeatureError):
        Feature(name="x", mode="both", core="", unauth=frozenset(), build=(lambda **_: None))


def test_ok__declared_unauth_sums_the_enabled_features() -> None:
    features.register(_feature("quiet", _Quiet, frozenset()))
    features.register(_feature("loud", _Loud, frozenset({("GET", "/loud/challenge")})))
    assert features.declared_unauth(["quiet"]) == set()
    assert features.declared_unauth(["quiet", "loud"]) == {("GET", "/loud/challenge")}


# ===== the real registration in server.py =====
def test_ok__the_switch_feature_is_registered_and_declares_nothing_pre_auth() -> None:
    import kvmd.apps.kvmd.server  # noqa: F401  pylint: disable=unused-import
    switch = features.get("switch")
    assert switch.mode in features.MODES
    assert switch.core
    assert switch.unauth == frozenset(), \
        "SwitchApi must not add pre-auth routes; if it now does, that is a security change"
