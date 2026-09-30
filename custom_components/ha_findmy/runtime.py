"""Runtime objects for HA-FindMy."""

from __future__ import annotations

from dataclasses import dataclass

from findmy import AsyncAppleAccount, FindMyAccessory

from .coordinator import HAFindMyCoordinator


@dataclass(slots=True)
class HAFindMyRuntime:
    """Runtime state for one config entry."""

    account: AsyncAppleAccount
    accessories: list[FindMyAccessory]
    coordinator: HAFindMyCoordinator
