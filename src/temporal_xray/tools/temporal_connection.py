from __future__ import annotations

from typing import Any

from ..temporal_client import (
    TemporalConfig,
    connect_to_server,
    get_connection_status,
)
from ..types import TemporalConnectionInput


async def temporal_connection(input: TemporalConnectionInput) -> dict[str, Any]:
    if input.action == "connect":
        if not input.address and not input.namespace:
            raise RuntimeError(
                "Provide at least an address or namespace to connect. "
                "Example: { action: 'connect', address: 'localhost:7233', namespace: 'default' }"
            )

        current = get_connection_status()
        config = TemporalConfig(
            address=input.address or current["address"],
            namespace=input.namespace or current["namespace"],
            tls_cert_path=input.tls_cert_path,
            tls_key_path=input.tls_key_path,
            api_key=input.api_key,
        )

        status = await connect_to_server(config)
        return {**status, "connected": True}

    return get_connection_status()
