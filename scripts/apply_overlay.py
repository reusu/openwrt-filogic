#!/usr/bin/env python3
"""Synchronize overlay-owned files and case labels while preserving upstream boards."""
import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

BASE_DEVICES = {'edgepi_e87n', 'hiveton_h5s-te42', 'hiveton_h5s-te43'}
ALLOWED_DEVICES = BASE_DEVICES | {'tenda_be12-pro'}
OWNED_PATTERNS = {name.replace('_', ',', 1) for name in ALLOWED_DEVICES}
ALLOWED_HELPERS = {'Build/tenda-mkdualimageheader'}
MTK = Path('target/linux/mediatek')
BASE = MTK / 'filogic/base-files'
ARMS = (
    ('network', BASE / 'etc/board.d/02_network', 'mediatek_setup_interfaces'),
    ('do_upgrade', BASE / 'lib/upgrade/platform.sh', 'platform_do_upgrade'),
    ('check_image', BASE / 'lib/upgrade/platform.sh', 'platform_check_image'),
    ('copy_config', BASE / 'lib/upgrade/platform.sh', 'platform_copy_config'),
    ('wifimac', BASE / 'etc/hotplug.d/ieee80211/11_fix_wifi_mac', None),
)
PACKAGE = Path('package/kernel/te43-modem-audio')
OBSOLETE_PATCH = MTK / 'patches-6.12/865-asoc-mt7986-te43-modem-pcm.patch'
RECIPE_BEGIN = '# BEGIN openwrt-filogic owned recipes'
RECIPE_END = '# END openwrt-filogic owned recipes'
LEGACY_H5000_DTS_SHA = '569f5d2bdfa0729fb6ff4fa68cded1b005ae701971cc57767f6dabcfeb300d26'
LEGACY_H5000_RECIPE_SHA = '471de4d445075c9d535a07bc43555d34d50317def3bb1cc1a2f46dca48abf72f'


class OverlayError(Exception):
    pass


def legacy_error(detail):
    raise OverlayError(
        f'legacy custom H5000M detected ({detail}). Start from a fresh OpenWrt '
        '25.12.6 source tree, then apply this overlay. Upstream H5000M cannot be '
        'safely reconstructed from an overwritten tree.'
    )


def definitions(text):
    lines, result, index = text.splitlines(keepends=True), [], 0
    while index < len(lines):
        match = re.fullmatch(r'\s*define ((?:Device|Build)/[^\s]+)\s*', lines[index])
        if not match:
            index += 1
            continue
        start, depth = index, 1
        index += 1
        while index < len(lines) and depth:
            if re.match(r'\s*define\s', lines[index]): depth += 1
            if re.fullmatch(r'\s*endef\s*', lines[index]): depth -= 1
            index += 1
        if depth: raise OverlayError(f'unclosed {match[1]} definition')
        result.append((match[1], start, index, ''.join(lines[start:index])))
    return result


def remove_definitions(text, names, devices):
    lines = text.splitlines(keepends=True)
    removed = set()
    for name, start, end, _ in definitions(text):
        if name in names: removed.update(range(start, end))
    output = []
    for index, line in enumerate(lines):
        if index in removed: continue
        match = re.fullmatch(r'(\s*TARGET_DEVICES\s*\+=\s*)([^#\n]*)([^\n]*)(\n?)', line)
        if match and set(match[2].split()) & devices:
            keep = [token for token in match[2].split() if token not in devices]
            if keep: output.append(match[1] + ' '.join(keep) + (' ' if match[3] else '') + match[3] + match[4])
            elif match[3]: output.append(match[3] + match[4])
        else: output.append(line)
    return ''.join(output)


def remove_markers(text, begin, end):
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.strip() == begin]
    ends = [i for i, line in enumerate(lines) if line.strip() == end]
    if len(starts) != len(ends) or len(starts) > 1 or (starts and starts[0] >= ends[0]):
        raise OverlayError(f'malformed overlay markers: {begin}')
    return ''.join(line for i, line in enumerate(lines) if i not in starts + ends)


