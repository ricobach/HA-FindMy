# Security Policy

## Reporting a vulnerability

Please do not open a public issue for vulnerabilities that expose Apple credentials, authentication/session material, recovered Find My private key material, or Home Assistant secrets.

Use GitHub's private vulnerability reporting feature for this repository when available. If private reporting is unavailable, contact the repository owner privately before publishing technical details.

## Sensitive data

HA-FindMy handles sensitive Apple account and Find My material. Bug reports and diagnostics must never include:

- Apple ID passwords
- trusted-device screen-lock passcodes
- authentication/session tokens or cookies
- recovered private Find My keys
- unredacted Home Assistant storage files containing those values

The integration intentionally does not persist the Apple ID password or trusted-device passcode.
