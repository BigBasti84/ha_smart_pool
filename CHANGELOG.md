# Changelog

All notable changes to this project will be documented in this file.

## [0.1.7] - 2026-05-19

### Changed
- Timeslot writes are now dispatched as one batched scheduler action (concurrent service calls) instead of six sequential writes, reducing failures when the pool controller becomes temporarily unavailable after a slot update.

- Interval apply now includes all slot from/to times and configured slot pump speeds in the same batch, plus the main pump speed select.

- Added readback verification after interval writes; only values that are actually confirmed on entities are logged as `set`.

- If verification fails, the integration retries after 2 minutes. After 3 failed attempts, a notification is sent (when `notify_service` is configured).

## [0.1.6] - 2026-05-19

### Fixed
- **Filtration interval times were not being set**: `time.set_value` requires the parameter `value`, not `time`. The wrong key caused the service call to be silently ignored by Home Assistant.

- **Pump speed was never set in normal winter mode**: the scheduler now sets the main pump speed select to the slot-1 configured speed (default: Slow) whenever the daily plan is written, not only during freeze protection.

- Added try/except with `_LOGGER.error` around all service calls so failures are visible in the Home Assistant log instead of silently aborting the update.

- Normalized time value comparison (`HH:MM` vs `HH:MM:SS`) so the before-value check does not cause unnecessary repeat writes.

## [0.1.5] - 2026-05-19

### Added
- Optional **fallback outdoor temperature sensor** in setup (entities step).

  When the primary sensor becomes unavailable, the integration automatically reads from the fallback sensor instead.

- **Notification on sensor unavailability**: if a notify service is configured, a push notification is sent when the primary outdoor temperature sensor goes unavailable, stating whether a fallback is in use or the last known value is being held.

- A recovery notification is sent when the primary sensor comes back online.

## [0.1.4] - 2026-05-19

### Added
- Temperature hysteresis (1 °C buffer) prevents rapid mode-switching when the outdoor temperature hovers near a freeze threshold.

  A colder state is entered immediately when the temperature crosses a threshold downward.

  Returning to a warmer state only happens once the temperature has risen at least 1 °C **above** the threshold — so a reading of 2.1 °C does not immediately cancel a freeze-protection mode triggered at 1.9 °C.

## [0.1.3] - 2026-05-19

### Fixed
- Scheduler now verifies the actual slot entity values on every update tick.

  If the pool controller loses power and its time slots reset, the integration detects the mismatch and re-applies the correct slots within the next update interval (default 5 min) — no HA restart or midnight required.

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
