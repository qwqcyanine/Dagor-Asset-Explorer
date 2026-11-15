# Aircraft weapons/export update

## Available through Source/Glide GUI export

- Native hardpoint presets or per-hardpoint selections, localized weapon names, numbered textured preview, and gun/missile/bomb reload overrides (0 keeps the WT default).
- Native ammunition and baseline arcade reloads; automatic cannon fire, single-press missiles/rockets, conventional bombs and gun pods. Independent mounted models disappear per shot; empty rocket containers are discarded cosmetically and restored on reload.
- Actual weapon names in Glide's weapon selection, native mount transforms and mirrored face winding.
- Source bone/mesh splitting, native skin-node mapping and inverse-bind correction; flaperon parent hinges and chute-cover geometry preserved.
- UserSkin ZIP import, skin families, aircraft audio mapping, volumetric exhaust/nozzle/heat resources, cutout-alpha fixes, and OpenGL preview text-state restoration.

## Optional experimental J-16 cockpit — GUI export

In J-16's Glide export dialog, enable **Experimental HQ cockpit (J-16)** (off by default). Requires WT's installed HQ cockpit pack and UI atlas, plus configured StudioMDL/gameinfo/VTFCmd paths. Other aircraft and helicopters cannot enable it.

The normal addon now includes the high-detail cockpit, native stick/bellows animation, collimated HUD, native-artwork MFD pages and cubemap mirrors. Cockpit parts compile in a temporary compiler-game directory with materials installed first, then join the addon; no prior test files or standalone deployment scripts are required. Missing resources or failed tools abort the export. The cockpit is first-person-only and adds export time/rendering cost.

MFDs are a partial layout/drawing port, not complete WT avionics. Game speed/map altitude are not IAS/barometric altitude; missing radar/RWR data stays unavailable. Missiles/rockets use Glide/Source approximations, including physics speed limits. Guided/retarded bombs and cross-hardpoint payload/exclusivity validation are not supported.

## Verification and cleanup

- `python -m unittest discover -s tests`: 117 tests passed; `git diff --check` passed before release. Real installed J-16 HQ data compiled into four cockpit models and four instrument PNGs under project `build/`, without installing game test assets.
- Prior isolated GMod checks covered weapons, mount synchronization/reload, pod disposal, stick poses, flaperons, closed covers, and display captures. These do not replace full flight, subjective audio, multiplayer, or manual EXE testing.
- Session test files were removed from GMod. Normal addons/configuration/saves were preserved, including root shaders referenced by existing aircraft. Recovery copies and the removal manifest remain outside the game in ignored `build/`.

## Rebuild (Windows, repository root)

```bat
python -m PyInstaller --noconfirm --onefile --name DagorAssetExplorer-Weapons --paths src/dae --hidden-import gui.customtreeview --hidden-import gui.mapDialog --hidden-import gui.previewDialog --hidden-import gui.skinImportWidget --hidden-import util.wtskins --hidden-import util.sourceparts --hidden-import util.jetexhaust --hidden-import util.wtloadout --hidden-import util.wtweapons --hidden-import util.wtcockpit --specpath build --distpath build/exe-staging --workpath build/weapon-exe src/dae/__main__.py
```

Place the EXE beside current `res/`, `lib/`, and `ui/` directories. Keep the user's `settings.json`; do not distribute test exports, game data or cleanup backups. Re-export aircraft to apply exporter changes; fully restart GMod after replacing same-path models.
