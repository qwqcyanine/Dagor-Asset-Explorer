"""Deploy parameterized DX9 exhaust shaders and native WT texture inputs."""
from io import BytesIO
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image
from util.misc import getResPath

SHADERS = ('dae_wt_volume_v2_vs30', 'dae_wt_volume_generic_v1_ps30',
           'dae_wt_exhaust_v3_vs30', 'dae_wt_nozzle_generic_v1_ps30', 'dae_wt_heat_v3_ps30')
PARAMETERS = ('ringAngleFadeMult', 'relativeCylinderHeightMin', 'relativeCylinderHeightMax',
              'absorption', 'colorOverRadiusNoiseStrength', 'radiusNoiseStrength',
              'tailHeightFadeMin', 'tailHeightFadeMax', 'minRingCount', 'maxRingCount',
              'minRingOffset', 'maxRingOffset', 'colorOverDepthMult', 'colorOverHeightMult',
              'colorOverRadiusMult', 'colorOverRadiusFadeOverHeight')


def parameterImage(volume):
    """RGB24 fixed point, sampled without filtering/mips/sRGB by the shader."""
    image = Image.new('RGBA', (32, 1), (0, 0, 0, 255))
    for i, key in enumerate(PARAMETERS):
        value = float(volume[key])
        if not math.isfinite(value) or not 0 <= value < 256:
            raise ValueError(f'Unsupported exhaust parameter {key}: {value}')
        packed = round(value / 256 * 255 ** 3)
        image.putpixel((i, 0), (packed // 65025, packed // 255 % 255, packed % 255, 255))
    return image


def exportExhaust(gameRoot, addonDir, className, volume, converter):
    """No silent legacy fallback: missing assets/conversion errors abort this export."""
    from parse.material import DDSxTexturePack2
    source = Path(getResPath('jet_exhaust'))
    binaries = [source / 'shaders/fxc' / (name + '.vcs') for name in SHADERS]
    for binary in binaries:
        if not binary.is_file() or binary.stat().st_size < 100:
            raise FileNotFoundError(f'Exhaust shader missing: {binary}; restore res/jet_exhaust beside the EXE')
    if not converter or not Path(converter).is_file():
        raise FileNotFoundError('WT HLSL exhaust requires a valid VTFCmd executable')
    images = {'volume_parameters': parameterImage(volume)}
    pack = DDSxTexturePack2(str(Path(gameRoot) / 'content/base/res/fx.dxp.bin'))
    wanted = {'afterburneratlastex', 'afterburnerflamenozzlemask', 'distortion_hot_air_a_tex', 'perlin_noise'}
    for texture in pack.getPackedFiles():
        if texture.name in wanted:
            images[texture.name] = Image.open(BytesIO(texture.getDDS())).convert('RGBA')
    missing = wanted - images.keys()
    if missing:
        raise ValueError(f'Missing native exhaust textures: {sorted(missing)}')
    atlas = images['afterburneratlastex']
    row = int(volume['rampTextureOffset']) * 4
    if row < 0 or row + 4 > atlas.height:
        raise ValueError(f'Invalid exhaust ramp row: {row}')
    images['volume_ramps'] = atlas.crop((0, row, atlas.width, row + 4))
    nozzle = volume.get('NozzleFlames')
    if nozzle:
        count = int(nozzle['amountOfFlames'])
        for block, key, maximum in (('FlameMaskTextureOffset', 'maskTextureOffset', 64),
                                     ('FlameRampTextureOffset', 'rampTextureOffset', atlas.height)):
            values = nozzle[block][key]
            if not 0 < count <= 64 or len(values) != count or any(not 0 <= v < maximum for v in values):
                raise ValueError(f'Invalid nozzle {key}: {values}')
    addon = Path(addonDir)
    texturePath = f'models/wt_glide/{className}/exhaust'
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for name, image in images.items():
            image.save(tmp / (name + '.tga'))
            subprocess.run([str(converter), '-file', str(tmp / (name + '.tga')), '-output', str(tmp),
                            '-version', '7.2', '-format', 'RGBA8888', '-alphaformat', 'RGBA8888',
                            '-nomipmaps', '-flag', 'CLAMPS', '-flag', 'CLAMPT'], check=True)
            result = tmp / (name + '.vtf')
            if not result.is_file() or not result.stat().st_size:
                raise RuntimeError(f'VTFCmd did not produce {result.name}')
        target = addon / 'materials' / texturePath
        target.mkdir(parents=True, exist_ok=True)
        for result in tmp.glob('*.vtf'):
            shutil.copy2(result, target)
    runtime = addon / 'lua/wt_jet_exhaust'
    runtime.mkdir(parents=True, exist_ok=True)
    for name in ('volume.lua', 'exhaust.lua'):
        shutil.copy2(source / name, runtime)
    destinations = [addon / 'shaders/fxc']
    # Local MOD deployment is required by the tested GMod loader; Workshop-only is unverified.
    if addon.parent.name == 'addons':
        destinations.append(addon.parent.parent / 'shaders/fxc')
    for dest in destinations:
        dest.mkdir(parents=True, exist_ok=True)
        for binary in binaries:
            shutil.copy2(binary, dest)
    return texturePath


def rendererLua(className, texturePath, volume):
    """Client block; all aircraft-specific values originate in its native configuration."""
    if not texturePath:
        return '''    function ENT:DrawTranslucent( flags )
        self:Draw( flags )
    end
'''
    config = json.dumps(volume, separators=(',', ':'))
    return f'''    local config = util.JSONToTable( [=[{config}]=] )
    local drawWTVolume = include( "wt_jet_exhaust/volume.lua" )( "{className}", config, "{texturePath}" )
    local exhaust = include( "wt_jet_exhaust/exhaust.lua" )( "{className}", config.NozzleFlames, "{texturePath}" )

    function ENT:DrawTranslucent( flags )
        self:Draw( flags )
        local glow = self.wtGlow or 0
        if glow <= 0 or #FLAMES == 0 then return end
        local angles = self:GetAngles()
        local flame = self.wtFlameScale or 0
        for _, f in ipairs( FLAMES ) do
            local origin = self:LocalToWorld( f.pos )
            exhaust.Nozzle( origin, angles, f.radius, glow )
            drawWTVolume( origin, angles, flame )
        end
        render.UpdateScreenEffectTexture()
        for _, f in ipairs( FLAMES ) do
            exhaust.Heat( self:LocalToWorld( f.pos ), angles, f.radius, glow, flame )
        end
    end
'''
