"""Check the imported Tenda wrapper against the bootloader's 16-byte format."""
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

OVERLAY = Path(__file__).resolve().parents[1]


class TendaImageTests(unittest.TestCase):
    def test_god1_header_preserves_payload_and_gzip_crc_size(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = bytes(range(256)) * 19 + b'TE43/Tenda merged build\x00\xff'
            (root / 'input.bin').write_bytes(payload)
            (root / 'Makefile').write_text(
                'SHELL := /bin/bash\n'
                f'include {OVERLAY / "files/filogic-devices.mk"}\n'
                'all: output.bin\n'
                'output.bin: input.bin\n'
                '\tcp $< $@\n'
                '\t$(call Build/tenda-mkdualimageheader)\n')
            subprocess.run(['make', '-s', 'all'], cwd=root, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            image = (root / 'output.bin').read_bytes()
            self.assertEqual(image[:8], b'God1\x00\x00\x00\x00')
            self.assertEqual(struct.unpack('<II', image[8:16]),
                             (zlib.crc32(payload), len(payload)))
            self.assertEqual(image[16:], payload)


if __name__ == '__main__':
    unittest.main()
