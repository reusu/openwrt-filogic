"""Overlay synchronization must preserve upstream boards and fail before mutation."""
import importlib.util
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/apply_overlay.py'
spec = importlib.util.spec_from_file_location('apply_overlay', SCRIPT)
apply = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = apply
spec.loader.exec_module(apply)

H5000_RECIPE = '''define Device/hiveton_h5000m
  DEVICE_VENDOR := Hiveton
  DEVICE_MODEL := H5000M
  DEVICE_ALT0_VENDOR := Airpi
  DEVICE_ALT0_MODEL := H5000M
  DEVICE_DTS := mt7987a-hiveton-h5000m
  DEVICE_DTS_DIR := ../dts
  DEVICE_PACKAGES := kmod-hwmon-pwmfan kmod-usb3 mt7987-2p5g-phy-firmware \\
\tkmod-mt7996e kmod-mt7992-23-firmware f2fsck mkf2fs
  KERNEL_LOADADDR := 0x40000000
  IMAGE/sysupgrade.bin := sysupgrade-tar | append-metadata
endef
TARGET_DEVICES += hiveton_h5000m
'''
H5000_DTS = b'// upstream H5000M\n/dts-v1/;\n/ { compatible = "hiveton,h5000m"; };\n'
NETWORK_OFFICIAL = '''\tupstream,first|\\
\thiveton,h5000m|\\
\tupstream,last)
\t\tucidef_set_interfaces_lan_wan eth0 eth1
\t\t;;
'''
PLATFORM_OFFICIAL = '''\thiveton,h5000m|\\
\tupstream,emmc)
\t\tupstream_emmc "$1"
\t\t;;
'''
WIFI_OFFICIAL = '''\thiveton,h5000m)
\t\tupstream_h5000_wifi
\t\t;;
'''


def write(path, text, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode() if isinstance(text, str) else text)
    path.chmod(mode)


def recipe(name):
    return (f'define Device/{name}\n  DEVICE_DTS := mt7987a-{name.replace("_", "-")}\n'
            f'  DEVICE_MODEL := {name}\nendef\nTARGET_DEVICES += {name}\n')


def arm(patterns, body):
    return ''.join('\t' + name + ('|\\\n' if i < len(patterns) - 1 else ')\n')
                   for i, name in enumerate(patterns)) + '\t\t' + body + '\n\t\t;;\n'


