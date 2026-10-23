"""The ``[device]`` configuration section, parsed once at the boundary.

``defaultconfig.d/50-device.toml`` documents every key. Command-line flags override the
section; :func:`resolve_endpoint` is where the two meet, so every command resolves its device
the same way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator

from ...domain.endpoint import DeviceEndpoint
from ...domain.errors import ConfigurationError

if TYPE_CHECKING:
    from lib_layered_config import Config

_SECTION = "device"


class DeviceSettings(BaseModel, frozen=True, extra="forbid"):
    """The ``[device]`` section."""

    host: str = ""
    login: str = ""
    password: SecretStr = SecretStr("")
    timeout: float = Field(default=10.0, gt=0, le=600)
    raw_port_base: int = Field(default=9100, ge=1, le=65535)

    @field_validator("host", "login", "password", mode="before")
    @classmethod
    def _numbers_are_text(cls, value: object) -> object:
        # The configuration layer turns an unquoted 1234 into a number; a password or
        # login made of digits is still text.
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        return value


def load_device_settings(config: Config) -> DeviceSettings:
    """Parse the ``[device]`` section of ``config``.

    Raises:
        ConfigurationError: A key is unknown or a value is invalid; one line per problem,
            never the password's value.
    """
    raw: object = config.get(_SECTION, default={})
    try:
        return DeviceSettings.model_validate(cast("dict[str, object]", raw) if raw else {})
    except ValidationError as exc:
        problems = "; ".join(f"{_SECTION}.{'.'.join(map(str, error['loc']))}: {error['msg']}" for error in exc.errors())
        raise ConfigurationError(f"invalid device settings: {problems}") from exc


def resolve_endpoint(settings: DeviceSettings, *, host: str | None, timeout: float | None) -> DeviceEndpoint:
    """Combine the settings with the command line's ``--host`` and ``--timeout``.

    Raises:
        ConfigurationError: No host is configured or given.

    Example:
        >>> resolve_endpoint(DeviceSettings(host="192.0.2.52"), host=None, timeout=2.5).timeout
        2.5
    """
    chosen_host = (host or settings.host).strip()
    if not chosen_host:
        raise ConfigurationError("no device given: pass --host or set [device] host in the configuration")
    return DeviceEndpoint(
        host=chosen_host,
        login=settings.login,
        password=settings.password,
        timeout=settings.timeout if timeout is None else timeout,
    )


__all__ = ["DeviceSettings", "load_device_settings", "resolve_endpoint"]
