"""memkit-adapter-dds — connects DDS buses to memkit Memory."""

from .adapter import AdapterConfig, AnomalyRule, DDSAdapter
from .bus import DDSBus, SubscriberCallback
from .fake_bus import FakeDDSBus, ThreadedFakeDDSBus
from .mapping import FieldMapping, TopicMapping

__version__ = "0.1.0"

__all__ = [
    # Core
    "DDSAdapter",
    "AdapterConfig",
    "AnomalyRule",
    # Bus
    "DDSBus",
    "SubscriberCallback",
    "FakeDDSBus",
    "ThreadedFakeDDSBus",
    # Mapping
    "TopicMapping",
    "FieldMapping",
]
