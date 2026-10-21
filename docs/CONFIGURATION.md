# 配置清单

首次只需运行 `sudo ./install.sh --setup`，提供或确认数据目录、访问地址、**后端模型名和该服务的 API Key**。安装器显示的模型建议不等于你的账号一定开通，必须按自己的账号确认。可选预设或自定义协议，对话与语音/搜索解耦，详见 [多模型接入](MODELS.md)。

## 配置放在哪里

| 文件 | 内容 | 权限 / 生效 |
|---|---|---|
| `/etc/xiaoxi/install.json` | 数据/软件/桌面/浏览器目录、真实挂载点、端口、公共 origin、运行参数、用户名称 | 不含密钥，root 管理、644；运行参数修改后重启，路径等迁移见下文 |
| `数据目录/config/service.env` | `LLM_*`、`ASR_*`、`TTS_*`、`SEARCH_*`、Computer Token、origin | 600，不能公开；模型/提供商 env 值优先于默认选项 |
| `数据目录/config/brain.env` | 独立 Brain Token | 600，自动生成并保留 |
| `数据目录/config/systemd/` | 按实际配置生成的三份 systemd unit | 主脑自动启用；可选图形桌面另行配置 |
| `computer/providers.defaults.json` | 服务商地址/协议预设，用户可覆盖地址，不代表开通权益 | 不含密钥；安装时复制 |
| `computer/runtime.defaults.json` | 版本随附的非秘密默认参数 | 不需逐项填写；首次可用 `--settings-file` 提供覆盖 |
| `firmware/sdkconfig` | 板端 Wi-Fi、主机连接、本地模型开关和独立模式模型名 | 本地私有文件，不提交 |

完整路径只保存一次，Linux 主脑、桌面、独立浏览器、配对管理、升级与 WayVNC 构建共用它。高级用户可用 `--config-file` 改定位文件位置；随后运行管理脚本时应设置 `DESKPET_INSTALL_CONFIG` 指向相同位置。

## 数据和部署参数

- `--data-dir /你的数据盘/小溪`：小溪专用目录，不改数据盘名称。若直接填写当前挂载点，自动使用 `xiaoxi` 子目录，不接管整块磁盘的根目录。
- 未另选磁盘时建议目录为 `/var/lib/xiaoxi`；这可能在系统盘上。检查输出明确提供 `storage_mount` 和 `separate_storage`，由使用者选择是否合适。
- `--require-mount /你的挂载点`：可选的首次防误写检查。安装时记录实际挂载点，后续该挂载点不在时拒绝启动，不落回系统盘。
- `--install-dir`：软件位置；默认 `/opt/deskpet-computer`。桌面和浏览器软件默认使用同一父目录下的独立目录。
- `--hostname`：域名或局域网 IP。支持 IP 证书，不强制公网域名；CA 信任仍需使用者在客户端操作。
- `--port`：HTTPS 端口，默认 8791；主脑、证书健康检查、链接和配对工具同步使用它。
- `--task-user`：可选的非 root 执行账户名。没有免密码 sudo；数据父目录若需通行，仅给该账户增加 traverse ACL，不把秘密目录改成可读。

已有部署的目录、账号和端口不会被安装器悄悄迁移。同一版本重跑会复用保存配置；移动现有数据需另行做一致性备份与迁移。旧版默认目录仅作为已有安装的兼容读取逻辑，不是新安装的要求。

路径、挂载点、账号和端口参与 systemd unit 生成，不能仅编辑 JSON 后重启就视为迁移完成。完成数据/权限迁移后，可用 `python3 软件目录/deployment_paths.py --service computer`（或 `desktop` / `browser`）从配置重新渲染 unit；该命令只输出文本，不改服务。核对后替换对应 unit、执行 daemon-reload，再启动并验收。域名/IP 变化还需更新私有 env 中的 origin 和匹配证书。

为兼容旧部署，`DESKPET_DATA_ROOT`、`DESKPET_DESKTOP_ROOT`、`DESKPET_BROWSER_ROOT` 与 `DESKPET_DESKTOP_CDP_PORT` 仍可做进程环境覆盖；新部署应统一使用定位 JSON，避免各进程传入互相矛盾的覆盖值。`DESKPET_PUBLIC_ORIGIN` 优先于定位文件的 origin。

## 模型和语音

使用通用 `LLM_PROVIDER`、`LLM_MODEL`、`LLM_API_KEY`，按需覆盖 `LLM_BASE_URL` 与 `LLM_API_TYPE`；旧 `MINIMAX_*` 仅在 MiniMax 模式兼容读取。ASR/TTS/search 的独立配置和 Key 规则见 [MODELS.md](MODELS.md)。不会因某个服务失败而自动换厂商/账户。

