"""Apply a UserSkin to an already staged, split SU-30SM2 export.
Usage: python import_sukhoi_skin.py <garrysmod> <WarThunder> <VTFCmd.exe> <export-dir> <skin.zip>
The GUI uses the same importer; this utility preserves the experiment's split skeleton.
"""
from pathlib import Path
from datetime import datetime
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src/dae'))
from split_sukhoi import split
from util.wtskins import importSkins
from util.assetcacher import AssetCacher
from parse.gameres import GameResourcePack, GameResDesc
from parse.realres import DynModel, GeomNodeTree, CollisionGeom
from parse.material import DDSxTexturePack2, TexturePathDict


def install(game, wt, converter, export, archive):
    game, wt, export = Path(game), Path(wt), Path(export)
    name = 'su_30sm2'
    addon = game / 'addons/wt_su_30sm2'
    original = export / (name + '.qc')
    if not original.is_file() or not addon.is_dir():
        raise ValueError('Stage and install the split SU-30SM2 first')
    backup = Path(tempfile.gettempdir()) / 'wtp/backups' / ('su30_skin_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    shutil.copytree(addon, backup / 'addon')
    shutil.copy2(original, backup / original.name)
    print('BACKUP', backup, flush=True)
    resources = wt / 'content/base/res'
    desc = GameResDesc(str(resources / 'dynModelDesc.bin'))
    desc.loadDataBlock()
    AssetCacher.appendGameResDesc(desc)
    assets = GameResourcePack(str(resources / 'aircrafts/air.grp')).getPackedFiles()
    for asset in assets:
        if isinstance(asset, (DynModel, GeomNodeTree, CollisionGeom)):
            AssetCacher.cacheAsset(asset)
    dyn = next(a for a in assets if isinstance(a, DynModel) and a.name == name)
    dyn.computeData()
    model = dyn.getModel(0)
    wanted = {t.split('*')[0] for t in dyn.textures}
    for file in resources.rglob('*.dxp.bin'):
        for tex in DDSxTexturePack2(str(file)).getPackedFiles():
            if tex.name in wanted:
                AssetCacher.cacheAsset(tex)
    qc = export / (name + '_skins.qc')
    qc.write_text(original.read_text())
    report = importSkins(qc, model.materials, TexturePathDict('wt_glide'), [archive], converter)
    split_dir = split(qc)
    for part in ('body', 'nozzles'):
        with (backup / (part + '_compile.log')).open('w') as log:
            subprocess.run([str(game.parent / 'bin/studiomdl.exe'), '-nop4', '-game', str(game), str(split_dir / (part + '.qc'))], stdout=log, stderr=subprocess.STDOUT, check=True)
    for suffix in ('', '_nozzles'):
        for file in (game / 'models/wt_glide').glob(name + suffix + '.*'):
            for target in (addon, export / 'source_export'):
                shutil.copy2(file, target / 'models/wt_glide' / file.name)
    shutil.copytree(export / 'source_export/materials', addon / 'materials', dirs_exist_ok=True)
    shutil.copy2(export / 'source_export/skins.json', addon / 'skins.json')
    print('INSTALLED_SKINS', report, flush=True)


if __name__ == '__main__':
    install(*sys.argv[1:])
