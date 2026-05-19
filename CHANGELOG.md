# Changelog

All notable changes to this project will be documented in this file.

## [0.0.3] - 2026-05-19
### Fixed
- Fixed HACS metadata parsing by changing [hacs.json](hacs.json) to use `domain: smart_pool_pump`.
- Bumped integration version to `0.0.3`.

## [0.0.2] - 2026-05-19
### Fixed
- Restored compatibility with existing HACS setup by renaming integration folder and domain back to `smart_pool_pump`.
- Added [hacs.json](hacs.json) for explicit HACS metadata.

## [0.0.1] - 2026-05-19
### Added
- Initial Smart Pool Pump integration scaffold with config flow, scheduler, sensors, services, and dashboard.