def tree_state(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
            for p in root.rglob('*') if p.is_file()}


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='overlay-unit-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'openwrt'
        self.overlay = Path(self.temp.name) / 'overlay'
        self.image = self.root / apply.MTK / 'image/filogic.mk'
        write(self.image, '# upstream recipes\n' + H5000_RECIPE + '\n' + recipe('netgear_eax17') + '\n' + recipe('upstream_keep'))
        write(self.root / apply.MTK / 'dts/mt7987a-hiveton-h5000m.dts', H5000_DTS)
        write(self.root / apply.MTK / 'dts/upstream-keep.dts', b'keep me\n')
        write(self.root / apply.BASE / 'etc/board.d/02_network',
              'mediatek_setup_interfaces() {\n\tcase "$board" in\n' + NETWORK_OFFICIAL + '\tesac\n}\n'
              'mediatek_setup_macs() {\n\tcase "$board" in\n' + WIFI_OFFICIAL + '\tesac\n}\n', 0o755)
        write(self.root / apply.BASE / 'lib/upgrade/platform.sh', ''.join(
            f'{function}() {{\n\tcase "$board" in\n' + PLATFORM_OFFICIAL + '\tesac\n}\n'
            for function in ['platform_do_upgrade', 'platform_check_image', 'platform_copy_config']), 0o755)
        write(self.root / apply.BASE / 'etc/hotplug.d/ieee80211/11_fix_wifi_mac',
              '#!/bin/sh\ncase "$board" in\n' + WIFI_OFFICIAL + 'esac\n', 0o755)
        self.make_overlay()

    def make_overlay(self, tenda=True):
        names = sorted(apply.BASE_DEVICES) + (['tenda_be12-pro'] if tenda else [])
        helper = 'define Build/tenda-mkdualimageheader\n\techo new-header\nendef\n' if tenda else ''
        write(self.overlay / 'files/filogic-devices.mk', helper + '\n'.join(recipe(name) for name in names))
        for name in names:
            write(self.overlay / 'files/dts' / ('mt7987a-' + name.replace('_', '-') + '.dts'), f'// {name} new DTS\n')
        for name, _, _ in apply.ARMS:
            patterns = sorted(device.replace('_', ',', 1) for device in apply.BASE_DEVICES)
            if name == 'wifimac': patterns.remove('edgepi,e87n')
            value = arm(patterns, f'new_{name} "$1"')
            if name == 'network' and tenda: value += arm(['tenda,be12-pro'], 'tenda_switch_ports')
            write(self.overlay / 'files/arms' / name, value)
        write(self.overlay / 'files/packages/te43-modem-audio/Makefile', 'new package\n')
        write(self.overlay / 'files/packages/te43-modem-audio/src/current.c', 'new driver\n')

    def run_apply(self):
        return apply.apply_overlay(self.root, self.overlay)

    def assert_upstream(self):
        self.assertEqual((self.root / apply.MTK / 'dts/mt7987a-hiveton-h5000m.dts').read_bytes(), H5000_DTS)
        self.assertIn(H5000_RECIPE, self.image.read_text())
        self.assertIn(NETWORK_OFFICIAL, (self.root / apply.BASE / 'etc/board.d/02_network').read_text())
        self.assertIn(WIFI_OFFICIAL, (self.root / apply.BASE / 'etc/board.d/02_network').read_text())
        self.assertEqual((self.root / apply.BASE / 'lib/upgrade/platform.sh').read_text().count(PLATFORM_OFFICIAL), 3)
        self.assertIn(WIFI_OFFICIAL, (self.root / apply.BASE / 'etc/hotplug.d/ieee80211/11_fix_wifi_mac').read_text())

    def test_fresh_four_devices_preserve_official_h5000(self):
        self.run_apply()
        self.assert_upstream()
        text = self.image.read_text()
        for name in apply.ALLOWED_DEVICES:
            self.assertEqual(text.count('define Device/' + name + '\n'), 1)
            self.assertEqual(text.count('TARGET_DEVICES += ' + name + '\n'), 1)
        self.assertNotIn('netgear_eax17', text)
        self.assertIn('define Device/upstream_keep\n', text)
        self.assertEqual(text.count('define Build/tenda-mkdualimageheader\n'), 1)
        self.assertIn('tenda,be12-pro)', (self.root / apply.BASE / 'etc/board.d/02_network').read_text())
        for _, path, _ in apply.ARMS:
            if path.name != '02_network': self.assertNotIn('tenda,be12-pro', (self.root / path).read_text())

    def test_second_apply_is_byte_identical(self):
        self.run_apply()
        first = tree_state(self.root)
        self.assertEqual(self.run_apply(), (0, 0))
        self.assertEqual(first, tree_state(self.root))

    def test_reapply_refreshes_all_owned_parts_and_removes_stale_package(self):
        self.run_apply()
        write(self.root / apply.PACKAGE / 'src/obsolete.c', 'old removed driver')
        write(self.root / apply.PACKAGE / 'old/nested/stale.h', 'stale header')
        write(self.root / apply.OBSOLETE_PATCH, 'obsolete kernel patch')
        write(self.overlay / 'files/packages/te43-modem-audio/src/current.c', 'replacement driver\n')
        path = self.overlay / 'files/filogic-devices.mk'
        write(path, path.read_text().replace('new-header', 'updated-header').replace('DEVICE_MODEL :=', 'DEVICE_TITLE :='))
        for name, _, _ in apply.ARMS:
            source = self.overlay / 'files/arms' / name
            write(source, source.read_text().replace('new_' + name, 'updated_' + name))
        self.run_apply()
        self.assert_upstream()
        self.assertNotIn('obsolete.c', str(tree_state(self.root)))
        self.assertFalse((self.root / apply.PACKAGE / 'old').exists())
        self.assertFalse((self.root / apply.OBSOLETE_PATCH).exists())
        self.assertEqual((self.root / apply.PACKAGE / 'src/current.c').read_text(), 'replacement driver\n')
        self.assertIn('updated-header', self.image.read_text())
        for name, path, _ in apply.ARMS:
            self.assertIn('updated_' + name, (self.root / path).read_text())
            self.assertNotIn('new_' + name, (self.root / path).read_text())

    def test_missing_and_unmarked_stale_arms_are_synchronized(self):
        self.run_apply()
        name, path, _ = apply.ARMS[1]
        content = (self.root / path).read_text()
        content = re.sub(r'\t# BEGIN openwrt-filogic do_upgrade\n.*?\t# END openwrt-filogic do_upgrade\n', '', content, flags=re.S)
        write(self.root / path, content)
        network = self.root / apply.ARMS[0][1]
        content = network.read_text().replace('case "$board" in\n',
            'case "$board" in\n' + arm(['edgepi,e87n', 'vendor,unowned'], 'old_shared_body'), 1)
        write(network, content)
        self.run_apply()
        self.assertIn('new_do_upgrade', (self.root / path).read_text())
        self.assertIn(arm(['vendor,unowned'], 'old_shared_body'), network.read_text())
        self.assertEqual(network.read_text().count('edgepi,e87n'), 1)
        self.assert_upstream()

    def test_existing_three_owned_boards_can_gain_tenda(self):
        self.make_overlay(tenda=False)
        self.run_apply()
        self.make_overlay(tenda=True)
        self.run_apply()
        self.assertEqual(self.image.read_text().count('define Device/tenda_be12-pro\n'), 1)
        self.assert_upstream()

    def test_legacy_three_device_overlay_with_custom_h5000_is_refused(self):
        old = H5000_RECIPE.replace('  DEVICE_ALT0_VENDOR := Airpi\n', '').replace('  DEVICE_ALT0_MODEL := H5000M\n', '')
        write(self.image, old + recipe('edgepi_e87n') + recipe('hiveton_h5s-te42'))
        before = tree_state(self.root)
        with self.assertRaisesRegex(apply.OverlayError, 'fresh OpenWrt'):
            self.run_apply()
        self.assertEqual(before, tree_state(self.root))

    def test_legacy_custom_h5000_dts_and_mixed_case_are_refused(self):
        dts = self.root / apply.MTK / 'dts/mt7987a-hiveton-h5000m.dts'
        write(dts, '// Copyright (C) 2026 Reusu <admin@yumao.name>\n/ { compatible="hiveton,h5000m"; };\n')
        before = tree_state(self.root)
        with self.assertRaisesRegex(apply.OverlayError, 'H5000M DTS'): self.run_apply()
        self.assertEqual(before, tree_state(self.root))
        write(dts, H5000_DTS)
        path = self.root / apply.ARMS[0][1]
        write(path, path.read_text().replace('case "$board" in\n',
              'case "$board" in\n' + arm(['hiveton,h5000m', 'edgepi,e87n'], 'legacy_network'), 1))
        before = tree_state(self.root)
        with self.assertRaisesRegex(apply.OverlayError, 'custom H5000M case'): self.run_apply()
        self.assertEqual(before, tree_state(self.root))

    def test_missing_late_anchor_has_no_partial_changes(self):
        path = self.root / apply.ARMS[-1][1]
        write(path, '# upstream changed structure; no case anchor\n')
        before = tree_state(self.root)
        with self.assertRaisesRegex(apply.OverlayError, 'case anchor missing'): self.run_apply()
        self.assertEqual(before, tree_state(self.root))
        self.assertFalse((self.root / 'package').exists())

    def test_missing_dts_preflight_has_no_partial_changes(self):
        (self.overlay / 'files/dts/mt7987a-tenda-be12-pro.dts').unlink()
        before = tree_state(self.root)
        with self.assertRaisesRegex(apply.OverlayError, 'required regular file'): self.run_apply()
        self.assertEqual(before, tree_state(self.root))

    def test_nested_case_in_unrelated_board_is_preserved(self):
        path = self.root / apply.ARMS[0][1]
        nested = '\tother,board)\n\t\tcase "$sub" in\n\t\tfoo)\n\t\t\tkeep\n\t\t\t;;\n\t\tesac\n\t\t;;\n'
        write(path, path.read_text().replace('case "$board" in\n', 'case "$board" in\n' + nested, 1))
        self.run_apply()
        self.assertIn(nested, path.read_text())

    def test_commit_error_restores_original_files(self):
        before = tree_state(self.root)
        original = apply.atomic_write
        count = 0
        def fail_once(*args):
            nonlocal count
            count += 1
            if count == 3: raise OSError('injected disk error')
            return original(*args)
        with patch.object(apply, 'atomic_write', side_effect=fail_once):
            with self.assertRaisesRegex(apply.OverlayError, 'original files restored'): self.run_apply()
        self.assertEqual(before, tree_state(self.root))
        self.assertFalse((self.root / 'package').exists())


if __name__ == '__main__': unittest.main()