@dataclass
class Arm:
    start: int
    header_end: int
    end: int
    patterns: list
    indent: str


CASE_OPEN = re.compile(r'^\s*case\s+.+\s+in\s*(?:#.*)?$')
CASE_CLOSE = re.compile(r'^\s*esac(?:\s*;)?\s*(?:#.*)?$')
ARM_END = re.compile(r'^\s*(?:;;|;&|;;&)\s*(?:#.*)?$')


def target_case(text, function):
    lines = text.splitlines(keepends=True)
    start, stop = 0, len(lines)
    if function:
        pattern = re.compile(r'^\s*' + re.escape(function) + r'\s*\(\s*\)\s*(?:\{\s*)?$')
        matches = [i for i, line in enumerate(lines) if pattern.fullmatch(line.rstrip('\n'))]
        if len(matches) != 1:
            raise OverlayError(f'expected one function anchor {function}(), found {len(matches)}')
        start = matches[0] + 1
        stop = next((i for i in range(start, len(lines)) if re.fullmatch(r'}\s*', lines[i])), len(lines))
    opening = next((i for i in range(start, stop) if CASE_OPEN.fullmatch(lines[i].rstrip('\n'))), None)
    if opening is None: raise OverlayError(f'case anchor missing in {function or "top-level script"}')
    depth, closing = 1, None
    for i in range(opening + 1, stop):
        line = lines[i].rstrip('\n')
        if CASE_OPEN.fullmatch(line): depth += 1
        elif CASE_CLOSE.fullmatch(line):
            depth -= 1
            if not depth:
                closing = i
                break
    if closing is None: raise OverlayError(f'unclosed case in {function or "top-level script"}')
    return lines, opening, closing


def case_arms(lines, opening, closing):
    arms, index = [], opening + 1
    while index < closing:
        if not lines[index].strip() or lines[index].lstrip().startswith('#'):
            index += 1
            continue
        start, header = index, []
        while index < closing:
            line = lines[index].strip()
            header.append(line)
            index += 1
            if line.endswith(')'): break
        else: raise OverlayError("case pattern header is not terminated by ')'")
        joined = ''.join(header).replace('\\', '')[:-1].lstrip('(')
        patterns = [value.strip() for value in joined.split('|')]
        if any(not value or re.search(r'\s', value) for value in patterns):
            raise OverlayError(f'unsupported case pattern header: {joined!r}')
        header_end, depth = index, 0
        while index < closing:
            line = lines[index].rstrip('\n')
            if CASE_OPEN.fullmatch(line): depth += 1
            elif CASE_CLOSE.fullmatch(line): depth -= 1
            if depth < 0: raise OverlayError('unbalanced nested case')
            index += 1
            if not depth and ARM_END.fullmatch(line): break
        else: raise OverlayError(f'case arm lacks terminator: {patterns}')
        arms.append(Arm(start, header_end, index, patterns, re.match(r'\s*', lines[start])[0]))
    return arms


def sync_arm(text, function, name, replacement):
    begin, end = f'# BEGIN openwrt-filogic {name}', f'# END openwrt-filogic {name}'
    text = remove_markers(text, begin, end)
    lines, opening, closing = target_case(text, function)
    arms = case_arms(lines, opening, closing)
    for arm in arms:
        if 'hiveton,h5000m' in arm.patterns and OWNED_PATTERNS.intersection(arm.patterns):
            legacy_error(f'custom H5000M case arm in {name}')
    # An old arm may share a body with another board: retain that board and body.
    for arm in reversed(arms):
        if not OWNED_PATTERNS.intersection(arm.patterns): continue
        keep = [value for value in arm.patterns if value not in OWNED_PATTERNS]
        if keep:
            lines[arm.start:arm.header_end] = [
                arm.indent + value + ('|\\\n' if i < len(keep) - 1 else ')\n')
                for i, value in enumerate(keep)]
        else: del lines[arm.start:arm.end]
    lines[opening + 1:opening + 1] = [f'\t{begin}\n', replacement.rstrip('\n') + '\n', f'\t{end}\n']
    return ''.join(lines)


