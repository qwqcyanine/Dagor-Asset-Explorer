"""Separate cockpit geometry for first-person rendering; never modifies the airframe."""
import json
import re
from math import isfinite
from pathlib import Path
from util.misc import getResPath


def exportDisplayArtwork(gameRoot, materialsDir):
    """Extract the installed WT instrument faces; keep native alpha, no bundled copies."""
    from io import BytesIO
    from PIL import Image
    from util.vromfs import VROMFS
    archive = VROMFS(str(Path(gameRoot) / 'ui/atlases.vromfs.bin'))
    target = Path(materialsDir) / 'wt_cockpit/instruments'
    target.mkdir(parents=True, exist_ok=True)
    for name in ('mfd_speed', 'mfd_altitude', 'mfd_vario', 'mfd_horizont_mask'):
        with Image.open(BytesIO(archive.read('gameuiskin/' + name + '.avif'))) as image:
            image.convert('RGBA').save(target / (name + '.png'))


def cockpitPack(gameRoot, modelName):
    """Only J-16 has calibrated geometry filtering, eye position and instrument layout."""
    if modelName != 'j_16':
        raise ValueError('Experimental cockpit currently supports J-16 only')
    if not gameRoot:
        raise FileNotFoundError('Experimental cockpit requires installed WT HQ cockpit data (War Thunder root not found)')
    pack = Path(gameRoot) / 'content.hq/pkg_cockpits/res/pkg_cockpits_aircrafts/j_16.grp'
    for required in (pack, pack.parent.parent / 'dynModelDesc.bin',
                     Path(gameRoot) / 'ui/atlases.vromfs.bin'):
        if not required.is_file():
            raise FileNotFoundError(f'Experimental cockpit requires installed WT HQ cockpit data: {required}')
    return pack


