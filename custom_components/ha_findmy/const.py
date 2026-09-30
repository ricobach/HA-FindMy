"""Constants for HA-FindMy."""

from datetime import timedelta

DOMAIN = "ha_findmy"
PLATFORMS = ["device_tracker", "sensor", "binary_sensor"]
UPDATE_INTERVAL = timedelta(minutes=15)

CONF_ACCOUNT = "account"
CONF_ACCESSORIES = "accessories"

DEFAULT_AWAY_TIMEOUT_MINUTES = 10


def signal_local_observation(unique_id: str) -> str:
    """Dispatcher signal fired when an accessory is matched locally."""
    return f"{DOMAIN}_local_observation_{unique_id}"


def signal_local_rssi(unique_id: str) -> str:
    """Dispatcher signal fired when local signal strength changes."""
    return f"{DOMAIN}_local_rssi_{unique_id}"
