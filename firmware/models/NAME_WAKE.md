# Follow the pet's name: local prototype

2026-10-17. The intended phrase is the confirmed pet name twice: 小西 → 小西小西. The persisted semantic name is read from birth identity; raw naming instructions are never used as a keyword. Runtime changes replace the command and invalidate the previous binding before reconfiguration.

This is an **experimental use of MultiNet5 Chinese command recognition**, not a custom-trained WakeNet model. Espressif documents dynamic command updates but recommends command recognition after a wake engine. Continuous command recognition must therefore be measured for music/speech false activations; passing synthetic clips is not a real-world accuracy claim. No claim of speaker identity or immunity to recordings is made.

- Initially supports 1–4 Han characters with available dictionary readings. Other names keep touch-to-chat. Names are not silently truncated or renamed.
- Generated pinyin uses pypinyin 0.55.0 (MIT), default character readings, without tones. Personal-name polyphones need further pronunciation selection. Full generated table and licenses are retained.
- `pack_name_wake.py` packs unmodified bundled `mn5q8_cn` weights, original source hashes, and synthetic test clips. `pet_name_wake_manifest.json` defines the exact packed SHA256. Firmware verifies the whole blob **before** giving its offsets to ESP-SR.
- The model's reserved range is **0xA00000–0xD00000** on this 16MiB board. Existing factory app 0x10000–0x810000 and SPIFFS 0x810000–0x910000 keep their addresses. The reserve contains inactive original factory data on this board; it must be backed up before provisioning. It is not claimed to have been erased originally.
- `esp_partition_register_external` registers a runtime descriptor and refuses overlaps with real partitions. It does not rewrite the partition table. The firmware reads the model; it never formats, updates or erases this range itself.
- `provision_name_wake.py` requires a fresh complete live 16MiB backup, validates current partition boundaries and packed model hash, then writes only the application and model. It does not write bootloader, partition table, NVS or SPIFFS. Keep original and fresh backups private: they contain credentials and memory.
- A standalone app update will not install the model on another board. Missing or corrupt model keeps the screen touch fallback. Future partition additions must respect this reservation or explicitly relocate and reprovision the model.

Rebuild the public blob/table:

```
python3 -m venv /private/wake-tools
/private/wake-tools/bin/pip install pypinyin==0.55.0
/private/wake-tools/bin/python firmware/models/pack_name_wake.py
```

Current prototype configures the engine detection threshold at 0.90. It trusts `ESP_MN_STATE_DETECTED`; returned candidate-ranking probabilities must **not** be compared with this threshold again (the positive synthetic tests returned 0.591 and 0.367). They are not calibrated biometric confidence.

2026-10-17: the recognizer now conditions a private copy of each 512-sample input frame with `pet_wake_level`. Quiet frames move toward RMS1400 with at most 8x gain; loud onsets immediately limit added gain to keep boosted peaks below24000. Already louder original samples pass at unity gain. Sub-floor room noise does not request amplification and gain returns toward unity after sustained quiet. Original capture/ASR/owner enrollment audio, name phonemes, acceptance threshold0.90 and reply-window admission stay unchanged. This is amplitude adaptation, not a new trained wake model or a proven cure for every missed human voice.

Actual ESP32-S3 diagnostic replay passed all11 cases: original six bindings/negative cases, an observational raw positive at one-eighth amplitude, normalized quiet positives for both names, and normalized quiet ordinary/near-phrase negatives. The unnormalized quiet positive **also passed**, so these results do not establish low level as the cause of the user's missed wake. Evidence is private `build/before-wake-level/boot-level-selftest.log`; production disables the diagnostic replay. Full81 host regressions and the later4 capture regressions passed. User microphone acceptance is still required; do not infer music false-alarm rates from four synthetic source recordings.

Real ESP32-S3 boot replay passed six cases: 小西→小西 positive; 小西→小月 negative; 小月→小月 positive; 小月→小西 negative; ordinary speech and a similar-sounding sentence negative. Each clip includes leading silence, matching an already running local detector. These are one synthetic voice and a tiny sample, not real microphone/music acceptance or a measured false-alarm rate. `build/boot-name-wake-selftest-pass.log` retains evidence. Production disables the boot replay to avoid a 10s startup delay; developer builds can enable `PET_WAKE_BOOT_SELFTEST=1` in pet_wake.c.

Synthetic positive/negative testing and a real microphone trial remain separate requirements. Music rejection is still under evaluation.

Sources: [Espressif dynamic command APIs](https://docs.espressif.com/projects/esp-sr/zh_CN/latest/esp32s3/speech_command_recognition/README.html), [WakeNet custom training process](https://docs.espressif.com/projects/esp-sr/zh_CN/latest/esp32s3/wake_word_engine/ESP_Wake_Words_Customization.html). Vendor custom WakeNet training is a separate commercial service; this prototype does not open or purchase it.

The latest app adds an offline local acknowledgement after a successful detection. The earlier app had only a footer hint, and the user reported no perceived wake; a logged candidate is not user acceptance. Test the latest audible cue and real microphone/music separately.
