"""
DDS bus abstraction.

memkit-adapter-dds does not import Cyclone DDS, rti DDS, or any specific
implementation. Instead, it defines a narrow Protocol that real DDS bindings
can satisfy, and ships a FakeDDSBus for testing.

In production, you wire in the real binding:

    from memkit_adapter_dds.backends.cyclone import CycloneDDSBus
    bus = CycloneDDSBus(domain_id=0)
    adapter = DDSAdapter(memory, bus, config=...)

For the Unitree G1 specifically, you'd pass domain_id=0 and subscribe to
the standard LowState_ / SportModeState_ topics.
"""
from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable


# A subscriber callback receives the deserialized message payload as a dict.
# Keeping this as a plain dict (not a typed struct) is intentional — it
# matches how both IDL-generated Python bindings and handwritten MCAP
# replays look, and makes the mapping layer straightforward.
SubscriberCallback = Callable[[dict[str, Any]], None]


@runtime_checkable
class DDSBus(Protocol):
    """The narrow surface memkit-adapter-dds needs from any DDS binding."""

    def subscribe(self, topic: str, callback: SubscriberCallback) -> None:
        """Register a callback for a topic. Callback runs on the DDS thread.

        The adapter guarantees its own callback is cheap (only touches reflex,
        never blocks). Nested subscribers are the caller's responsibility.
        """
        ...

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Publish a message to a topic. Expected to be non-blocking."""
        ...

    def unsubscribe(self, topic: str) -> None:
        """Remove all subscribers for a topic."""
        ...

    def close(self) -> None:
        """Tear down the bus."""
        ...