def regular_file(path):
    if path.is_symlink() or not path.is_file():
        raise OverlayError(f'required regular file missing or symlinked: {path}')
    return path.read_bytes()


def legacy_check(root, text):
    blocks = [body for name, _, _, body in definitions(text) if name == 'Device/hiveton_h5000m']
    if len(blocks) > 1: legacy_error('duplicate H5000M recipes')
    for body in blocks:
        if hashlib.sha256(' '.join(body.split()).encode()).hexdigest() == LEGACY_H5000_RECIPE_SHA:
            legacy_error('old overlay H5000M recipe')
    dts = root / MTK / 'dts/mt7987a-hiveton-h5000m.dts'
    if dts.exists():
        data = regular_file(dts)
        if hashlib.sha256(data).hexdigest() == LEGACY_H5000_DTS_SHA or (
                b'Reusu <admin@yumao.name>' in data and b'hiveton,h5000m' in data):
            legacy_error('old overlay H5000M DTS')


def plan_overlay(root, overlay):
    if not (root / MTK / 'dts').is_dir():
        raise OverlayError(f'{root} is not an OpenWrt source tree (missing {MTK}/dts)')
    image = MTK / 'image/filogic.mk'
    texts = {path: regular_file(root / path).decode() for path in {image, *(item[1] for item in ARMS)}}
    legacy_check(root, texts[image])
    recipes = regular_file(overlay / 'files/filogic-devices.mk').decode()
    blocks = definitions(recipes)
    devices = [name.removeprefix('Device/') for name, _, _, _ in blocks if name.startswith('Device/')]
    helpers = [name for name, _, _, _ in blocks if name.startswith('Build/')]
    if not BASE_DEVICES <= set(devices) <= ALLOWED_DEVICES or len(devices) != len(set(devices)):
        raise OverlayError('overlay recipes must define E87N, H5S TE-42, H5S TE-43 and optionally Tenda BE12 Pro exactly once')
    if not set(helpers) <= ALLOWED_HELPERS or len(helpers) != len(set(helpers)):
        raise OverlayError('unsupported or duplicate overlay build helper')
    filenames = []
    for name, _, _, body in blocks:
        if not name.startswith('Device/'): continue
        device = name.removeprefix('Device/')
        if len(re.findall(r'^TARGET_DEVICES\s*\+=\s*' + re.escape(device) + r'\s*$', recipes, re.M)) != 1:
            raise OverlayError(f'overlay recipe lacks one TARGET_DEVICES entry: {device}')
        dts = re.findall(r'^\s*DEVICE_DTS\s*:=\s*([\w.-]+)\s*$', body, re.M)
        if len(dts) != 1: raise OverlayError(f'expected one literal DEVICE_DTS for {device}')
        filenames.append(dts[0] + '.dts')
    base = remove_markers(texts[image], RECIPE_BEGIN, RECIPE_END)
    removed_devices = ALLOWED_DEVICES | {'netgear_eax17'}
    base = remove_definitions(base, {'Device/' + name for name in removed_devices} | ALLOWED_HELPERS, removed_devices)
    texts[image] = base.rstrip('\n') + '\n\n' + RECIPE_BEGIN + '\n' + recipes.strip('\n') + '\n' + RECIPE_END + '\n'
    for name, path, function in ARMS:
        replacement = regular_file(overlay / 'files/arms' / name).decode()
        wrapped = 'case "$board" in\n' + replacement.rstrip('\n') + '\nesac\n'
        lines, opening, closing = target_case(wrapped, None)
        arms = case_arms(lines, opening, closing)
        required = {device.replace('_', ',', 1) for device in (devices if name == 'network' else BASE_DEVICES)}
        if name == 'wifimac': required.discard('edgepi,e87n')
        supplied = [pattern for arm in arms for pattern in arm.patterns]
        if set(supplied) != required or len(supplied) != len(required):
            raise OverlayError(f'overlay {name} arm must contain exactly {sorted(required)}')
        texts[path] = sync_arm(texts[path], function, name, replacement)
    writes = {path: (content.encode(), stat.S_IMODE((root / path).stat().st_mode)) for path, content in texts.items()}
    for filename in filenames:
        source = overlay / 'files/dts' / filename
        writes[MTK / 'dts' / filename] = (regular_file(source), stat.S_IMODE(source.stat().st_mode))
    package_source = overlay / 'files/packages/te43-modem-audio'
    regular_file(package_source / 'Makefile')
    for source in package_source.rglob('*'):
        if source.is_symlink(): raise OverlayError(f'package source symlink unsupported: {source}')
        if source.is_file():
            writes[PACKAGE / source.relative_to(package_source)] = (source.read_bytes(), stat.S_IMODE(source.stat().st_mode))
    deletes = {OBSOLETE_PATCH} if (root / OBSOLETE_PATCH).exists() else set()
    package_target = root / PACKAGE
    if package_target.exists():
        if package_target.is_symlink() or not package_target.is_dir():
            raise OverlayError(f'owned package path is not a directory: {package_target}')
        for target in package_target.rglob('*'):
            if target.is_symlink(): raise OverlayError(f'owned package target symlink unsupported: {target}')
            if target.is_file() and target.relative_to(root) not in writes:
                deletes.add(target.relative_to(root))
    for path in set(writes) | deletes:
        target = root / path
        for ancestor in (target, *target.parents):
            if ancestor == root: break
            if ancestor.is_symlink(): raise OverlayError(f'target path traverses symlink: {ancestor}')
        if target.exists() and not target.is_file(): raise OverlayError(f'target is not a regular file: {target}')
    return writes, deletes


