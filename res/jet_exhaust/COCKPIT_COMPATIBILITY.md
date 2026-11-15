# Experimental cockpit compatibility

The normal GUI support gate remains **J-16 only**. Compilation is not visual or flight acceptance, and does not justify enabling every aircraft.

## Native-data validation

All validation outputs were written under project `build/`. Compilation probes compared installed GMod models/materials/Lua/sounds/addons before and after and verified that they were unchanged.

| Aircraft | Result | Remaining blockers |
| --- | --- | --- |
| Su-30SM2 | Compiled 4 model parts; 31 VTFs | Aircraft-specific exterior-cockpit suppression, display routing/layout and eye alignment not validated |
| Su-33 | Compiled 4 model parts; 58 VTFs | Same; native displays differ from J-16 |
| MiG-29 9.12 | Compiled 4 model parts; 54 VTFs after shortening output path | Same; long paths can break VTFCmd |
| F-16A Block 10 | Private current-selector export compiled 4 parts; 6 VTFs; 541,697 faces preserved | Production gate still rejects 286 bones; missing gauges and visual calibration remain |
| A-10A early | Geometry/HUD/stick inspection passed after resolving shared pack | Pack `a_10.grp` contains `a_10a_early_cockpit`; direct aircraft-name lookup fails. No compilation or visual validation |
| Spitfire Mk I | Current interior/HUD validation failed | UK gauges and native `collimator` shader do not match J-16-centric selection/HUD assumptions |

## Additional native rule audit

This round inspected models/configurations and animation availability, not compiled or in-game results. The initial batch contained flightmodel lookup failures; targeted retries resolved Harrier and Heinkel aliases. An empty-selection bug in the audit itself was also fixed before reporting Heinkel results.

| Aircraft | Current selection | Special rule found |
| --- | --- | --- |
| F-16A Block 10 | 286 bones; 285 directly referenced | Excess is not just unused ancestor bones. Diagnostic whole-object partition was 256 + 31 bones (shared ancestors repeated); subsequent face-budget-aware compilation is documented below. 23 gauge-material names excluded |
| F-14A early | 45 bones / 321,289 faces | Pack is `f_14.grp`; model is `f_14a_early_cockpit`. Extraction passes despite 23 excluded gauge-material names |
| Harrier T.10 | 105 bones / 616,382 faces | Pack `harrier_t10.grp`, cockpit `harrier_t_10_cockpit`, flightmodel `harrier_t10.blk`. Two named head nodes; only the configured pilot viewpoint checked |
| A-10A early | 51 bones / 384,691 faces | Shared `a_10.grp` contains early and late cockpits. 24 gauge-material names excluded despite extraction passing |
| Spitfire Mk I | 88 selected bones; extractor rejected | Retained sight uses `collimator`, not `dynamic_mfd_trans`; 27 excluded gauge-material names |
| B-25J-1 | 45 selected bones; extractor rejected | Same legacy-sight issue; 28 excluded gauge-material names |
| He 111 H-6 | Zero selected objects; extractor rejected | Flightmodel `he-111h-6.blk`; materials use `inside`, `interior`, and `common_bomber_gauges`, not `cockpit`. No modern HUD/display materials or standard stick animation pair |

Consequences for a general exporter:

- Resolve **pack, cockpit model and flightmodel** identities separately from native metadata; underscore replacement alone is insufficient (e.g. `he-111h-2.blk` identifies model `he_111h_3`). Audit aliases above are probe inputs, not a production resolver.
- Treat cockpit geometry, modern HUD, legacy collimator, MFD, mirrors and animated controls as separate capabilities. Missing optional HUD/stick tracks must not imply that a valid analog cockpit is unusable.
- Validate instrument completeness independently of successful extraction/compilation. Excluded-material counts are audit signals, not proof that every excluded damaged-glass variant should be rendered.
- Do not prune objects merely because names contain `gears`, `flaps`, or `wheel`: cockpit levers/indicators and actual exterior geometry share those terms. Inspect materials, geometry and dependencies.
- Preserve weighted-bone/ancestor closures when partitioning. F-16 private compilation now verifies this for current-selector geometry; it does not authorize dropping instrument bones or establish completeness.
- Respect native instrument units and available telemetry. Inspected US/UK configurations use `altitude_koef` about 3.28, while Heinkel uses 1.0. Glide world speed/map Z are still not IAS/barometric altitude.
- Multiple crew/head bones do not define usable passenger camera positions automatically. Trainer/bomber viewpoints require explicit mapping rather than choosing the first matching head bone.

## Candidate selection and filename audit

A separate, non-production candidate selector added national gauge families, `common_bomber_gauges`, `inside`/`interior` materials and legacy `collimator` shaders to the existing selection. These counts measure selected geometry, not visual completeness:

| Aircraft | Candidate objects / bones | Added faces over current selection | Diagnostic bone partitions |
| --- | --- | --- | --- |
| F-16A Block 10 | 391 / 395 | 61,409 | 256 + 140 |
| Spitfire Mk I | 147 / 148 | 43,427 | 148 |
| F-14A early | 160 / 164 | 32,046 | 164 |
| B-25J-1 | 122 / 123 | 40,317 | 123 |
| A-10A early | 164 / 166 | 32,537 | 166 |
| Harrier T.10 | 160 / 164 | 107,982 | 164 |
| He 111 H-6 | 50 / 53 | 87,661 | 53 |

