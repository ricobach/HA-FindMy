"""Runtime objects for HA-FindMy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from findmy import AsyncAppleAccount, FindMyAccessory

from .coordinator import HAFindMyCoordinator

if TYPE_CHECKING:
    from .local_bluetooth import LocalObservation


@dataclass(slots=True)
class HAFindMyRuntime:
    """Runtime state for one config entry."""

    account: AsyncAppleAccount
    accessories: list[FindMyAccessory]
    coordinator: HAFindMyCoordinator
    local_observations: dict[str, tuple[LocalObservation, str | None]] = field(default_factory=dict)
    local_status: dict[str, tuple[int, datetime]] = field(default_factory=dict)
    local_rssi: dict[str, int | None] = field(default_factory=dict)
