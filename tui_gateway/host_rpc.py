"""Advertise and validate this host's actual registered operations."""
from pydantic import ValidationError

from protocol.rpc.host import HostNegotiateRequest
from protocol.version import MIN_SUPPORTED, PROTOCOL_VERSION


def descriptor(server) -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "min_protocol_version": MIN_SUPPORTED,
        "capabilities": sorted(server._methods),
    }


def register(server) -> None:
    @server.rpc_validated("host.negotiate")
    def negotiate(rid, params):
        try:
            request = HostNegotiateRequest.model_validate(params)
        except ValidationError as exc:
            return server._err(rid, -32602, str(exc))
        offered = descriptor(server)
        if not MIN_SUPPORTED <= request.protocol_version <= PROTOCOL_VERSION:
            return server._err(rid, 4004, f"Incompatible protocol: client {request.protocol_version}; host supports {MIN_SUPPORTED}..{PROTOCOL_VERSION}. Install compatible client and backend versions.")
        missing = sorted(set(request.required_capabilities) - set(offered["capabilities"]))
        if missing:
            return server._err(rid, 4004, "Backend is missing required capabilities: " + ", ".join(missing))
        return server._ok(rid, offered)
