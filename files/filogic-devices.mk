
define Device/edgepi_e87n
  DEVICE_VENDOR := EdgePi
  DEVICE_MODEL := E87N
  DEVICE_DTS := mt7987a-edgepi-e87n
  DEVICE_DTS_DIR := ../dts
  DEVICE_PACKAGES := kmod-hwmon-pwmfan kmod-spi-dev kmod-usb3 kmod-nvme mt7987-2p5g-phy-firmware  \
        e2fsprogs f2fsck mkf2fs
  KERNEL_LOADADDR := 0x40080000
  IMAGE/sysupgrade.bin := sysupgrade-tar | append-metadata
endef
TARGET_DEVICES += edgepi_e87n

define Device/hiveton_h5s-te42
  DEVICE_VENDOR := Hiveton
  DEVICE_MODEL := H5S TE-42
  DEVICE_DTS := mt7987a-hiveton-h5s-te42
  DEVICE_DTS_DIR := ../dts
  DEVICE_PACKAGES := kmod-hwmon-pwmfan kmod-i2c-core kmod-spi-dev kmod-usb3 mt7987-2p5g-phy-firmware \
        kmod-mt7996e kmod-mt7992-23-firmware e2fsprogs f2fsck mkf2fs
  KERNEL_LOADADDR := 0x40000000
  IMAGE/sysupgrade.bin := sysupgrade-tar | append-metadata
endef
TARGET_DEVICES += hiveton_h5s-te42

define Device/hiveton_h5s-te43
  DEVICE_VENDOR := Hiveton
  DEVICE_MODEL := H5S TE-43
  DEVICE_DTS := mt7987a-hiveton-h5s-te43
  DEVICE_DTS_DIR := ../dts
  DEVICE_PACKAGES := kmod-hwmon-pwmfan kmod-i2c-core kmod-spi-dev kmod-usb3 \
    kmod-sound-soc-te43-modem alsa-utils \
    mt7987-2p5g-phy-firmware kmod-mt7996e kmod-mt7992-23-firmware \
    kmod-usb-acm kmod-usb-serial-option kmod-usb-net-qmi-wwan \
    kmod-usb-net-cdc-mbim kmod-usb-net-cdc-ncm kmod-usb-net-rndis \
    kmod-mhi-pci-generic kmod-mhi-net kmod-mhi-wwan-ctrl kmod-mhi-wwan-mbim \
    e2fsprogs f2fsck mkf2fs
  KERNEL_LOADADDR := 0x40000000
  IMAGE/sysupgrade.bin := sysupgrade-tar | append-metadata
endef
TARGET_DEVICES += hiveton_h5s-te43

define Build/tenda-mkdualimageheader
	printf '%b' "\x47\x6f\x64\x31\x00\x00\x00\x00" >"$@.new"
	gzip -c "$@" | tail -c8 >>"$@.new"
	cat "$@" >>"$@.new"
	mv "$@.new" "$@"
endef

define Device/tenda_be12-pro
  DEVICE_VENDOR := Tenda
  DEVICE_MODEL := BE12 Pro
  DEVICE_DTS := mt7987a-tenda-be12-pro
  DEVICE_DTS_DIR := ../dts
  DEVICE_PACKAGES := mt7987-2p5g-phy-firmware airoha-en8811h-firmware kmod-phy-airoha-en8811h kmod-mt7992-firmware
  UBINIZE_OPTS := -E 5
  BLOCKSIZE := 128k
  PAGESIZE := 2048
  KERNEL_LOADADDR := 0x40000000
  KERNEL_INITRAMFS := kernel-bin | lzma | \
        fit lzma $$(KDIR)/image-$$(firstword $$(DEVICE_DTS)).dtb with-initrd | pad-to 64k
  IMAGE/sysupgrade.bin := append-kernel | tenda-mkdualimageheader | sysupgrade-tar kernel=$$$$@ | append-metadata
endef
TARGET_DEVICES += tenda_be12-pro
