"""Split rigid aircraft exports at nozzle1/2, preserving animations and skin families."""
from pathlib import Path
import re


def prune_smd(text, keep):
    lines = text.splitlines()
    start = lines.index('nodes') + 1
    end = lines.index('end', start)
    nodes = {int(m[1]): (m[2], int(m[3])) for line in lines[start:end]
             if (m := re.fullmatch(r'(\d+) "([^"]+)" (-?\d+)', line))}
    assert len(nodes) == end - start
    selected = {i for i, (name, _) in nodes.items() if keep(name)}
    for i in list(selected):
        parent = nodes[i][1]
        while parent != -1:
            selected.add(parent)
            parent = nodes[parent][1]
    assert 0 < len(selected) <= 256, len(selected)
    remap = {old: new for new, old in enumerate(sorted(selected))}
    out = lines[:start] + [f'{remap[i]} "{nodes[i][0]}" {remap.get(nodes[i][1], -1)}' for i in sorted(selected)] + ['end']
    mode, triangle_line = '', 0
    for line in lines[end + 1:]:
        if line in ('skeleton', 'triangles', 'end'):
            mode = line
            out.append(line)
        elif mode == 'skeleton' and not line.startswith('time '):
            bone, rest = line.split(' ', 1)
            if int(bone) in remap:
                out.append(f'{remap[int(bone)]} {rest}')
        elif mode == 'triangles':
            if triangle_line % 4:
                fields = line.split()
                assert len(fields) >= 9, fields
                links = int(fields[9]) if len(fields) > 9 else 0
                assert len(fields) == (10 + 2 * links if len(fields) > 9 else 9), fields
                for j in range(10, len(fields), 2):
                    assert int(fields[j]) in remap, 'Weighted mesh crosses component boundary'
                    fields[j] = str(remap[int(fields[j])])
                bone = int(fields[0])
                assert bone in remap or (links and abs(sum(float(fields[j]) for j in range(11, len(fields), 2)) - 1) < 1e-5), 'Mesh belongs in the other component'
                fields[0] = str(remap[bone]) if bone in remap else fields[10]
                line = ' '.join(fields)
            triangle_line += 1
            out.append(line)
        else:
            out.append(line)
    assert triangle_line % 4 == 0
    return '\n'.join(out) + '\n', len(remap)


def split(qc_path):
    qc_path = Path(qc_path).resolve()
    original = qc_path.read_text()
    skin_group = re.search(r'(?ims)^\$texturegroup\s+"[^"]+"\s*\{\s*(?:\{[^{}]*\}\s*)+\}', original)
    skins = skin_group[0] if skin_group else ''
    if skin_group:
        original = original[:skin_group.start()] + original[skin_group.end():]
    dest = qc_path.parent / 'split'
    dest.mkdir(exist_ok=True)
    counts = {}
    is_nozzle = lambda name: name.startswith(('nozzle1_', 'nozzle2_'))
    for component in ('body', 'nozzles'):
        keep = (lambda name: not is_nozzle(name)) if component == 'body' else is_nozzle
        lines = []
        for line in original.splitlines():
            body = re.fullmatch(r'\$body studio "([^"]+)"', line)
            if body and is_nozzle(Path(body[1]).stem) != (component == 'nozzles'):
                continue
            if component == 'nozzles' and line.startswith('$modelname '):
                line = line.replace('.mdl', '_nozzles.mdl')
            # Both QCs retain sequences; nozzle QCs do not need physics.
            if component == 'nozzles' and line.startswith('$collisionmodel '):
                break
            smd = re.search(r'"([^"]+\.smd)"', line)
            if smd:
                rel = Path(component) / smd[1]
                output = dest / rel
                output.parent.mkdir(parents=True, exist_ok=True)
                data, count = prune_smd((qc_path.parent / smd[1]).read_text(), keep)
                output.write_text(data)
                counts[component] = count
                line = line.replace(smd[1], rel.as_posix())
            lines.append(line)
        # Keep identical skin indices even when a component uses only some materials.
        (dest / f'{component}.qc').write_text('\n'.join(lines) + '\n' + skins + '\n')
    print(qc_path.stem, counts, dest)
    return dest
