"""Per-installation role and hub connection settings.

This configuration deliberately lives outside SQLite.  A client keeps its local
database untouched while it uses another installation's HTTP server as its hub.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from runtime import runtime


CONFIG_VERSION = 1
HUB_PROTOCOL_VERSION = 1


def normalize_hub_url(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise ValueError("Enter the hub's address.")
    if "://" not in candidate:
        candidate = f"http://{candidate}"

    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("The hub address must use http:// or https://.")
    if not parsed.hostname or any(character.isspace() for character in parsed.hostname):
        raise ValueError("Enter a valid hub hostname or IP address.")
    if parsed.username or parsed.password:
        raise ValueError("The hub address cannot contain a username or password.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Enter the hub's base address without a page path.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Enter a valid port number.") from exc

    host = parsed.hostname.lower()
    formatted_host = f"[{host}]" if ":" in host else host
    netloc = f"{formatted_host}:{port}" if port is not None else formatted_host
    return urlunsplit((parsed.scheme.lower(), netloc, "", "", ""))


class InstanceConfig:
    def __init__(self, path: Path | None = None):
        self.path = path or runtime.data_dir / "instance-config.json"

    def _read(self) -> dict:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @property
    def hub_url(self) -> str | None:
        value = self._read().get("hub_url")
        if not isinstance(value, str):
            return None
        try:
            return normalize_hub_url(value)
        except ValueError:
            return None

    @property
    def role(self) -> str:
        return "client" if self.hub_url else "hub"

    def instance_id(self) -> str:
        payload = self._read()
        value = payload.get("instance_id")
        if isinstance(value, str) and value.strip():
            return value
        value = str(uuid.uuid4())
        payload.update({"version": CONFIG_VERSION, "instance_id": value})
        self._write(payload)
        return value

    def connect(self, hub_url: str) -> str:
        normalized = normalize_hub_url(hub_url)
        payload = self._read()
        payload.update(
            {
                "version": CONFIG_VERSION,
                "instance_id": payload.get("instance_id") or str(uuid.uuid4()),
                "hub_url": normalized,
            }
        )
        self._write(payload)
        return normalized

    def disconnect(self) -> None:
        payload = self._read()
        payload.pop("hub_url", None)
        payload.update(
            {
                "version": CONFIG_VERSION,
                "instance_id": payload.get("instance_id") or str(uuid.uuid4()),
            }
        )
        self._write(payload)


instance_config = InstanceConfig()
