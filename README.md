# Smart Pool Pump

Home Assistant custom integration to control a pool pump with winter-first logic,
minimal hardware writes, and TEST MODE dry-run support.

## Installation with HACS

1. Open HACS in Home Assistant.
2. Add custom repository `BigBasti84/ha_smart_pool` as type `Integration`.
3. Install the latest release.
4. Restart Home Assistant.
5. Add integration: Settings -> Devices & Services -> Add Integration -> Smart Pool Pump.

## Repository Structure

- `custom_components/smart_pool_pump/manifest.json`
- `custom_components/smart_pool_pump/*`

## Notes

- TEST MODE records planned changes without writing to hardware entities.
- Winter logic currently implemented; summer logic is planned for later releases.
