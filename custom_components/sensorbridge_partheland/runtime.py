"""Laufzeitdaten eines SensorBridge-Config-Entries."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .config_service import ConfigService
from .coordinator import SensorBridgeCoordinator


@dataclass(slots=True)
class SensorBridgeRuntimeData:
    """Bündelt alle Laufzeitobjekte eines Config-Entries."""

    config_service: ConfigService
    coordinator: SensorBridgeCoordinator
    supplemental_coordinators: dict[str, Any]
    pending_supplemental_shutdowns: dict[str, Any] = field(
        default_factory=dict
    )
    pending_supplemental_cleanup_task: asyncio.Task[Any] | None = field(
        default=None,
        repr=False,
    )
    platforms_unloaded: bool = False
    pending_platforms: set[str] = field(default_factory=set)
    coordinator_shutdown: bool = False
    shutdown_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        repr=False,
    )


SensorBridgeConfigEntry = ConfigEntry[SensorBridgeRuntimeData]
