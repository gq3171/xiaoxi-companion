# Third-party notices

Project-owned source and bundled project artwork are distributed under the root MIT license. Third-party code, fonts and model data retain their original licenses; the root MIT license does not replace them.

| Component | Origin / license | Included notice |
|---|---|---|
| Noto Sans CJK generated bitmap fonts | Google/Adobe Noto CJK, SIL OFL 1.1 | `firmware/main/fonts/OFL.txt`, `README.md` |
| cJSON native Linux parser | Dave Gamble and contributors, MIT | `computer/vendor/cjson/LICENSE` |
| ESP-DL speaker-verification model derivative | Espressif ESP-DL, MIT | `firmware/models/LICENSE.esp-dl`, `README.md` |
| ESP-SR MultiNet wake model | Espressif ESP-SR model license, subject to its use restrictions | `firmware/models/licenses/esp-sr.txt`, `NAME_WAKE.md` |
| Pinyin-derived name table | pypinyin, MIT | `firmware/models/licenses/pypinyin-MIT.txt` |
| noVNC core (with local patches) | noVNC contributors, MPL 2.0 and per-file exceptions | `computer/vendor/novnc/LICENSE.txt`, `COPYRIGHT.Debian`, `LOCAL_PATCHES.md` |
| noVNC bundled pako | zlib / MIT, retained per-file notices | `computer/vendor/novnc/vendor/pako/`, `COPYRIGHT.Debian` |
| WayVNC patch/build helper | WayVNC upstream ISC; build fetches pinned upstream source with SHA-256 verification | `computer/wayvnc-headless.patch`; original license remains in downloaded source |

ESP-IDF, BSP, LVGL, ESP-SR/ESP-DL and cJSON are resolved from their upstream packages at build/install time. Their licenses apply independently. No third-party API keys, SDK accounts, private services or provider usage quota are supplied by this repository.

The bundled `wake_ack.pcm` is a synthetic wake acknowledgement, not a recording of the owner. Owner enrollment recordings/embeddings and private reference uploads are excluded. The transformed speaker model contains upstream public test vectors as documented; it does not contain the deployer's voiceprint.
