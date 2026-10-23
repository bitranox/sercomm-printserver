"""Where and how to reach one print server, and what a print job carries."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, SecretStr

Port = Annotated[int, Field(ge=1, le=65535)]


class DeviceEndpoint(BaseModel, frozen=True, extra="forbid"):
    """Address, credentials and timeouts for one print server.

    The FTP login is the device name (BOX_NAME, or the default name ``SCxxxxxx``) with the
    password, empty by factory default. An empty ``login`` means "do not log in"; this family
    serves ``CONFIG`` and ``PSINF`` without a login.

    Example:
        >>> endpoint = DeviceEndpoint(host="192.0.2.52")
        >>> endpoint.ftp_port, endpoint.password.get_secret_value()
        (21, '')
    """

    host: str = Field(min_length=1)
    login: str = ""
    password: SecretStr = SecretStr("")
    timeout: float = Field(default=10.0, gt=0, le=600)
    ftp_port: Port = 21
    telnet_port: Port = 23
    tftp_port: Port = 69
    lpd_port: Port = 515


class PrintJob(BaseModel, frozen=True, extra="forbid"):
    """Print data plus the names LPD puts into the job's control file.

    The device prints the data as it arrives and ignores control-file options (vendor manual),
    so only the identifying fields are carried.
    """

    data: bytes
    name: str = Field(default="job", min_length=1, max_length=99, pattern=r"^[\x21-\x7e]+$")
    user: str = Field(default="sercomm", min_length=1, max_length=31, pattern=r"^[\x21-\x7e]+$")
    client_host: str = Field(default="localhost", min_length=1, max_length=31, pattern=r"^[\x21-\x7e]+$")


__all__ = ["DeviceEndpoint", "Port", "PrintJob"]
