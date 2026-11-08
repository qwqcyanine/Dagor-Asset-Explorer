"""Deploy experimental split-model Sukhoi exports; leaves addons/su30 and MiG untouched.
Usage: python install_sukhoi.py <garrysmod> <WarThunder> <VTFCmd.exe> <staged-export-root>
Compile split_sukhoi.py outputs and the Sukhoi shaders first.
"""
from datetime import datetime
from io import BytesIO
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys
import tempfile

from install import patch_entity, patch_exhaust


def component_patch(text, name):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src/dae"))
    from util.sourceparts import component_patch as patch
    return patch(text, f"models/wt_glide/{name}_nozzles.mdl")


def install(game, wt, converter, exports):
    source = Path(__file__).resolve().parent
    game, wt, exports = Path(game), Path(wt), Path(exports)
    sys.path.insert(0, str(source.parents[2] / 'src/dae'))
    from parse.gameres import GameResourcePack
    from parse.material import DDSxTexturePack2
    from util.glide import findAircraftBlk, generateAircraftLua, controlSurfaces, exhausts, exportAircraftSounds
    from util.a2d import A2D
    from PIL import Image
    grp = str(wt / 'content/base/res/aircrafts/air.grp')
    assets = GameResourcePack(grp).getPackedFiles()
    from parse.realres import DynModel, GeomNodeTree, CollisionGeom
    from util.assetcacher import AssetCacher
    for asset in assets:
        if isinstance(asset, (DynModel, GeomNodeTree, CollisionGeom)):
            AssetCacher.cacheAsset(asset)
    textures = {'afterburneratlastex', 'afterburnerflamenozzlemask', 'distortion_hot_air_a_tex', 'perlin_noise'}
    pack = DDSxTexturePack2(str(wt / 'content/base/res/fx.dxp.bin'))
    images = {t.name: Image.open(BytesIO(t.getDDS())).convert('RGBA') for t in pack.getPackedFiles() if t.name in textures}
    assert images.keys() == textures
    images['sukhoi_volume_ramps'] = images['afterburneratlastex'].crop((0, 32, 256, 36))
    shaders = ['dae_wt_volume_v2_vs30', 'dae_wt_sukhoi_volume_v1_ps30', 'dae_wt_exhaust_v3_vs30', 'dae_wt_sukhoi_nozzle_v1_ps30', 'dae_wt_heat_v3_ps30']
    assert all((source / 'shaders/fxc' / (s + '.vcs')).is_file() for s in shaders)
    model_dirs = {}
    for name in ('su_30sm2', 'su_33'):
        for suffix in ('', '_nozzles'):
            candidates = (exports / name / 'source_export/models/wt_glide', game / 'models/wt_glide')
            directory = next((p for p in candidates if all((p / (name + suffix + ext)).is_file() for ext in ('.mdl', '.vvd', '.dx90.vtx'))), None)
            assert directory is not None, 'Compile all split models first'
            model_dirs[name + suffix] = directory
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for key, image in images.items():
            image.save(tmp / (key + '.tga'))
            subprocess.run([str(converter), '-file', str(tmp / (key + '.tga')), '-output', str(tmp), '-version', '7.2', '-format', 'RGBA8888', '-alphaformat', 'RGBA8888', '-nomipmaps', '-flag', 'CLAMPS', '-flag', 'CLAMPT'], check=True)
        for name in ('su_30sm2', 'su_33'):
            addon = game / 'addons' / ('wt_' + name)
            if addon.exists():
                backup = Path(tempfile.gettempdir()) / 'wtp/backups' / (addon.name + '_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
                shutil.copytree(addon, backup)
                print('BACKUP', backup)
            for suffix in ('', '_nozzles'):
                compiled = list(model_dirs[name + suffix].glob(name + suffix + '.*'))
                assert any(p.suffix == '.mdl' for p in compiled), 'Compile split models first'
                dest = addon / 'models/wt_glide'
                dest.mkdir(parents=True, exist_ok=True)
                for p in compiled:
                    shutil.copy2(p, dest)
            shutil.copytree(exports / name / 'source_export/materials', addon / 'materials', dirs_exist_ok=True)
            dest = addon / 'materials/models/wt_glide/fx'
            dest.mkdir(parents=True, exist_ok=True)
            for p in tmp.glob('*.vtf'):
                shutil.copy2(p, dest)
            dyn = next(a for a in assets if isinstance(a, DynModel) and a.name == name)
            dyn.computeData()
            blk = findAircraftBlk(grp, name)
            volume = blk['AfterBurner0']['volumetricAfterBurner']
            a2d = A2D.fromPack(grp, name + '_anim')
            model = dyn.getModel(0)
            sounds = exportAircraftSounds(str(wt), blk, str(addon / 'sound/wt' / ('wt_' + name)))
            lua = generateAircraftLua('wt_' + name, name.replace('_', ' ').upper(), f'models/wt_glide/{name}.mdl', dyn.geomNodeTree, blk, a2d, controlSurfaces(model), sounds=sounds)
            lua = component_patch(patch_exhaust(patch_entity(lua)), name)
            # WT flame-card pivots are deep inside these airframes, not the nozzle exit.
            centres = exhausts(dyn.geomNodeTree)
            def flame_origin(match):
                old_y = float(match[2])
                pos, radius = min(centres, key=lambda entry: abs(entry[0][1] - old_y))
                return f'{match[1]}Vector( {pos[0]:.3f}, {pos[1]:.3f}, {pos[2]:.3f} ), radius = {radius:.3f}'
            lua, changed = re.subn(r'(\{ bone = "jet_flame\d*", pos = )Vector\( [-\d.]+, ([-\d.]+), [-\d.]+ \), radius = [-\d.]+', flame_origin, lua)
            assert changed == 2
            namespace = 'wt_' + name + '_exhaust'
            lua = lua.replace('wt_mig29_volume', namespace).replace('math.min(mins.x, -600)', 'math.min(mins.x, -850)')
            runtime = addon / 'lua' / namespace
            runtime.mkdir(parents=True, exist_ok=True)
            v = (source / 'volume.lua').read_text().replace('MiG-29 only', name)
            v = v.replace('dae_wt_volume_v6', 'dae_wt_sukhoi_volume_v1').replace('fx/mig29_volume_ramps', 'fx/sukhoi_volume_ramps')
            v = v.replace('Lerp(power, 7, 10)', f'Lerp(power, {volume["minHeight"]}, {volume["maxHeight"]})').replace('0.55 * 40', '0.65 * 40')
            v = v.replace('Lerp(power, 0.35, 0.4), 0.3, Lerp(power, 0.4, 0.42), Lerp(power, 2, 7)', 'Lerp(power, 0.42, 0.45), 0.38, Lerp(power, 0.45, 0.5), Lerp(power, 1, 5)')
            # Separate material objects: each aircraft has its own runtime constants.
            v = v.replace('CreateMaterial("dae_wt_sukhoi_volume_v1"', f'CreateMaterial("dae_wt_{name}_volume_v1"')
            (runtime / 'volume.lua').write_text(v)
            n = volume['NozzleFlames']
            e = (source / 'exhaust.lua').read_text().replace('MiG-specific', 'Sukhoi-specific')
            e = e.replace('dae_wt_nozzle_v5', 'dae_wt_sukhoi_nozzle_v1').replace('for layer = 0, 5 do', 'for layer = 0, 7 do')
            e = e.replace('(-12 + layer * 8)', f'({n["startOffset"] * 40:.4f} + layer * {n["endOffsetAddition"] * 40 / 7:.4f})')
            e = e.replace('-- WT startOffset=-0.3m; first ring is inside, never camera-facing.', '-- Native Sukhoi layer start/end offsets, never camera-facing.')
            # SU-30's closely overlapping layers need lower Source LDR exposure.
            if name == 'su_30sm2':
                e = e.replace('nozzle:SetFloat("$c0_w", 0.10)', 'nozzle:SetFloat("$c0_w", 0.065)')
            (runtime / 'exhaust.lua').write_text(e)
            entities = addon / 'lua/entities'
            entities.mkdir(exist_ok=True)
            (entities / ('wt_' + name + '.lua')).write_text(lua, encoding='utf-8')
            (addon / 'addon.json').write_text(json.dumps({'title': '[Glide experimental] ' + name, 'type': 'vehicle', 'tags': ['fun'], 'ignore': []}))
            for dest in (addon / 'shaders/fxc', game / 'shaders/fxc'):
                dest.mkdir(parents=True, exist_ok=True)
                for shader in shaders:
                    shutil.copy2(source / 'shaders/fxc' / (shader + '.vcs'), dest)
            print('INSTALLED', addon)


if __name__ == '__main__':
    install(*sys.argv[1:])
