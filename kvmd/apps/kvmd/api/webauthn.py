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


from aiohttp.web import Request
from aiohttp.web import Response

from ....logging import get_logger

from ....htserver import ForbiddenError
from ....htserver import UnauthorizedError
from ....htserver import exposed_http
from ....htserver import make_json_response
from ....htserver import set_request_auth_info
from ....htserver import is_request_secure

from ....validators.auth import valid_expire

from ....plugins.auth.webauthn import Plugin as WebAuthnPlugin
from ....plugins.auth.webauthn import WebAuthnError

from ..auth import AuthManager

# Imported rather than re-declared. A second "auth_token" literal in this file
# would drift silently the day the other one changes: the browser would keep
# sending the old cookie name, every request would look unauthenticated, and
# nothing would log an error. One definition, one name.
from .auth import _COOKIE_AUTH_TOKEN


# =====
class WebAuthnApi:
    def __init__(self, auth_manager: AuthManager, service: WebAuthnPlugin) -> None:
        self.__auth_manager = auth_manager
        self.__service = service

    # =====
    # Both routes are auth_required=False by necessity: they are how a caller
    # WITH no session obtains one. They are not usc-reachable and carry no
    # allowed_exe_paths -- _check_exe_path is exclusive (api/auth.py), so an
    # exe-path would make them unreachable from any browser.

    @exposed_http("GET", "/auth/webauthn/challenge", auth_required=False, allow_usc=False)
    async def __challenge_handler(self, _: Request) -> Response:
        if not self.__service.is_configured():
            raise UnauthorizedError("WebAuthn is not configured")
        return make_json_response(self.__service.make_challenge(), wrap_result=False)

    @exposed_http("POST", "/auth/webauthn/assert", auth_required=False, allow_usc=False)
    async def __assert_handler(self, req: Request) -> Response:
        if not self.__service.is_configured():
            raise UnauthorizedError("WebAuthn is not configured")

        data = await req.json()
        expire = valid_expire(data.get("expire", "0"))

        try:
            # rawId, not id: the plugin matches on the raw credential bytes.
            (user, purpose) = await self.__service.verify_assertion(
                credential_id=str(data.get("rawId", "")),
                client_data_json=str(data.get("clientDataJSON", "")),
                authenticator_data=str(data.get("authenticatorData", "")),
                signature=str(data.get("signature", "")),
            )
            if purpose != "login":
                # A challenge minted for something else must not be spendable
                # as a login. The challenge is already single-use, so this is
                # the second half of that: right ceremony, wrong purpose.
                raise WebAuthnError(f"Challenge purpose {purpose!r} is not 'login'")
        except WebAuthnError as ex:
            # Deliberately opaque to the caller and specific in the log: an
            # attacker probing origins or replaying a challenge learns nothing
            # from the response, the operator learns everything from the log.
            get_logger(0).error("WebAuthn assertion rejected: %s", ex)
            set_request_auth_info(req, "- (webauthn)")
            raise ForbiddenError()

        (token, failed_since_last_success) = self.__auth_manager.login_verified(user, expire)
        set_request_auth_info(req, f"{user} (webauthn)", token)
        get_logger(0).info("Logged in user %r via WebAuthn", user)
        return make_json_response({
            "token": token,
            "failed_since_last_success": failed_since_last_success,
        }, set_cookies={_COOKIE_AUTH_TOKEN: token}, secure_cookies=is_request_secure(req))
