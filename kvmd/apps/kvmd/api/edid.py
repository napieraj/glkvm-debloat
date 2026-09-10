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

"""EDID management for the capture chip.

Split out of api/upgrade.py by docs/lean-plan.md step 9. These three routes
were never about firmware: they write an EDID blob to the HDMI receiver so the
attached host advertises the modes we want. They shared a module with the
vendor's update client only because both ran x_upgrade-style commands.
"""


import asyncio
import os
import re

from aiohttp.web import Request, Response

from ....htserver import (
    BadRequestError,
    exposed_http,
    make_json_response,
    make_json_exception,
)
from ....logging import get_logger
from ....utils import get_model_name


EDID_FILE = "/tmp/edid.bin"
EDID_USER_FILE = "/etc/kvmd/user/edid.txt"  # 用于保存当前写入的EDID
EDID_LIST_FILE = "/etc/kvmd/edid.json"

LT6911C_UPGRADE_CMD = "lt6911c_upgrade -d /dev/i2c-1 -e /tmp/edid.bin && sleep 1 && echo 1 >  /sys/bus/i2c/devices/1-002b/reset"
GSV1127X_UPGRADE_CMD = (
    "echo 0 > /sys/bus/i2c/devices/1-0058/poll_interval_enable && sleep 1 "
    "&& gsv1127x_upgrade -d /dev/i2c-1 -e /tmp/edid.bin && sleep 1 "
    "&& echo 1 > /sys/bus/i2c/devices/1-0058/poll_interval_enable"
)
GSV1127_UPGRADE_CMD = (
    "echo 0 > /sys/bus/i2c/devices/0-0058/enable_stream && sleep 0.5 "
    "&& gsv1127x_upgrade -d /dev/i2c-0 -e /tmp/edid.bin && sleep 0.5 "
    "&& echo 1 > /sys/bus/i2c/devices/0-0058/enable_stream"
)

# 每个型号的 HDMI 接收芯片不同，写 EDID 的命令也不同；未列出的型号走 LT6911C。
_CMD_MAP = {
    "rm10rc": GSV1127X_UPGRADE_CMD,
    "rm4pe": GSV1127X_UPGRADE_CMD,
    "rmq1": GSV1127_UPGRADE_CMD,
}


class EdidApi:
    def __init__(self) -> None:
        # kvmd.utils.get_model_name() rather than a fourth copy of MODEL_PATH.
        # Its fallback is "rm10" where upgrade.py's was "rm1"; neither is a key
        # of _CMD_MAP, so both fall through to LT6911C exactly as before.
        self.__model = get_model_name()

    def __validate_edid(self, edid_str: str) -> bool:
        # 移除所有空白字符
        edid_str = "".join(edid_str.split())

        # 检查长度（标准EDID是128字节或256字节，每个字节由2个十六进制字符表示）
        if len(edid_str) not in [256, 512]:
            return False

        # 检查是否都是有效的十六进制字符
        if not re.match(r"^[0-9A-Fa-f]+$", edid_str):
            return False

        return True

    def __convert_edid_to_bytes(self, edid_str: str) -> bytes:
        # 移除所有空白字符
        edid_str = "".join(edid_str.split())

        # 如果EDID只有128字节(256个十六进制字符)，则追加指定的128字节
        if len(edid_str) == 256:
            # 追加的128字节数据
            additional_bytes = (
                "02 03 12 F0 23 09 04 01 83 01 00 00 65 03 0C 00 "
                "10 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
                "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
                "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
                "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
                "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
                "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
                "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 C0"
            )
            # 移除空格
            additional_bytes = "".join(additional_bytes.split())
            # 合并原始EDID和追加的数据
            edid_str = edid_str + additional_bytes
            get_logger(0).info("EDID is only 128 bytes, automatically appending additional 128 bytes")

        # 将十六进制字符串转换为字节
        return bytes.fromhex(edid_str)

    @exposed_http("POST", "/upgrade/edid")
    async def __edid_handler(self, request: Request) -> Response:
        try:
            # 读取请求体中的edid参数
            data = await request.post()
            edid_str = data.get("edid", "")

            # 验证EDID数据
            if not self.__validate_edid(edid_str):
                raise BadRequestError("Invalid EDID format")

            # 转换为字节数据
            edid_bytes = self.__convert_edid_to_bytes(edid_str)

            # 写入临时文件
            with open(EDID_FILE, "wb") as f:
                f.write(edid_bytes)

            # 保存原始edid字符串到用户配置文件
            os.makedirs(os.path.dirname(EDID_USER_FILE), exist_ok=True)
            with open(EDID_USER_FILE, "w") as f:
                f.write(edid_str)
            await asyncio.create_subprocess_shell("sync")

            edid_cmd = _CMD_MAP.get(self.__model, LT6911C_UPGRADE_CMD)

            # 执行x_upgrade命令
            proc = await asyncio.create_subprocess_shell(
                edid_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            (_, stderr) = await proc.communicate()

            if proc.returncode != 0:
                raise BadRequestError(f"Failed to execute x_upgrade: {stderr.decode()}")

            return make_json_response({
                "status": "success",
                "message": "EDID data has been written and applied"
            })

        except BadRequestError as ex:
            return make_json_exception(ex, 400)
        except Exception as ex:
            return make_json_exception(str(ex), 500)

    @exposed_http("GET", "/upgrade/get_edid")
    async def __get_edid_handler(self, request: Request) -> Response:
        try:
            if not os.path.exists(EDID_USER_FILE):
                # 如果文件不存在，返回空字符串
                return make_json_response({"edid": ""})

            # 读取保存的EDID数据
            with open(EDID_USER_FILE, "r") as f:
                edid_str = f.read().strip()

            return make_json_response({"edid": edid_str})

        except Exception as ex:
            get_logger(0).error(f"Error getting EDID data: {str(ex)}")
            return make_json_exception(str(ex), 500)

    @exposed_http("GET", "/upgrade/edid_list")
    async def __get_edid_list_handler(self, _: Request) -> Response:
        try:
            with open(EDID_LIST_FILE, "r", encoding="utf-8") as f:
                data = f.read()
        except FileNotFoundError:
            get_logger(0).warning("edid.json not found at %s", EDID_LIST_FILE)
            data = "[]"
        except Exception as ex:
            get_logger(0).error(f"Error reading edid.json: {ex}")
            data = "[]"
        return Response(text=data, content_type="application/json")
