# HA-FindMy

A Home Assistant custom integration for Apple Find My accessories.

This project intentionally starts small: authenticate to Apple with **local Anisette**, recover
Find My accessory keys directly from iCloud Keychain, select accessories, and expose them as
Home Assistant GPS device trackers.

## Current status

Early development / proof of concept.

Implemented in the first slice:

- Local Anisette only — no external Anisette server setting.
- Apple ID + password sign-in.
- Trusted-device or SMS 2FA.
- Read-only iCloud Keychain recovery using a trusted device's screen-lock passcode.
- Accessory discovery directly from iCloud.
- Accessory selection during setup.
- Remote Find My location polling every 15 minutes.
- One Home Assistant `device_tracker` entity per selected accessory.
- The Apple ID password and device passcode are **not stored** by this integration.

Not implemented yet:

- Re-authentication flow when Apple expires a session.
- Adding/removing accessories after initial setup without re-running setup.
- Local Bluetooth / ESPHome proxy tracking.
- Persisting recovered keychain keys to avoid the passcode on a future discovery run.
- Sensors for battery, diagnostics and local presence.

## Dependency strategy

For now this integration uses the FindMy.py fork used by OpenTagViewer because the iCloud
Keychain / CloudKit accessory discovery API has not yet landed in the released upstream package.

Pinned source:

- https://github.com/parawanderer/FindMy.py
- commit `7969003ca785658369b650f75d9e7ca519566bf6`

The integration is intentionally written against FindMy.py's public `FindMyAccessory` and
`AsyncAppleAccount` interfaces so moving back to upstream FindMy.py should be small once the
iCloud import work is released.

## Installation

This repository is structured for HACS as a custom integration.

1. Add this repository as a custom repository in HACS.
2. Install **HA-FindMy**.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration → HA-FindMy**.

## Security notes

The selected accessory JSON contains private Find My key material. Home Assistant config-entry
storage is not designed as a hardware-backed secret vault, so protect your Home Assistant
configuration and backups accordingly.

The device screen-lock passcode is used only for the iCloud Keychain recovery call and is not
written to the config entry. The Apple ID password is also removed from the account state before
the config entry is saved.

## Credits

The Apple protocol work is provided by FindMy.py and the iCloud accessory extraction work in the
parawanderer FindMy.py fork / OpenTagViewer ecosystem.

This project is not affiliated with or endorsed by Apple.
