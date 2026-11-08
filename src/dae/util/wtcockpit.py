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
