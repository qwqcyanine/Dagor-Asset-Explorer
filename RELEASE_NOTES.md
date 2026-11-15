# Glide vehicle & aircraft export update

## Available through Source/Glide GUI export

- Ground vehicles (tracked tanks and wheeled vehicles): native gearbox, suspension travel, mass-scaled traction/springs, independent left/right track scrolling, armor kit selection, and War Thunder FMOD engine/track/turret/weapon sound extraction.
- Fixed-wing aircraft and helicopters: native flightmodel inertia/controls/landing gear animation, rotor/turbine/cannon/gear FMOD sound extraction, and volumetric HLSL exhaust/nozzle/heat distortion shaders.
- Native hardpoint presets or per-hardpoint selections, localized weapon names, numbered textured preview, and gun/missile/bomb reload overrides (0 keeps the WT default).
- Native ammunition and baseline arcade reloads; automatic cannon fire, single-press missiles/rockets, conventional bombs and gun pods. Independent mounted models disappear per shot; empty rocket containers are discarded cosmetically and restored on reload.
- Source bone/mesh splitting, native skin-node mapping and inverse-bind correction; flaperon parent hinges and chute-cover geometry preserved.
- UserSkin ZIP import, skin families, cutout-alpha fixes, concurrent VTFCmd conversion, and OpenGL preview text-state restoration.

## Rebuild (Windows, repository root)

```bat
python -m PyInstaller --noconfirm --onefile --name DagorAssetExplorer --paths src/dae --hidden-import gui.customtreeview --hidden-import gui.mapDialog --hidden-import gui.previewDialog --hidden-import gui.skinImportWidget --hidden-import util.wtskins --hidden-import util.sourceparts --hidden-import util.jetexhaust --hidden-import util.wtloadout --hidden-import util.wtweapons --hidden-import util.vromfs --hidden-import concurrent.futures --specpath build --distpath build/exe-staging --workpath build/pyinstaller src/dae/__main__.py
```

Place the EXE beside current `res/`, `lib/`, and `ui/` directories. Keep the user's `settings.json`; do not distribute test exports or game data. Re-export vehicles/aircraft to apply exporter changes; fully restart GMod after replacing same-path models.