def exportCockpit(gameRoot, modelName, output, addonDir, compiler, gameInfo, converter, run):
    """Build in a private compiler game, then collect everything into the normal addon.

    run(argv) is the export action's cancellable, checked subprocess runner.
    No installed game files or standalone test scripts are used as input/output.
    """
    import shutil
    from parse.gameres import GameResourcePack, GameResDesc
    from parse.realres import DynModel, SourceModel
    from parse.material import DDSx, DDSxTexturePack2
    from util.assetcacher import AssetCacher
    from util.a2d import A2D
    from util.vromfs import VROMFS

    root, output, addon = Path(gameRoot), Path(output).resolve(), Path(addonDir)
    pack = cockpitPack(root, modelName)
    for filename in (compiler, gameInfo, converter):
        if not Path(filename).is_file():
            raise FileNotFoundError(filename)
    for filename in (root / 'content/base/res/dynModelDesc.bin', pack.parent.parent / 'dynModelDesc.bin'):
        desc = GameResDesc(str(filename))
        desc.loadDataBlock()
        AssetCacher.appendGameResDesc(desc)
    assets = GameResourcePack(str(pack)).getPackedFiles()
    for asset in assets:
        AssetCacher.cacheAsset(asset)
    dyn = next(a for a in assets if isinstance(a, DynModel) and a.name == modelName + '_cockpit')
    model = dyn.getModel(0)
    keep, report = prepareInterior(model)
    controls = stickPoses(model.skeleton, A2D.fromPack(str(pack), modelName + '_cockpit_anim'))
    head = VROMFS(str(root / 'aces.vromfs.bin')).readBlk(
        'gamedata/flightmodels/' + modelName + '.blk')['cockpit']['headPos']
    wanted = {t.split('*')[0] for m in model.materials for t in m.getTextureSlots() if t}
    if wanted:
        for folder in ('content.hq/hq_tex/res', 'content.hq/pkg_cockpits/res'):
            for filename in (root / folder).rglob('*.dxp.bin'):
                for asset in DDSxTexturePack2(str(filename)).getPackedFiles():
                    if asset.name in wanted and all(
                            c.getPixelCnt() < asset.getPixelCnt()
                            for c in AssetCacher.getCachedAsset(DDSx, asset.name) or ()):
                        AssetCacher.cacheAsset(asset)
        missing = {n for n in wanted if not AssetCacher.getCachedAsset(DDSx, n)}
        if missing:
            for filename in (root / 'content/base/res').rglob('*.dxp.bin'):
                if not missing:
                    break
                for asset in DDSxTexturePack2(str(filename)).getPackedFiles():
                    if asset.name in missing:
                        AssetCacher.cacheAsset(asset)
                        missing.discard(asset.name)
    missing = sorted(n for n in wanted if not AssetCacher.getCachedAsset(DDSx, n))
    if missing:
        raise ValueError('Missing cockpit textures: ' + ', '.join(missing))

    namespace = 'wt_glide/cockpits/' + modelName
    smdl = SourceModel(modelName + '_cockpit', model, keepBones=keep)
    qc, textures = smdl.export(str(output), namespace, False)
    qc = Path(qc)
    qc.write_text(qc.read_text().replace('$opaque\n', ''))
    targets = splitCockpitQC(qc)
    model.exportTextures(str(qc.parent), texturePaths=textures, forceConvert=True)
    materials = qc.parent / 'source_export/materials'
    jobs = []
    for name, spec in textures.getDict().items():
        source = qc.parent / 'textures' / (name + '.dds')
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = materials / spec.texPath
        destination.mkdir(parents=True, exist_ok=True)
        vtf = destination / (name + '.vtf')
        vtf.unlink(missing_ok=True)  # VTFCmd can return zero on failure; reject stale output.
        jobs.append((source, destination, vtf))
    if jobs:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from threading import Event
        stop = Event()

        def convert(job):
            if stop.is_set():
                return
            source, destination, vtf = job
            run([str(converter), '-file', str(source), '-output', str(destination)])
            if not vtf.is_file():
                stop.set()
                raise RuntimeError('VTFCmd did not create cockpit texture: ' + str(vtf))

        if len(jobs) == 1:
            convert(jobs[0])
        else:
            with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as pool:
                futures = [pool.submit(convert, job) for job in jobs]
                try:
                    for future in as_completed(futures):
                        future.result()
                except Exception:
                    stop.set()
                    raise
    exportDisplayArtwork(root, materials)
    # Material flags/tangents must be available before compilation, without polluting GMod.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='cockpit-compile-', dir=output) as folder:
        stage = Path(folder)
        shutil.copytree(materials, stage / 'materials')
        search = Path(gameInfo).resolve().parent.as_posix()
        (stage / 'gameinfo.txt').write_text(
            '"GameInfo" { "game" "DAE cockpit compiler" "FileSystem" { "SteamAppId" "4000" '
            '"SearchPaths" { "Game" "|gameinfo_path|." "Game" "' + search + '" } } }\n')
        for target in targets:
            run([str(compiler), '-nop4', '-game', str(stage), str(target)])
            for suffix in ('.mdl', '.vvd', '.dx90.vtx'):
                if not (stage / 'models' / namespace / (target.stem + suffix)).is_file():
                    raise RuntimeError('Missing compiled cockpit output: ' + target.stem + suffix)
        shutil.copytree(stage / 'models', addon / 'models', dirs_exist_ok=True)
    shutil.copytree(materials, addon / 'materials', dirs_exist_ok=True)
    exterior = ['su_27sm_inside', 'su_30sm_seat', 'j_16_interior', 'j_16_blister',
                'rainbow_coating_05', 'rainbow_light_coating_017', 'dynamic_glass_chrome_017',
                'dynamic_glass_chrome_06']
    return cockpitLua([f'models/{namespace}/{t.stem}.mdl' for t in targets],
                      (head[0] * 40, head[2] * 40, head[1] * 40), report['surfaces'], exterior, controls)


def interiorMaterial(name):
    return ('cockpit' in name or name.startswith(('su_gauge_', 'hud_', 'cn_gauge_', 'j_11b_mfd_')))


def prepareInterior(model):
    """Keep interior objects and their actual bone dependencies, including mixed glass."""
    nodes = {n.idx: n for n in model.skeleton.getNodes()}
    keep = set()
    remove = set()
    surfaces = {}
    displays = []
    for obj in model:
        materials = set(obj.materials.values())
        # Standalone glass/illuminated inserts have no textured interior material.
        selected = any(interiorMaterial(m) for m in materials) or obj.name in {
            'glass_yellow', 'glass_green', 'glass_red', 'glass', 'glass_sight_back',
            'gauges_glass', 'collimator', 'steel_cable',
        }
        if not selected:
            remove.add(obj.name)
            continue
        node = model.skeleton.getNodeByName(obj.name)
        if node:
            keep.add(node.name)
        for face in obj.faces:
            for vertex in face:
                if obj.skinned:
                    for bone, weight in model.skin.get(vertex, ()):
                        if weight > 0:
                            keep.add(nodes[bone].name)
        current = None
        for i, face in enumerate(obj.faces):
            current = obj.materials.get(i, current)
            if current in ('dynamic_mfd', 'dynamic_mirror'):
                display = next((d for d in displays if d['name'] == obj.name and d['material'] == current), None)
                if display is None:
                    display = {'name': obj.name, 'material': current, 'triangles': []}
                    displays.append(display)
                display['triangles'].append([
                    [p[0], p[2], p[1], *model.getUV(vertex)] for vertex in face
                    for p in [model.getVertex(vertex, True, node if not obj.skinned else None)]
                ])
            if current not in ('dynamic_mfd', 'dynamic_mfd_trans'):
                continue
            triangles = surfaces.setdefault(current, [])
            triangles.append([
                [p[0], p[2], p[1]] for vertex in face
                for p in [model.getVertex(vertex, True, node if not obj.skinned else None)]
            ])
    if not keep or 'dynamic_mfd_trans' not in surfaces:
        raise ValueError('Cockpit has no retained interior/HUD geometry')
    reduced, _ = model.skeleton.getReducedBones(keep)
    if len(reduced) > 256:
        raise ValueError(f'Interior still has {len(reduced)} bones; split before compiling')
    surfaces['displays'] = displays
    model.removeObjects(remove)
    return keep, {'bones': len(reduced), 'faces': model.getFaceCount(), 'surfaces': surfaces,
                  'objects': [o.name for o in model]}