`options.llm.send_temperature` 可为 `auto` / true / false；`effort_mode` 可为 `auto` / `none` / `minimax` / `openai`；`token_parameter` 可为 `auto` / `max_tokens` / `max_completion_tokens`（Chat 协议）。预设默认只发送保守、受支持的参数；模型所支持的思考参数由部署者确认，不能把 MiniMax 的 output_config 原样交给任意模型。

可选运行参数在定位 JSON 的 `options` 中（首次 `--settings-file` 接收相同结构）：

```json
{
  "llm": {"timeout_seconds": 30, "dialogue_max_tokens": 4096, "reflection_max_tokens": 8192, "dialogue_effort": "low", "reflection_effort": "high", "temperature": 1},
  "speech": {"tts_model": "speech-2.8-turbo", "asr_model": "asr-1.0", "default_voice": "female-shaonv"},
  "desktop": {"cdp_port": 19223, "probe_cdp_port": 19224, "renderer": "gles2", "drm_device": "/dev/dri/renderD128", "max_fps": 15, "headless_idle_seconds": 300},
  "web": {"preview_port": 18791},
  "http": {"connection_limit": 64, "handshake_limit": 8, "handshake_timeout": 4, "lane_limits": {"rpc": 16, "web": 20, "events": 20, "desktop": 8}}
}
```

只写要覆盖的字段，缺项沿用默认；未知字段/越界数值会拒绝启动。Key 禁止放进 `options`。后端模型名/API 地址以私有 `service.env` 为准；不要在两处维护互相矛盾的值。MiniMax 模式下板子已保存音色优先于初始音色，网页使用默认音色。兼容 OpenAI 的 TTS 使用 `TTS_VOICE` 或 `speech.openai_voice`；板端内置 MiniMax 音色列表目前不映射其它厂商。主脑对板端旧版默认 TTS/ASR 型号进行统一覆盖；音频仍固定为双方约定的 16kHz 单声道 PCM。兼容 OpenAI 的 PCM 合成默认按 24kHz 接收、经 FFmpeg 缓冲重采样，`speech.openai_pcm_rate` 可设实际上游采样率；它不是端到端实时语音。

## 保留为代码约束的内容

- HTTPS 验证、Cookie/Token 鉴权、VNC Unix socket、CDP 仅 loopback、模型 URL 格式/TLS 校验与禁止凭据重定向；没有“关闭安全”配置。
- 消息协议、音频采样/帧大小、场景 wire 格式、资源摘要、公开模型布局和 Flash 分区；不能当普通运行参数随意修改。
- 已验证的 WayVNC 源码版本、URL 和摘要固定在构建脚本中，升级要同时审查源码与校验值。
- 硬件引脚/驱动属 BSP，板端可调模型、亮度/省电和网络开关由 Kconfig/设备设置管理。
- 回归夹具中的示例地址、独立测试端口，以及容量基准访问的演示网站不是生产目标地址。新增功能时也不得重新引入个人服务器地址。

`options.desktop.browser_vision`（布尔，默认 `true`）控制浏览器的截图图片输入与定位工具。纯文本后端设 `false`；环境 `DESKPET_BROWSER_VISION=0|1` 可覆盖。它复用当前模型，不自动添加另一家模型或凭据。坐标新鲜度、隐私与命中检查见 [DESKTOP.md](DESKTOP.md)。

## 浏览器搜索切换

`options.desktop.search_timeout_seconds` 为一次公开搜索导航或首次读取的等待预算，默认 8 秒，范围 2–20 秒。`search_engines` 是候选顺序，默认 `["google", "bing", "baidu"]`，允许调整顺序或只保留其中部分；不需要新的 API Key。已失败的引擎在当前任务内暂停重试 120 秒。

失败时保留原搜索词，给执行模型返回其他候选入口，由模型选择继续；只有确认本任务的挂起搜索标签已关闭，才解除这次搜索导航的待核对状态。所有候选都不可用时如实停止。明确“只用某个引擎”的要求会限制推荐候选。网页登录、私密填写、注册提交及未知点击不采用此恢复规则；切换搜索引擎也不代表已查到资料。

升级可选桌面组件时，应同时同步共享的 `runtime_config.py` 与 `runtime.defaults.json` 到配置指定的软件目录，再使用新增配置字段，避免旧组件拒绝新字段。纯默认使用不要求用户编辑配置。

## 任务运行参数

`options.tasks` 可覆盖 `context_bytes`（默认 32768，范围 8192–65536）、`completion_rounds`（3，1–5）、`queue_limit`（8，1–32）、`command_timeout_seconds`（受管理命令默认 600，30–1800）、`skill_active_limit`（64，16–256）、`skill_select_limit`（4，1–8）。这些是容量和执行预算，不是安全开关。普通同步命令仍采用 120 秒上限；较长的已授权步骤使用受管理句柄。具体恢复和验收行为见 [TASKS.md](TASKS.md)。
