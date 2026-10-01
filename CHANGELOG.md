# Changelog

All notable changes to HA-FindMy are documented here.

## [0.4.7] - 2026-10-01

### Fixed
- Reverted concurrent Find My report requests because Apple's report service may throttle or stall parallel requests from one account.
- Accessories are now refreshed sequentially in the background with a generous 180-second per-accessory safety timeout.
- Successful accessory results are published immediately instead of waiting for the whole accessory set to finish.
- Slow or failed accessories retain their previous good report while other accessories continue updating.

## [0.4.6] - 2026-10-01

### Fixed
- Apple Find My polling now fetches rolling-key accessories with bounded concurrency instead of relying on FindMy.py's sequential multi-accessory loop.
- Each accessory has its own 45-second request timeout, so one slow accessory no longer blocks every other location update.
- Partial refreshes preserve the previous good report for accessories whose current Apple request fails or times out.
- Removed the deprecated device-tracker `battery_level` property; battery remains available through the dedicated battery sensor.

## [0.4.5] - 2026-10-01

### Fixed
- Initial Apple Find My location polling no longer blocks Home Assistant config-entry setup/bootstrap.
- Initial cloud refresh now runs as a config-entry background task after entities are loaded.
- Apple location requests time out after 60 seconds instead of hanging indefinitely.
- Config-entry update listener now ignores Apple session-state persistence and reloads only when selected accessory IDs change.

## [0.4.4] - 2026-10-01

### Fixed
- Accessory management now stores post-setup selection in Home Assistant config-entry options.
- Reloads now happen through the standard config-entry update listener after the options flow completes, avoiding setup-cancelled races.
- Removed reparsing of legacy stored accessory rows during rediscovery.
- Stale entities and devices for deselected accessories are cleaned up during setup/reload.

## [0.4.3] - 2026-10-01

### Fixed
- Split Configure-time keychain recovery, accessory discovery and stored-accessory parsing into separate failure stages.
- Stale or unreadable previously stored accessory rows no longer turn a successful keychain recovery into a generic recovery failure.
- Added clearer guidance when an escrow record/passcode or keychain record cannot be used.

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
