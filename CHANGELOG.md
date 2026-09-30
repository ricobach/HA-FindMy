# Changelog

All notable changes to HA-FindMy are documented here.

## [0.4.2] - 2026-09-30

- Added standard HACS and hassfest GitHub Actions.
- Moved local integration branding into Home Assistant's supported `brand/` directory.
- Added release automation, Dependabot configuration, issue templates, licensing and attribution files.
- Added repository validation badges and development documentation.

## [0.4.1] - 2026-09-30

- Fixed Home Assistant options-flow startup for post-setup accessory management.

## [0.4.0] - 2026-09-30

- Added post-setup accessory discovery, selection and removal through Configure.
- Added cleanup for entities and device-registry entries when accessories are removed.

## [0.3.4] - 2026-09-30

- Added Find My report freshness diagnostics.
- Added local BLE/key diagnostics, including AirPods grouping metadata.

## [0.3.3] - 2026-09-30

- Added the combined Current location sensor using Bermuda area, nearest scanner, GPS zone and fallback state.

## [0.3.2] - 2026-09-30

- Added GPS accuracy sensor.

## [0.3.1] - 2026-09-30

- Simplified battery entities to retain the approximate percentage sensor only.

## [0.3.0] - 2026-09-30

- Added local Bluetooth matching through Home Assistant adapters and ESPHome proxies.
- Added optional Bermuda BLE Trilateration bridge.

## [0.1.0] - 2026-09-30

- Initial HA-FindMy custom integration with local Anisette, Apple authentication, iCloud Keychain accessory recovery and Find My GPS tracking.
