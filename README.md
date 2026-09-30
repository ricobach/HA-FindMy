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
- Accessory management after setup from **Settings → Devices & services → HA-FindMy → Configure**; rediscover, add or remove accessories without deleting the integration or entering the Apple ID/password again.
- Remote Find My location polling every 15 minutes.
- One Home Assistant `device_tracker` entity per selected accessory.
- Latitude, longitude, GPS accuracy and last Find My report timestamp sensors.
- Diagnostic `Find My report age` sensor showing report age plus the last successful Apple poll, report timestamp and confidence.
- Diagnostic `Local BLE diagnostic` sensor showing whether rolling keys are available and whether the accessory has actually been matched locally; includes AirPods grouping metadata when Apple provides it.
- A combined `Current location` sensor that prefers Bermuda Area, then nearest proxy, then a Home Assistant GPS zone, with Away/Unknown as fallback.
- AirTag battery sensor shown as an approximate percentage derived from Apple's four battery bands.
- Local Bluetooth matching using Home Assistant Bluetooth adapters and ESPHome Bluetooth proxies.
- Bluetooth presence and RSSI entities, including the proxy/source that most recently saw the tag.
- Optional Bermuda BLE Trilateration bridge: selected AirTags are registered as stable Bermuda devices and rotating BLE addresses are attached automatically.
- The Apple ID password and device passcode are **not stored** by this integration.

Not implemented yet:

- Re-authentication flow when Apple expires a session.
- Persisting recovered keychain keys to avoid the passcode on a future discovery run.
- Model-specific AirPods behaviour is still being validated; the generic Find My accessory and BLE diagnostics are intended to show whether a given case/bud can use the existing Bermuda path.

## Managing accessories after setup

Open **Settings → Devices & services → HA-FindMy → Configure** to refresh the iCloud accessory list and change the selected devices. Because HA-FindMy intentionally does not persist recovered iCloud Keychain keys, Home Assistant will ask you to choose a trusted Apple device and enter its screen-lock passcode for each rediscovery. The passcode is not stored.

Currently selected accessories stay preselected. Explicitly deselecting an accessory removes its HA-FindMy entities and device registry entry after the integration reloads. Newly selected accessories are created automatically.

## Bermuda BLE Trilateration integration

If [Bermuda BLE Trilateration](https://github.com/agittins/bermuda) is installed and loaded,
HA-FindMy automatically creates a stable Bermuda metadevice for each selected Find My accessory.
Whenever HA-FindMy resolves a rotating AirTag Bluetooth address, it attaches that address to the
stable Bermuda device.

Bermuda then uses its own observations from all Home Assistant Bluetooth adapters and ESPHome
Bluetooth proxies for RSSI smoothing, distance calculation, area selection and its local
`device_tracker`. HA-FindMy also reads Bermuda Area, nearest scanner, distance and RSSI for the combined `Current location` sensor while leaving Bermuda's original entities intact for automations.

Bermuda currently has no public external-resolver API, so this bridge is a guarded compatibility
shim over Bermuda's existing metadevice model. If Bermuda changes that internal interface,
HA-FindMy will log a warning and continue operating normally; Find My GPS and local Bluetooth
tracking are not dependent on Bermuda.

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
