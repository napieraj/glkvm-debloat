InotifyMask.ACCESS
InotifyMask.ATTRIB
InotifyMask.CLOSE_WRITE
InotifyMask.CLOSE_NOWRITE
InotifyMask.CREATE
InotifyMask.DELETE
InotifyMask.DELETE_SELF
InotifyMask.MODIFY
InotifyMask.MOVE_SELF
InotifyMask.MOVED_FROM
InotifyMask.MOVED_TO
InotifyMask.OPEN

InotifyMask.IGNORED
InotifyMask.ISDIR
InotifyMask.Q_OVERFLOW
InotifyMask.UNMOUNT

IpmiServer.handle_raw_request

SpiDev.no_cs
SpiDev.cshigh
SpiDev.max_speed_hz

_DriveImage.complete

_AtxApiPart.switch_power

_UsbKey.arduino_modifier_code

_KeyMapping.web_name
_KeyMapping.mcu_code
_KeyMapping.usb_key
_KeyMapping.ps2_key
_KeyMapping.at1_code
_KeyMapping.x11_keys

_SharedParams.width
_SharedParams.height

_Netcfg.net_ip
_Netcfg.net_mask
_Netcfg.dhcp_option_3

_ScriptWriter.get_args

_pwm.period_ns

_Edid.set_mfc_id
_Edid.set_product_id
_Edid.set_serial
_Edid.set_monitor_name
_Edid.set_monitor_serial
_Edid.set_audio

Dumper.ignore_aliases

_auth_server_port_fixture
_test_user

# Plugin foundation: refusal codes for behaviour that lands with the device
# half (placement, loading, runtime-tier policy) and for the server-side
# unsolicited-fetch case. They are defined because contract/plugins/errors.md
# defines them, and tests/pluginmgr/test_errors.py fails if the two ever
# disagree -- so these are contract surface, not dead names.
CODE_WIRE_UNSOLICITED
CODE_POLICY_ROLLBACK_REFUSED
CODE_POLICY_WRONG_RUNTIME
CODE_POLICY_INCOMPATIBLE_MODEL
CODE_POLICY_INCOMPATIBLE_FIRMWARE
CODE_INSTALL_LOAD_FAILED
CODE_INSTALL_PLACE_FAILED
CODE_INSTALL_READBACK_MISMATCH
