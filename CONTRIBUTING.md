# Contributing

Contributions are welcome.

## Development checks

Before opening a pull request:

1. Keep the integration under `custom_components/ha_findmy`.
2. Update `manifest.json` when changing the integration version.
3. Keep `strings.json` and `translations/en.json` aligned.
4. Run Python syntax checks with `python -m compileall custom_components/ha_findmy`.
5. Ensure the HACS and hassfest GitHub Actions pass.

## Releases

HA-FindMy follows semantic versioning. Release tags use the form `vX.Y.Z` and must match the `version` in `custom_components/ha_findmy/manifest.json`.

## Security

Do not commit or post Apple passwords, device passcodes, session tokens, recovered private keys, Home Assistant secrets, or real account-state exports.
