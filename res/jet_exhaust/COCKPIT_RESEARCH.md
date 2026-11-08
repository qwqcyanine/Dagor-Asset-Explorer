# J-16 first-person cockpit / native-style HUD feasibility

Research only: no production addon, EXE, physics, weapons or exporter behavior changed.

## Native evidence

- Model: `content.hq/pkg_cockpits/res/pkg_cockpits_aircrafts/j_16.grp`, DynModel `j_16_cockpit`; descriptor `content.hq/pkg_cockpits/res/dynModelDesc.bin`.
- LOD0: 571 skeleton nodes, 446 mesh objects, 1,216,059 triangles, 65 materials. Contains exterior airframe, landing gear, nozzle petals, pylons and damage geometry as well as cockpit. Three objects are skinned; others are rigid.
- A material-based candidate filter (not production-ready) leaves 147 objects / 776,086 triangles, 146 directly referenced bones and 155 with ancestor closure. It still includes some pylons/damage objects; mixed-material meshes could be excluded incorrectly. Requires visual per-object/material review before export. This is not a compiled or visually accepted 155-bone model.
- Existing general Source export fallback uses `MAX_SOURCE_BONES=128` and otherwise emits `modelHasTooManyBones`; explicit `keepBones` uses the separate reduced-bone path. Existing aircraft splitting enforces 256. Do not simply export the raw cockpit or globally raise the legacy constant. Keep geometry weights and necessary ancestors, and deliberately use reduced export; split only if still needed.
- `j_16_cockpit_anim` is readable with existing `util.a2d.A2D`: 541 tracks, 3.333333s duration. Sampling endpoints confirms changing throttle/throttle1, stick_elevator/stick_ailerons, compass, blister1 and gears. Controller-to-clip ranges still need verification; track readability alone is not validated instrument animation.
- `aces.vromfs.bin/gamedata/flightmodels/j_16.blk` has `headPos=(7.8,1.077,0)`, translating to roughly Source `(312,0,43.08)` with existing x,z,y and scale 40. Must check actual compiled alignment, near clipping and FOV.
- Unit flag `ilsJ15t=true`; `gui.vromfs.bin/reactivegui/planeils.nut` selects `planeIlses/ilsJ10a.nut::ilsJ15t`, backed by `ilsJ10a.das`, 17.5-degree X/Y HUD FOV, metric units, English language setting. This is the current installed J-16's selection, not a guess from its name.
- HUD mesh `collimator` uses `dynamic_mfd_trans`; main MFD meshes `cn_gauge_mfi_j_16` / `_1` and backup `j_11b_mfd_secondary1` use `dynamic_mfd`. Static material conversion does not implement these displays.
- Native display atlas is 2048x1280; configured pages include `mfdSu35J16Horizon`, `su30Radar`, `su30RadarElevation`, HSD, RWR, thermal/tracking, `europeanAviaHorizont` and `plane_ils`.
- Native `.nut`/`.das` sources are readable, but depend on Dagor GUI, FlightModelWrap, RadarHud, WTCamera etc. Reimplement drawing/data adapters in GMod Lua, not execute the original files. HUD graphics are not equivalent to implementing radar or ballistic solutions.
- Prior texture probe found 44 of 70 references missing from cockpit-only cache; this does not establish absent WT assets. Resolve shared and exterior texture packs before judging appearance.

## Minimal integration proposal

1. Export a separate interior model retaining HUD/MFD planes, canopy and required instrument/control bones. Merge static bindings only after validating transforms; preserve parent chains and skinned weights. No collisions or changes to the existing external aircraft physics/model required. Hide only overlapping original cockpit pieces locally if necessary; keep wings/nose visible through windows.
2. Render only for local first-person occupant, using a managed clientside model and Glide `GetFirstPersonOffset` / `isLocalPlayerInFirstPerson`. Explicit cleanup on vehicle removal/exit and validity checks; do not replace global CalcView or spawn HQ cockpits for every distant aircraft.
3. Draw native-layout basic HUD: attitude ladder, heading, flight-path marker, speed, altitude, selected weapon/ammo and existing Glide lock state. Use physical HUD aperture masking and view-dependent projection (collimation), not a green texture permanently glued to glass. Account for Glide's variable FOV/free look.
4. Use render-target-backed materials for MFD attitude/basic status pages. Keep resources reused and update only active local cockpit; do not allocate RTs every frame or per distant plane.
5. Drive controls/instruments with verified native animation curves. Reserve radar, RWR, CCIP/CCRP, mirror render views and advanced avionics for separate verified work.

Telemetry caveats: Glide velocity is not WT IAS; world Z is not true barometric altitude, and existing server `altitude` is a capped downward trace. Calibrate units, datum and sampling rather than label substitutes as native simulation. Fuel, engine temperature, radar scan and WT ballistic impact data may have no corresponding Glide simulation. Do not invent live readings.

## Validation before adoption

- Compare retained triangles/materials and bone weights before/after reduction; assert bone budget and preserved ancestor transforms; compile isolated model.
- Inspect front seat, canopy/glass, HUD aperture, instruments and external-airframe overlap across free-look/FOV.
- Test seat switching, third-person, exit, death/removal and client resource cleanup; confirm existing aircraft weapons/physics untouched.
- Compare HUD units and marker projection with known headings/attitudes/speeds, and check FPS/frame-time before/after.

Evidence: `build/cockpit-research.json`, `build/cockpit-digest.log`, `build/cockpit-config-research.log`, `build/cockpit-animation.log`; native sources extracted locally to `build/cockpit-native/`. Read-only probes completed; no Source compilation or live cockpit rendering performed.

API references: https://gmodwiki.com/Global.ClientsideModel and https://gmodwiki.com/render_rendertargets ; installed Glide source `build/glide-api/lua/glide/client/camera.lua` and `entities/base_glide_plane/cl_init.lua`.