Spitfire and B-25 retain legacy collimator geometry without a modern HUD; Heinkel requires neither. However, the broader selector also admits **whole wing objects** on F-16, Harrier and Heinkel because their mixed material sets include `inside`. These are not accepted interior selections. Selection must account for mixed-material faces and visibility; globally adding these substrings is unsafe. Restoring instrument coverage can also increase bone requirements substantially: the F-16's current-selector 286-bone experiment does not validate the 395-bone candidate.

The first F-16 private SMD export failed before compilation because the native object name `Handle_Chassis_AV_EXP:SCREWS:Object5270` contains Windows-invalid colons. The private retry assigns safe names only to generated SMD files, leaving native object names, skeleton names and weights intact. A production fix must additionally handle filename collisions and consistently update QC references; renaming bones is not the solution. The release exporter is unchanged by this probe.

## F-16 private compilation result

The safe-filename retry completed successfully. Bone-closure and 180,000-face limits produced four compiled components:

| Part | Bones | Faces |
| --- | --- | --- |
| 0 | 151 | 179,495 |
| 1 | 62 | 176,938 |
| 2 | 74 | 179,262 |
| 3 | 4 | 6,002 |

The probe preserved all **541,697 selected faces and their weights**, converted **6 textures**, and verified the installed GMod inventory was unchanged. Bone totals across parts include repeated ancestors; do not sum them as unique bones. This proves that the existing 286-bone selection can compile without discarding bones, not that the missing instruments or the separate 395-bone candidate are correct. No in-game rendering or alignment acceptance was performed.

## Face-level candidate audit

A separate private selector now retains individual material runs rather than entire mixed-material objects. It rebuilds face-material boundaries without changing vertex indices, UVs, skin weights or bone names. Self-checks cover mixed wing materials, alternating gauge/glass runs and legacy collimators; the native audit checks face totals and removes all `aircraft_normal_detail` material faces.

| Aircraft | Objects | Bones including ancestors | Selected faces |
| --- | --- | --- | --- |
| F-16A Block 10 | 391 | 395 | 578,109 |
| Spitfire Mk I | 148 | 149 | 418,910 |
| F-14A early | 160 | 164 | 349,185 |
| B-25J-1 | 122 | 123 | 428,251 |
| A-10A early | 164 | 166 | 416,888 |
| Harrier T.10 | 163 | 168 | 615,730 |
| He 111 H-6 | 50 | 53 | 38,341 |

This is **still not a release selector**. Interior-labelled faces also form exterior structural cut surfaces: F-16 retains 72 faces per wing and 28 per elevator; Harrier retains 245 per wing and 60 per elevator; Heinkel retains 358 per wing spanning up to 11.1 metres from the centreline. Face filtering removes most wing geometry but cannot establish cockpit ownership by material alone. Native visibility, mesh ancestry and geometry must disambiguate those residuals without discarding similarly named cockpit instruments. Spitfire/B-25 legacy sights survive; absence of a HUD is still not a cockpit failure. All audit files remain under `build/`; production selection is unchanged.

The expanded F-16 face candidate also **compiled successfully**, using 55 converted textures and four components: **151 bones / 179,495 faces**, **62 / 176,938**, **156 / 177,997**, and **32 / 43,679**. The report verifies all 578,109 selected faces and weights were preserved, the 395 unique required bones were partitioned without deletion, and the installed GMod inventory was unchanged. This resolves compilation feasibility for the expanded candidate, not the residual exterior faces or missing visual calibration.

## Why the gate is unchanged

`interiorMaterial` recognizes selected Soviet/Chinese gauge families, not all nations' instrument materials. `exportCockpit` still supplies J-16-specific exterior material suppression, and the display Lua routes J-16 screen names to its pages. Removing the whitelist alone could omit instruments, overlap exterior seats/panels, or display incorrect avionics.

## Reproduction artifacts (local, ignored)

- `build/other-cockpits-validation.json`, `build/other-cockpits-validation-extra.json`
- `build/other-cockpits-compile/results.json`
- `build/oc/results.json` (MiG-29 short-path retry)
- `build/validate_other_cockpits.py`, `build/compile_other_cockpits.py`
- `build/audit_cockpit_rules.py`, `build/cockpit-rule-audit.json`
- `build/cockpit-rule-audit-extra.json` (corrected Harrier result)
- `build/cockpit-rule-audit-he_111h_6.json` (corrected Heinkel result)
- `build/audit_cockpit_selection.py`, `build/cockpit-selection-candidates.json`
- `build/compile_f16_partition.py`, `build/f16p/result.json` (current-selector compile)
- `build/cockpit_candidate_faces.py`, `build/audit_cockpit_faces.py`, `build/cockpit-face-candidates.json`
- `build/compile_f16_partition.py --faces`, `build/f16f/result.json` (face-candidate compile; inspect status)

MiG-29 initially failed to create a VTF at an existing destination directory when the full path was 261 characters. The identical export succeeded under shorter `build/oc`. The normal exporter currently detects missing VTF output and fails rather than silently delivering an incomplete addon; it does not yet eliminate this legacy converter path limitation.

Next safe expansion: calibrate Su-30SM2/Su-33/MiG-29 model selection, exterior masking and native display handling, then visually validate those aircraft before enabling them. No other-aircraft GUI release or in-game acceptance was performed by these probes.
