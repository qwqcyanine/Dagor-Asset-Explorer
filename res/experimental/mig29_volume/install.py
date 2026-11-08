"""Install the experimental renderer into an EXISTING MiG addon; never recompile its model.
Usage: python res/experimental/mig29_volume/install.py <garrysmod> <WarThunder> <VTFCmd.exe>
Compile the referenced HLSL files with ShaderCompile first. Keeps a dated addon backup.
"""
from datetime import datetime
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def patch_entity(text):
    if 'include("wt_mig29_volume/volume.lua")' in text:
        return text
    start = text.index('    local volumeMat = CreateMaterial(')
    end = text.index("    -- shortcut: WT's jet distortion", start)
    text = text[:start] + '    local drawWTVolume = include("wt_mig29_volume/volume.lua")\n\n' + text[end:]
    start = text.index('                volumeMesh = volumeMesh or BuildVolume()')
    end = text.index('                render.SetBlend( 1 )', start) + len('                render.SetBlend( 1 )')
    text = text[:start] + '                drawWTVolume(p0, self:GetAngles(), flame)\n' + text[end:]
    # The volume extends beyond the MDL bounds; avoid culling it off screen.
    marker = '        BaseClass.OnActivateMisc( self )'
    assert text.count(marker) == 1
    text = text.replace(marker, marker + '\n        local mins, maxs = self:GetModelBounds()\n        self:SetRenderBounds(Vector(math.min(mins.x, -600), mins.y, mins.z), maxs)')
    text = 'if SERVER then AddCSLuaFile("wt_mig29_volume/volume.lua") end\n' + text
    assert 'BuildVolume' not in text and 'volumeMesh' not in text
    return text


def patch_exhaust(text):
    if 'include("wt_mig29_volume/exhaust.lua")' in text:
        return text
    start = text.index("    -- shortcut: WT's jet distortion")
    end = text.index('    -- thrust -> p_nozzle', start)
    text = text[:start] + '''    local exhaust = include("wt_mig29_volume/exhaust.lua")

    function ENT:DrawTranslucent()
        if not self.wtGlow or self.wtGlow <= 0 then return end
        for _, f in ipairs(FLAMES) do
            local p0 = self:LocalToWorld(f.pos)
            exhaust.Nozzle(p0, self:GetAngles(), f.radius, self.wtGlow)
            drawWTVolume(p0, self:GetAngles(), self.wtFlameScale or 0)
        end
        -- Capture once after both plumes, so heat cannot erase their light.
        render.UpdateScreenEffectTexture()
        for _, f in ipairs(FLAMES) do
            exhaust.Heat(self:LocalToWorld(f.pos), self:GetAngles(), f.radius, self:GetPower(), self.wtThrust or 0)
        end
    end

''' + text[end:]
    return 'if SERVER then AddCSLuaFile("wt_mig29_volume/exhaust.lua") end\n' + text


def install(game, wt, converter):
    source = Path(__file__).resolve().parent
    game, wt = Path(game), Path(wt)
    addon = game / 'addons/wt_mig_29_9_12'
    entity = addon / 'lua/entities/wt_mig_29_9_12.lua'
    patched = patch_exhaust(patch_entity(entity.read_text(encoding='utf-8')))
    shader_names = ('dae_wt_volume_v2_vs30', 'dae_wt_volume_v6_ps30', 'dae_wt_exhaust_v3_vs30', 'dae_wt_nozzle_v5_ps30', 'dae_wt_heat_v3_ps30')
    binaries = [source / 'shaders/fxc' / (name + '.vcs') for name in shader_names]
    assert all(p.is_file() and p.stat().st_size > 100 for p in binaries), 'Compile shaders first'
    backup = Path(tempfile.gettempdir()) / 'wtp/backups' / ('wt_mig_29_9_12_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    shutil.copytree(addon, backup)
    print('BACKUP', backup)
    sys.path.insert(0, str(source.parents[2] / 'src/dae'))
    from parse.material import DDSxTexturePack2
    from PIL import Image
    pack = DDSxTexturePack2(str(wt / 'content/base/res/fx.dxp.bin'))
    wanted = {'afterburneratlastex', 'afterburnerflamenozzlemask', 'distortion_hot_air_a_tex', 'perlin_noise'}
    images = {t.name: Image.open(BytesIO(t.getDDS())).convert('RGBA') for t in pack.getPackedFiles() if t.name in wanted}
    assert images.keys() == wanted, 'Missing native exhaust texture'
    atlas = images['afterburneratlastex']
    assert atlas.size == (256, 64)
    images['mig29_volume_ramps'] = atlas.crop((0, 16, atlas.width, 20))
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        dest = addon / 'materials/models/wt_glide/fx'
        dest.mkdir(parents=True, exist_ok=True)
        for name, image in images.items():
            image.save(tmp / (name + '.tga'))
            subprocess.run([str(converter), '-file', str(tmp / (name + '.tga')), '-output', str(tmp), '-version', '7.2', '-format', 'RGBA8888', '-alphaformat', 'RGBA8888', '-nomipmaps', '-flag', 'CLAMPS', '-flag', 'CLAMPT'], check=True)
            shutil.copy2(tmp / (name + '.vtf'), dest)
    dest = addon / 'lua/wt_mig29_volume'
    dest.mkdir(parents=True, exist_ok=True)
    for name in ('volume.lua', 'exhaust.lua'):
        shutil.copy2(source / name, dest)
    # MOD path is verified; addon/Workshop-only loading is not yet established.
    for dest in (addon / 'shaders/fxc', game / 'shaders/fxc'):
        dest.mkdir(parents=True, exist_ok=True)
        for binary in binaries:
            shutil.copy2(binary, dest)
    entity.write_text(patched, encoding='utf-8')
    print('INSTALLED', entity)


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    install(*sys.argv[1:])
