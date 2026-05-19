# Changelog

All notable changes to this project will be documented in this file.

## [0.1.2] - 2026-05-19

### Fixed
- Removed spurious `pump_switch → off` log entry: in Auto mode the pump controller manages on/off via timeslots, no direct switch write is needed.

- Eliminated duplicate `pump_mode Heat → Auto` log entry caused by setting Auto mode twice per cycle (once in plan step, once in state evaluation).

- Shifted daily slot anchors from daytime (08:00 / 13:00 / 18:00) to night-time (22:00 / 02:00 / 05:00) so the pump runs during the coldest hours in winter.

## [0.1.1] - 2026-05-19

### Fixed
- Speed level dropdown in setup (slot desired speed) now shows `Slow/Medium/High` instead of `low/medium/high`.

- Dashboard "Last 5 Actions" card now renders each entry on its own line with proper line breaks.

## [0.1.0] - 2026-05-19

### Added
- Integration can now be reconfigured after initial setup via the "Configure" button in Home Assistant.

  All three setup steps (entities, settings, hardware option values) are accessible again to correct any value.

  Changes take effect immediately — the integration reloads automatically.

## [0.0.9] - 2026-05-19

### Fixed
- Changed default pump speed option values from `low/medium/high` to `Slow/Medium/High` to match hardware labels.

## [0.0.8] - 2026-05-19

### Changed
- Added setup fields for per-interval speed handling:

  - Optional speed select entities for slot 1/2/3 (`slot*_speed_select_entity`)

  - Desired speed level for each slot (`slot*_speed_level`)

- Daily plan application now also applies interval speed settings when slot speed entities are configured.

### Fixed
- Added optional `pump_running_sensor_entity` in setup to track actual runtime using a real running-status source instead of relying only on pump switch state.

- Improved state parsing (supports decimal comma values and additional ON-state tokens like `running`, `active`, `filtering`).

- Temperature handling now caches last valid values; `unknown/unavailable` no longer force temperature to `0.0`.

- Scheduler now enforces auto mode when applying normal daily plans.

## [0.0.7] - 2026-05-19

### Fixed
- Winter evaluation now runs immediately on integration startup, so `winter_state`, target runtime, and planned slots are populated without waiting for the first interval tick.

- Switching season to winter now triggers immediate schedule recalculation.

- Daily slot planning is recalculated on startup/winter-switch and logged as an action (`plan -> daily_slots`).

- Target runtime now always reflects configured winter minimum runtime.

- Pump runtime tracking now accepts additional ON-like pump states (`on`, `true`, `1`, `running`).

- Outdoor temperature `unknown/unavailable` no longer defaults to `0` and false-freeze behavior; state remains `unknown` until valid data arrives.

## [0.0.6] - 2026-05-19

### Changed
- Added setup helper descriptions for all configuration fields so users can select the correct entities and option values.

- Included clear explanations for key fields such as `pump_switch_entity` (main pump ON/OFF control), mode/speed selects, temperature sensors, and slot time entities.

- Added descriptions for winter settings and hardware option text mapping fields.

## [0.0.5] - 2026-05-19

### Fixed
- Added root [README.md](README.md) so HACS repository validation has standard project metadata.

- Restored [hacs.json](hacs.json) with explicit `domains: ["smart_pool_pump"]` and `content_in_root: false`.

- Updated integration manifest name to `Smart Pool Pump` and bumped version to `0.0.5`.

## [0.0.4] - 2026-05-19

### Fixed
- Removed [hacs.json](hacs.json) to avoid domain-resolution issues in HACS and rely on the standard integration layout scan (`custom_components/smart_pool_pump/manifest.json`).

- Bumped integration version to `0.0.4`.

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
