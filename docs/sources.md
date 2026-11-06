# Source attribution

The initial content was consolidated from `reusu/openwrt-hiveton` (base commit
`0002e876b9d7995b854a269949e2317ed84bfbdc`) and `reusu/openwrt-tenda`.
The new repository does not import their Git histories. Original per-file
copyright and SPDX notices remain authoritative; no blanket license change is made.

Tenda BE12 Pro support was originally upstreamed by Chen Minqiang (ptpt52),
with follow-up fixes by Chukun Pan and other OpenWrt contributors:

- [Device support](https://github.com/openwrt/openwrt/commit/7d79346581582fd609513640ccde74b0ca2537cc)
- [Port names and MAC offsets](https://github.com/openwrt/openwrt/commit/348f716408d771b5ff658d4c81141acdd17bff54)
- [DTS compiler fixes](https://github.com/openwrt/openwrt/commit/3158f18538d8c2f9670f3c567a32e54fc43ab409)
- [NVMEM conversion](https://github.com/openwrt/openwrt/commit/53fa04d2619f5ac8d3043c08e1beddf5afa0651e)

Imported Tenda source blobs before the additional 25.12.6 SPI-cell correction:
DTS `368b7366218522d95344eeef03add3be943fb35e`, image recipe
`b43ae5958c7484f67e64c0bd04926409bc093847`, network arm
`f1d1442825f4be8654e570afc26769034edad176`.

The TE43 standalone AFE code derives from Linux v6.12 MediaTek ASoC sources,
with the original notices retained. Hardware pin ownership comes from the
user-supplied TE43 project and live EDA review dated 2026-11-05.
