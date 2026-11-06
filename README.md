# openwrt-filogic

Device support overlays and a shared OpenWrt build for MediaTek Filogic boards.
The default release is **25.12.6**. This repository combines the TE/Hiveton,
EdgePi and Tenda overlay sources; it starts with a new history and retains
source copyright and license notices.

| Device | Compatible | Storage / image |
| --- | --- | --- |
| Hiveton H5S TE-42 | `hiveton,h5s-te42` | eMMC sysupgrade |
| Hiveton H5S TE-43 | `hiveton,h5s-te43` | eMMC sysupgrade; MCU companion and modem audio |
| EdgePi E87N | `edgepi,e87n` | eMMC sysupgrade |
| Tenda BE12 Pro | `tenda,be12-pro` | SPI-NAND; God1 wrapper and initramfs |

H5000M is supported by upstream OpenWrt 25.12.6. This overlay does not replace
its DTS, device recipe or board cases, and does not select it in this build.
Use a fresh official OpenWrt tree when moving from the retired H5000M overlay.

## Build

Actions → **Build Filogic devices + ImageBuilder** → **Run workflow**, with
`tag=25.12.6` (without `v`). A push changing overlay/build sources also builds
25.12.6. Artifacts contain the four devices' sysupgrade images, available
initramfs images, ImageBuilder, build information and checksums. This does not
flash any device or publish a GitHub Release.

The workflow seeds the official Filogic configuration, disables stock device
profiles and explicitly selects these four profiles. Board-specific upgrade
paths remain distinct: the Tenda NAND target does not receive the eMMC upgrade
or generated-MAC scripts used by the Hiveton boards.

```sh
git clone --branch v25.12.6 --depth 1 https://github.com/openwrt/openwrt.git openwrt-25.12.6
./apply.sh openwrt-25.12.6
cd openwrt-25.12.6
./scripts/feeds update -a
./scripts/feeds install -a
make menuconfig
make -j"$(nproc)"
```

`apply.sh` requires Python 3 and synchronizes the owned DTS, image recipes,
board-case entries and modem-audio package. Reapplying updates changed owned
entries without duplicating them or overwriting other upstream devices.
The existing Netgear EAX17 image-recipe exclusion is retained for the all-profile
build. The helper validates injection anchors before modifying source files.

## Validation and hardware notes

```sh
python3 -m unittest discover -s tests -v
sh -n apply.sh
```

DTS preprocessing and `dtc` checks use the exact 25.12.6 source and Linux
6.12.112 bindings. Full firmware and external audio modules are built by CI.
A compiled image is not evidence that every untested board peripheral works.

- [TE43 connections, ownership and PCM configuration](docs/te43.md)
- [Tenda hardware, MAC addresses and installation](docs/tenda-be12-pro.md)
- [Source attribution](docs/sources.md)

The TE43 CH585M owns its LCD, touch, NFC, charger/BMS and both AW9523 expanders.
They are not invented Linux I2C children or GPIO regulators. Its USB 5V and 5G
power rails require the MCU firmware and valid external hardware. GPIO/pin
mappings were checked against the live TE43 EDA project; hardware defects found
in that review still need circuit changes and board validation.

## Layout

```text
apply.sh                 overlay entry point
scripts/                 overlay synchronization helpers
files/dts/               four device trees
files/filogic-devices.mk  owned image definitions and Tenda wrapper
files/arms/              board setup and upgrade cases
files/packages/          standalone TE43 modem audio modules
tests/                   overlay regression tests
.github/workflows/       shared release build
```
