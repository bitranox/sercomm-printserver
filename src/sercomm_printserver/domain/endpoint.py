"""Where and how to reach one print server, and what a print job carries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BaseModel, Field, GetPydanticSchema, SecretStr

from .print_data import PrintData

if TYPE_CHECKING:
    from pydantic import GetCoreSchemaHandler
    from pydantic_core import CoreSchema

Port = Annotated[int, Field(ge=1, le=65535)]
_JobName = Annotated[str, Field(min_length=1, max_length=99, pattern=r"^[\x21-\x7e]+$")]
_LpdName = Annotated[str, Field(min_length=1, max_length=31, pattern=r"^[\x21-\x7e]+$")]


def _print_data_schema(_source: Any, handler: GetCoreSchemaHandler) -> CoreSchema:
    """A ``PrintData`` passes unchanged; anything pydantic reads as ``bytes`` is wrapped in one.

    Built here rather than on ``PrintData`` itself, so the domain module that defines it stays
    free of pydantic. Written as the schema's plain mapping form, because the ``core_schema``
    builders live in ``pydantic_core``, which this package reaches only through pydantic.
    """
    return {
        "type": "union",
        "choices": [
            {"type": "is-instance", "cls": PrintData},
            {
                "type": "function-after",
                "function": {"type": "no-info", "function": PrintData.of},
                "schema": handler(bytes),
            },
        ],
    }


_JobData = Annotated[PrintData, GetPydanticSchema(_print_data_schema)]


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
    so only the identifying fields are carried. ``data`` is a :class:`PrintData`; plain bytes are
    wrapped in one, so a job read from a file or stdin can be streamed instead of held in memory.

    Example:
        >>> job = PrintJob(data=b"hello\\r\\n\\f", name="greeting")
        >>> job.data
        PrintData.of(<8 bytes>)
        >>> job.data == b"hello\\r\\n\\f"
        True
    """

    data: _JobData
    name: _JobName = "job"
    user: _LpdName = "sercomm"
    client_host: _LpdName = "localhost"

    def __init__(
        self,
        *,
        data: PrintData | bytes,
        name: str = "job",
        user: str = "sercomm",
        client_host: str = "localhost",
    ) -> None:
        """Spelled out so a type checker accepts ``bytes`` for ``data``; validation wraps them."""
        super().__init__(data=data, name=name, user=user, client_host=client_host)


__all__ = ["DeviceEndpoint", "Port", "PrintJob"]
