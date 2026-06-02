"""System coordination — unified lifecycle for Car, PC, and App agents.

The SystemCoordinator owns all three agents with proper dependency
ordering (Car → PC → App), background health monitoring, and
graceful reverse-order shutdown.
"""

from coordinator.system_coordinator import (
    AgentStatus,
    RuntimeEndpoint,
    SharedRuntimeState,
    SystemCoordinator,
    resolve_endpoint,
)
