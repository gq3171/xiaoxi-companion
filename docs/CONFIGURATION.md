# 配置清单

首次只需运行 `sudo ./install.sh --setup`，提供或确认数据目录、访问地址、**后端模型名和该服务的 API Key**。安装器显示的模型建议不等于你的账号一定开通，必须按自己的账号确认。当前协议适配 MiniMax；不声称任意厂商 Key 可以互换。

## 配置放在哪里

| 文件 | 内容 | 权限 / 生效 |
|---|---|---|
| `/etc/xiaoxi/install.json` | 数据/软件/桌面/浏览器目录、真实挂载点、端口、公共 origin、运行参数、用户名称 | 不含密钥，root 管理、644；运行参数修改后重启，路径等迁移见下文 |
| `数据目录/config/service.env` | `MINIMAX_MODEL`、`MINIMAX_API_KEY`、`MINIMAX_API_HOST`、Computer Token、origin | 600，不能公开；模型/提供商 env 值优先于默认选项 |
| `数据目录/config/brain.env` | 独立 Brain Token | 600，自动生成并保留 |
| `数据目录/config/systemd/` | 按实际配置生成的三份 systemd unit | 主脑自动启用；可选图形桌面另行配置 |
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

`MINIMAX_MODEL` 与 `MINIMAX_API_KEY` 为新安装必需字段；向导隐藏输入 Key，自动化使用 `computer/env.example` 的私有副本。模型名会实际进入聊天、反思和任务的 API 请求，不再写死旗舰型号。不同模型是否支持 effort、音频和搜索，以你的账号和提供商接口为准；不会自动转用付费备用服务。

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

只写要覆盖的字段，缺项沿用默认；未知字段/越界数值会拒绝启动。Key 禁止放进 `options`。后端模型名/API 地址以私有 `service.env` 为准；不要在两处维护互相矛盾的值。板子的已保存音色选择优先于初始音色，网页使用配置中的默认音色。主脑对板端旧版默认 TTS/ASR 型号进行统一覆盖；音频仍固定为双方约定的 16kHz 单声道 PCM。

## 保留为代码约束的内容

- HTTPS 验证、Cookie/Token 鉴权、VNC Unix socket、CDP 仅 loopback、模型提供商 origin 校验；没有“关闭安全”配置。
- 消息协议、音频采样/帧大小、场景 wire 格式、资源摘要、公开模型布局和 Flash 分区；不能当普通运行参数随意修改。
- 已验证的 WayVNC 源码版本、URL 和摘要固定在构建脚本中，升级要同时审查源码与校验值。
- 硬件引脚/驱动属 BSP，板端可调模型、亮度/省电和网络开关由 Kconfig/设备设置管理。
- 回归夹具中的示例地址、独立测试端口，以及容量基准访问的演示网站不是生产目标地址。新增功能时也不得重新引入个人服务器地址。