def atomic_write(path, data, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.filogic-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output: output.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def apply_overlay(root, overlay):
    root, overlay = Path(root).resolve(), Path(overlay).resolve()
    writes, deletes = plan_overlay(root, overlay)
    changed = {path: item for path, item in writes.items() if not (root / path).exists() or
               ((root / path).read_bytes(), stat.S_IMODE((root / path).stat().st_mode)) != item}
    paths = set(changed) | deletes
    backups = {path: ((root / path).read_bytes(), stat.S_IMODE((root / path).stat().st_mode))
               if (root / path).exists() else None for path in paths}
    new_dirs = {parent for path in changed for parent in (root / path).parents
                if parent != root and root in parent.parents and not parent.exists()}
    try:
        for path, (data, mode) in changed.items(): atomic_write(root / path, data, mode)
        for path in deletes: (root / path).unlink()
    except OSError as error:
        for path, previous in backups.items():
            if previous is None: (root / path).unlink(missing_ok=True)
            else: atomic_write(root / path, *previous)
        for path in sorted(new_dirs, key=lambda p: len(p.parts), reverse=True):
            if path.exists(): path.rmdir()
        raise OverlayError(f'apply failed; original files restored: {error}') from error
    package = root / PACKAGE
    if package.exists():
        for directory in sorted((p for p in package.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            if not any(directory.iterdir()): directory.rmdir()
    return len(changed), len(deletes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?', default='.')
    args = parser.parse_args()
    try: changed, removed = apply_overlay(args.source, Path(__file__).resolve().parents[1])
    except (OverlayError, OSError, UnicodeError) as error:
        print(f'apply.sh: {error}', file=sys.stderr)
        return 1
    print(f'Overlay applied: {changed} files updated, {removed} stale files removed; upstream H5000M preserved.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
