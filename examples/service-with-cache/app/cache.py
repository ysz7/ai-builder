"""A very small Redis client, spoken over a socket.

Deliberately dependency-free: the point of this example is the *service*, not the driver.
It carries no node -- nothing in this file is decorated, so the graph does not show it, and
no function in it needs classifying. A node for the cache itself is P12's job.
"""

import socket

from app.settings import settings


def _encode(*parts: str) -> bytes:
    """RESP: an array of bulk strings. Twenty lines beats a dependency here."""
    out = [f"*{len(parts)}\r\n".encode()]
    for part in parts:
        raw = part.encode()
        out.append(b"$%d\r\n%s\r\n" % (len(raw), raw))
    return b"".join(out)


def command(*parts: str) -> str:
    """Send one command and read one line back. Raises if the service is not there."""
    with socket.create_connection(
        (settings.cache_host, settings.cache_port), timeout=settings.connect_timeout_s
    ) as connection:
        connection.sendall(_encode(*parts))
        answer = connection.makefile("rb").readline().decode().strip()

    if answer.startswith("-"):
        raise RuntimeError(answer[1:])
    return answer[1:]
