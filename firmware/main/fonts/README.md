# 中文字体

`pet_font_cn_16.c` 是由 Noto Sans CJK SC Regular 生成的 16px、2bpp 压缩位图字体，包含 ASCII、CJK 标点、基本汉字区和全角符号。不使用只含少量汉字的 LVGL 内置 CJK 字体，避免名字、灵魂和夜间文字回答显示成方框。

字体嵌入应用固件，**不占 1 MiB 的记忆存储分区**。字体保持在 Flash，避免复制到 PSRAM 与录音、TLS 和合成音频争用内存。

- 上游：[Noto Sans CJK](https://github.com/notofonts/noto-cjk)
- 原始字体：`Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf`
- 已核对的 Git blob SHA-1：`dc15562470b4f842321894787a0d066879ccff8b`
- 许可：同目录 `OFL.txt`，SIL Open Font License 1.1。
- 生成器：`lv_font_conv@1.5.3`。

在下载原始字体的目录中生成：

```sh
npx --yes lv_font_conv@1.5.3 \
  --font NotoSansCJKsc-Regular.otf \
  --range 0x20-0x7E,0x3000-0x303F,0x4E00-0x9FFF,0xFF00-0xFFEF \
  --size 16 --bpp 2 --no-kerning --format lvgl \
  --lv-font-name pet_font_cn_16 --lv-include lvgl.h \
  -o pet_font_cn_16.c
```

`pet_font_owner_28.c` 为主人声音录入页的大字字体，来自同一份已核对的 Noto Sans CJK SC Regular（同一 OFL 许可），28px、2bpp 压缩；仅包含 ASCII 和录入页面所需的 261 个汉字/标点。生成器同为 lv_font_conv@1.5.3，使用 --symbols 选择 pet_setup.c / pet_face.c 的中文字符，不重复嵌入完整汉字区。新增朗读句子时应重新生成所需字符集合。


## 常见标点与符号补全（2026-10-17）

用户反馈文字间出现方块，原范围没有U+00B7中点、U+2013/2014连接号、U+2018/2019/201C/201D引号、U+2026省略号。新增同源 `pet_font_symbols_16.c`，包含字体实际支持的U+00A0至U+2FFF共1634字形（Latin/Greek/Cyrillic、常见标点、箭头、数学符号等），不重复打包基本汉字。

生成命令：

```sh
npx --yes lv_font_conv@1.5.3 --font NotoSansCJKsc-Regular.otf --range 0xA0-0x2FFF \
 --size 16 --bpp 2 --no-kerning --format lvgl --lv-font-name pet_font_symbols_16 \
 --lv-include lvgl.h -o pet_font_symbols_16.c
```

生成后需保留字体后备链：owner_28 → cn_16 → symbols_16 → LV_FONT_DEFAULT。大字页缺少某字时可回退到较小字号，图标仍由LVGL默认字体处理。字体全部留在Flash。原始字符和记忆不改写，模型正文提示避免emoji；没有宣称覆盖所有Unicode或彩色表情。真实LVGL夹具断言15种原先缺失的符号在普通/大字字体均找到非placeholder字形，并生成symbols视图。
