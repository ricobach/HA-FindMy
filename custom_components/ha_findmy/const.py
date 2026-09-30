"""Constants for HA-FindMy."""

from datetime import timedelta

DOMAIN = "ha_findmy"
PLATFORMS = ["device_tracker"]
UPDATE_INTERVAL = timedelta(minutes=15)

CONF_ACCOUNT = "account"
CONF_ACCESSORIES = "accessories"
