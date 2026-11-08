# MiG-29 volumetric exhaust experiment

This is a **reconstruction**, not a faithful translation of WT's `after_burner` DXBC.
It is deliberately MiG-29-specific and is not wired into the general exporter yet.

## Implemented

- DX9 SM3 custom VS/PS through `screenspace_general`.
- Finite-cylinder ray intersection and 96-step per-pixel emission/absorption integration.
- Native MiG dimensions and min/max values; native atlas rows 16–19, extracted at full 256-pixel width.
- Base-2 optical absorption, depth/height/radius colors, angularly faded shock modulation.
- Procedural radius/shake noise and existing entity throttle easing.
- Native six-layer nozzle masks (indices 8–13), ramp rows 23/30, with native perlin G as a substitute for the unresolved original noise binding.
- Custom scene-color refraction using native heat texture RG minus 127/255, replacing the generic Refract material and legacy glow quad.
- Exit-face box proxy (24 vertices per nozzle), including views from inside the volume.
- Pixel entry depth: opaque geometry entirely in front occludes the volume; no depth writes.
- Explicit 0.18 LDR exposure plus a hue-preserving shoulder to prevent axial white clipping; nozzle exposure 0.10 (artistic calibration, not WT exposure).

## Build / install

Compiler tested: SCell555/ShaderCompile `build_235_20231013.2`. From this directory:

```
ShaderCompile.exe /O 3 -ver 30 -shaderpath . dae_wt_volume_v2_vs30.hlsl
ShaderCompile.exe /O 3 -ver 30 -shaderpath . dae_wt_volume_v6_ps30.hlsl
ShaderCompile.exe /O 3 -ver 30 -shaderpath . dae_wt_exhaust_v3_vs30.hlsl
ShaderCompile.exe /O 3 -ver 30 -shaderpath . dae_wt_nozzle_v5_ps30.hlsl
ShaderCompile.exe /O 3 -ver 30 -shaderpath . dae_wt_heat_v3_ps30.hlsl
```

From repo root:

```
python res/experimental/mig29_volume/install.py <garrysmod-directory> <War-Thunder-directory> <VTFCmd.exe>
```

The installer backs up the existing `addons/wt_mig_29_9_12` into `%TEMP%/wtp/backups/`, replaces only its old nested-shell renderer, adds Lua/ramp/VCS assets, and also copies uniquely named VCS files into `garrysmod/shaders/fxc` (the verified load location). Existing model, sound and animation assets are not rebuilt. It fails on an unrecognized entity layout. Use new shader/material names after changing HLSL; GMod caches shaders.

**General re-export overwrites this experimental entity patch.** Run this installer again afterward. Do not distribute as a working Workshop-only addon yet; loading without the root VCS copies has not been tested.

## Tests performed in running GMod

Run `test_volume.lua` clientside through GTerm. It asserts nonzero pixels for side/rear/oblique/inside/partial-throttle views, zero pixels with engine off or a wall fully in front, dimmer partial throttle and changing noise over time. Nine cases passed on DX95 / gm_flatgrass, including a close side view. `test_exhaust.lua` verifies background displacement, off-state invariance, a bright annulus with dark centre, and limited (not zero) white highlights. Latest nozzle peak was 255/255, 115 white samples out of 4,025 lit samples; 15,674 heat samples differed from baseline. Volume tests check local axial continuity in side/close-side/animated views and reject a whole white rear plume. The continuity check failed v5 (trough/local-peak ~0.15) and passed v6 (~0.74); merely counting bright peaks had rewarded isolated slices. `preview.lua` captures the actual MiG MDL to `data/dae_mig_exhaust_{oblique,rear,side,sideNoHeat,top,nozzle}.png` and removes the client model. Tests remove their one-shot hooks.

A temporary networked MiG was also spawned, its installed `DrawTranslucent` invoked at full power without Lua errors, and then removed. This is not a flight test. The standalone MDL preview is the visual reference; the live-entity RT capture did not include Glide's separate chassis rendering. Python suite: 55 tests, including installer preservation/idempotence/fail-closed checks.

## Limits

- Numerical integration and noise approximate WT's analytic pieces. No exact bending, atmosphere, exposure or particle/depth-pass port. The nozzle subshader is reconstructed, not a complete port; original noise binding remains unresolved.
- Reference-calibrated v6 uses continuous core/halo density with weaker curved compression fronts. Noise varies across the radius instead of synchronizing entire cross-sections. This fixes v5's isolated side-view slices without increasing the 96 samples. Ring/nozzle envelopes are reconstruction, not decoded WT equations; blue-purple color is still weak and rear views remain too orange/hazy.
- Heat uses approximate moving quads and omits native blur/soft-depth intersection. Side previews with/without heat show additional speckling from this pass; continuity tests isolate the volume and do not validate heat's visual fidelity.
- A wall fully in front works, but an opaque surface cutting through the volume does not truncate integration at that surface. A scene-depth sampler is needed.
- 96 samples reduce axial undersampling but can still alias thin features; this doubles integration work versus v3, and GPU performance under many aircraft is unmeasured. CPU submission timing is not GPU timing.
- Linux, multiplayer, Workshop-only loading and non-SM3 devices untested.

## Restore this machine's original

Original pre-experiment backup:
`%TEMP%/wtp/backups/wt_mig_29_9_12_20261106_000250`.
Replace the addon with that backup and reload/restart. The experiment's uniquely named `dae_wt_volume_*`, `dae_wt_exhaust_*`, `dae_wt_nozzle_*`, and `dae_wt_heat_*` VCS files in `garrysmod/shaders/fxc` can also be removed when no longer used. No other vehicle addon was modified.
