# Changelog

All notable changes to HA-FindMy are documented here.

## [0.4.2] - 2026-09-30

### Fixed
- Accessory management now performs an explicit Apple reauthentication when opening iCloud Keychain.
- Reuses the saved Anisette/device identity instead of creating a new Apple client identity.
- Handles Apple two-factor authentication inside the Configure flow.
- Apple ID passwords remain in memory only for the management operation and are scrubbed before config-entry persistence.

## [0.4.1] - 2026-09-30

### Fixed
- Fixed Home Assistant options-flow startup when opening Configure.

## [0.4.0] - 2026-09-30

### Added
- Manage selected Find My accessories after initial setup.
- Rediscover, add and remove accessories without deleting the integration.

## [0.3.4] - 2026-09-30

### Added
- Find My report-age and Apple polling diagnostics.
- Local BLE/key diagnostics, including accessory grouping metadata.

## [0.3.3] - 2026-09-30

### Added
- Combined Current location sensor using Bermuda area/proxy and GPS-zone fallback.

## [0.3.2] - 2026-09-30

### Added
- GPS accuracy sensor.

## [0.3.1] - 2026-09-30

### Changed
- Simplified battery entities while retaining approximate battery percentage.

## [0.3.0] - 2026-09-30

### Added
- Bermuda BLE Trilateration bridge for stable Find My accessory identities.

## [0.2.0] - 2026-09-30

### Added
- Local Bluetooth tracking through Home Assistant Bluetooth and ESPHome proxies.
- Battery, presence and RSSI entities.

## [0.1.0] - 2026-09-30

### Added
- Initial Apple sign-in, 2FA, iCloud Keychain recovery, accessory selection and Find My GPS tracking.