def splitCockpitQC(qcPath, maxFaces=180000):
    """Separate dense interior meshes to stay below Source VTX's signed 24-bit offsets."""
    qcPath = Path(qcPath)
    lines = qcPath.read_text().splitlines()
    common, groups, group, count = [], [], [], 0
    for line in lines:
        match = re.fullmatch(r'\$body studio "([^"]+)"', line)
        if not match:
            common.append(line)
            continue
        smd = (qcPath.parent / match[1]).read_text().splitlines()
        start = smd.index('triangles') + 1
        end = smd.index('end', start) if 'end' in smd[start:] else len(smd)
        if (end - start) % 4:
            raise ValueError(f'Incomplete cockpit SMD triangles: {match[1]}')
        faces = (end - start) // 4
        if faces > maxFaces:
            raise ValueError(f'SMD exceeds cockpit mesh budget: {match[1]}')
        if group and count + faces > maxFaces:
            groups.append(group)
            group, count = [], 0
        group.append(line)
        count += faces
    if group:
        groups.append(group)
    if not groups:
        raise ValueError('Cockpit QC has no meshes')
    targets = []
    for index, bodies in enumerate(groups):
        output = qcPath.with_name(f'{qcPath.stem}_{index}.qc')
        header = [re.sub(r'\.mdl"$', f'_{index}.mdl"', line) if line.startswith('$modelname ') else line
                  for line in common]
        output.write_text('\n'.join(header + bodies) + '\n')
        targets.append(output)
    return targets


def stickPoses(skeleton, animation):
    """Native control poses expressed in the exporter's rotation-free reduced skeleton."""
    import re
    from math import degrees
    from util.glide import poseWorld, poseSMD
    names = {'stick_elevator', 'stick_ailerons'}
    if not names.issubset(animation.names):
        raise ValueError('Missing native cockpit stick animation')
    kept = skeleton.getReducedBones(names)[0]
    rest = [[float(v) for v in line.split()[1:]]
            for line in poseSMD(skeleton, kept, poseWorld(skeleton, {}))]
    poses = {name: [] for name in names}
    for step in range(9):
        world = poseWorld(skeleton, animation.sample(animation.duration * step / 8),
                          re.compile(r'stick_(elevator|ailerons)'))
        for node, line, bind in zip(kept, poseSMD(skeleton, kept, world), rest):
            if node.name in names:
                values = [float(v) for v in line.split()[1:]]
                poses[node.name].append(([a - b for a, b in zip(values[:3], bind[:3])],
                                        [degrees(values[4]), degrees(values[5]), degrees(values[3])]))
    return poses


def cockpitLua(modelPath, headPos, surfaces, exteriorMaterials=(), controls=None):
    models = [modelPath] if isinstance(modelPath, str) else modelPath
    if not models or any(not p.startswith('models/') or not p.endswith('.mdl') for p in models):
        raise ValueError('Expected compiled cockpit model paths')
    if len(headPos) != 3 or not all(isfinite(v) for v in headPos):
        raise ValueError('Invalid cockpit eye position')
    if not surfaces.get('dynamic_mfd_trans'):
        raise ValueError('HUD aperture geometry is required')
    template = Path(getResPath('jet_exhaust')) / 'cockpit.lua'
    return '\n' + template.read_text(encoding='utf-8').replace('__COCKPIT_MODEL__', '{' + ', '.join(json.dumps(p) for p in models) + '}').replace(
        '__COCKPIT_EYE__', ', '.join(str(float(v)) for v in headPos)).replace(
        '__COCKPIT_SURFACES__', json.dumps(surfaces)).replace(
        '__COCKPIT_EXTERIOR__', json.dumps(list(exteriorMaterials))).replace(
        '__COCKPIT_CONTROLS__', json.dumps(controls or {})).replace(
        '__COCKPIT_DISPLAYS__', (template.parent / 'cockpit_displays.lua').read_text(encoding='utf-8'))
