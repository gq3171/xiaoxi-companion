# ESP32 交互端

目标板：Waveshare ESP32-S3-Touch-AMOLED-2.16（SKU 33969），16 MiB Flash、PSRAM。开发环境 ESP-IDF 5.5.5，托管依赖见 `main/idf_component.yml`。其他屏幕/引脚/传感器需要 BSP 适配，不能直接刷入。

## 构建和连接

先安装官方 ESP-IDF 5.5.5 并激活其环境；不要使用包含别人配置的现成二进制。

```sh
cd firmware
idf.py set-target esp32s3
idf.py menuconfig
```

在“桌宠”配置里启用 `DESKPET_REMOTE_BRAIN`，配置：

- `DESKPET_COMPUTER_URL`：与你浏览器相同的 HTTPS origin，例如 `https://你的域名:8791`，无 `/home/` 路径。
- `DESKPET_COMPUTER_TOKEN` 与 `DESKPET_BRAIN_TOKEN`：分别取主机私有 `service.env`、`brain.env`；不公开或混用。
- `DESKPET_COMPUTER_CA_FILE`：复制本次主机的**公共 CA**到 `firmware/private/computer-ca.pem`，填写 `private/computer-ca.pem`。不得嵌入证书私钥。
- Wi-Fi 可以留空，在屏幕完成配网。云模型 Key 留在主脑，远程模式不需要把它写入板子。

远程模式默认启用房间同步和 panel cache。主脑安装器生成相同美术/字体资源，并经认证接口分块下发，板端有校验及 A/B 缓存。

```sh
idf.py build
idf.py -p YOUR_SERIAL_PORT flash monitor
```

`flash` 会改变板子固件。先核对型号、串口与原数据备份；不要对未知设备自动执行整片擦除。`sdkconfig`、私有 CA 目录与构建固件禁止提交。

## 本地语音模型

默认 `DESKPET_WAKE` 需要单独写入 MultiNet 模型；**普通应用 flash 不会自动完成这一块**。阅读 [models/NAME_WAKE.md](models/NAME_WAKE.md) 的地址、容量及校验要求，再使用其 provision 工具。开启 `DESKPET_LOCAL_OWNER` 则嵌入同目录 speaker-verification 模型，依赖与限制见 [models/README.md](models/README.md)。声纹仍为实验功能，不作高风险身份认证。

首次顺序为配网 → 主人声音录入/复验（启用时）→ 模型理解名字与初始约定 → 主脑身份导入 → 对话。必须安排实际语音、触摸、显示和旋转测试；编译成功不能替代整机测试。

## 素材和存储

运行素材已打包在 `main/character/pet_character_assets.c`，52 帧动作/表情及房间/小院背景；`assets/character/manifest.json` 提供帧索引。主脑安装时从同一 C 资源生成网页 PNG，不需要私人的原始参考图。中文位图字体及许可证见 `main/fonts/`。本地唤醒反馈为 `assets/voice/wake_ack.pcm`。

当前缓存分区和模型布局只适用于这块 16 MiB 板子的配置，不得在不了解分区时挪用地址。资源空间较紧，增加素材前需重新检查构建体积和 A/B bank 容量。
