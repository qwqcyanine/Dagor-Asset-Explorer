# WT aircraft weapon loadouts

In **Export to Gmod Glide addon**, choose **Weapon loadout (export-time)**.
The default **No external weapons** keeps the previous clean-aircraft export.
The list comes from the selected aircraft's native `weapon_presets` data.
**Custom hardpoints** lets each slot choose one of its native presets or stay empty.
Weapon descriptions come from the installed WT `lang.vromfs.bin` in the UI language,
with English/raw-name fallbacks. Duplicate stores show quantities; containers show
native child ammunition and capacity. Hover for original preset/BLK identifiers.
These are display names only, not a claim that every listed weapon is functional.
The geometry preview labels native hardpoint positions with numbers and leader lines:
yellow = loaded, blue = empty. Labels are visible through the model and follow rotation.
Empty slots use a representative native emitter; multi-store racks use their emitter center.
Guided/retarded bombs may be previewed geometrically but are still rejected by functional export.
These are slot-local choices, not a guarantee that arbitrary combinations obey all
WT cross-slot restrictions or payload limits. **Preview selected loadout** opens
an orbitable model preview; it is not a Source shader/animation preview.
Gun, missile and bomb reload fields override seconds per weapon group; zero means
**WT default** (not instant reload). Overrides apply at export time.

The selected preset is baked into the MDL: native slot-local presets select pylons,
weapon meshes are placed with their emitter's full world transform, and mount bones
are retained through automatic body/nozzle splitting. Weapon materials receive a
separate namespace and use the normal texture/livery pipeline. The importer searches
WT resource packs for weapon models and textures, including available HQ copies.

Built-in guns use aircraft ammunition counts (summed for identical guns), native
shot frequency, and baseline arcade empty-magazine reload times from
`config/gameplay.blk` (caliber and aircraft-type overrides; no crew skill bonus).
For J-16 this is 150 rounds, 30 rounds/second, and 60 seconds to reload.
Gun scheduling preserves sub-tick remainder during continuous fire (Glide's default
`CurTime() + FireDelay` reduced 30 Hz to 22.2 Hz on a 66.7-tick server). Firing is
still limited to one shot per weapon think; rates above server tick frequency are
not reproduced. Holstered reload completion clears the reload flag.

Single-round AAM/AGM mounts become independent visible/blank bodygroups and compiled
projectile models using the same reflection-corrected geometry. Firing consumes one
round and hides only that mount; empty groups reload together and restore all their
mounts, even while another weapon is selected. J-16 six-PL-8B reload is 200 seconds.
Glide provides targeting and HUD; native launcher shotFreq is NOT the reload time.
Missiles and bombs fire once per press: holding attack never launches the remaining
mounts automatically. Release before the next shot, including after reload.

Missile lifetime, mass, initial speed, thrust/mass acceleration and requested top
speed come from WT, but top speed is capped at 4000 Source units/s. Glide guidance,
collision proxy, damage/explosion and continuous propulsion remain approximations,
not WT ballistics; gun damage is still the existing caliber-based estimate.
Single-store ordinary HE bombs use independent mounts, inherited aircraft velocity,
gravity and Glide impact explosions. Blast damage/radius are approximations based
on explosive mass, not WT fragmentation or explosive-type equivalence. Guided and
retarded bombs are rejected rather than silently treated as ordinary bombs.
Native `additional gun` pods use aircraft ShowNodes, original emitters and per-pod
ammunition; each pod is independently selectable and remains visible when empty.
Unguided rockets and multi-bomb containers remain visual-only. No payload mass change, new aircraft
collision geometry, crew skills or in-game preset switching; export again to change
presets. Models already loaded in GMod need a full restart.

Unknown presets, missing emitters/models/textures, ambiguous slot references, and
multi-round definitions without explicit mount transforms fail with an error rather
than silently dropping weapons. Aircraft-provided pod meshes (`empty_mesh`) use
native ShowNodes; other pod/multi-round layouts are not universally supported.

## Acceptance

- Automated tests cover slot-local names, visibility, transform/bone binding,
  material isolation, missing textures, GUI selection, ammunition/reload precedence,
  per-mount metadata, projectile rebasing and bodygroup generation.
- J-16 / `j_16_pl8b.blk` is the initial six-PL-8B validation fixture.
- GTerm isolated real-entity checks: hold/release/press launches two PL-8B total;
  mixed J-16 launches two PL-12 and drops five GP-250-3 bombs, five impact explosions,
  custom 3-second holstered reload and seven restored client bodygroups. This does
  not establish long-range radar/seeker fidelity or manual visual acceptance.
- Su-25 four SPPU-22 pods each fired 260 real shots at ~56.43 Hz (native target
  ~56.6 Hz), independently consumed ammunition, and reloaded while holstered after
  the custom 3 seconds. The internal cannon remained at 250 rounds. This is not a
  manual HUD/sound/damage-balance or gun-pod visual acceptance test.
- `test_visual_loadout.lua` checks compiled missile triangles, materials and retained
  mount bones and creates two close inspection captures. It is not a flight test.
- GMod may retain the old MDL after re-export. Fully restart GMod and respawn when
  testing normal model paths; temporary renamed-model checks do not refresh them.
