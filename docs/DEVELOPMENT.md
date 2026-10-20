# 开发与验证

| 目录 | 内容 |
|---|---|
| `computer/` | Linux 主脑、记忆、任务、媒体、浏览器/真实桌面、Web 同步 |
| `computer/home_web/` | 房间、聊天、录音和 noVNC 前端 |
| `computer/vendor/novnc/` | 保留许可证的 noVNC 与局部修改 |
| `firmware/main/` | ESP32 交互、音频与可复用场景/记忆 C 引擎 |
| `firmware/tests/` | 主机端 C/LVGL 验证夹具；部分需 ESP-IDF 依赖 |
| `firmware/models/` | 本地唤醒与实验声纹模型及许可 |
| `scripts/` | Linux 初次安装和安装器回归 |

Linux 测试依赖：Python 3.11+、C 编译器、Pillow；Node.js 用于前端合同验证；FFmpeg 用于完整媒体测试。回归使用临时目录和合成夹具，不需要私人配置或调用真实云模型。

```sh
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 -m unittest discover -s computer -p 'test_*.py'
node computer/test_home_web.cjs
node computer/test_desktop_client.cjs
node computer/test_novnc_render.cjs
node computer/test_private_input.cjs
python3 -m unittest discover -s firmware/tests -p 'test_cloud_host.py'
python3 -m unittest discover -s firmware/tests -p 'test_voice_selection.py'
python3 -m unittest discover -s firmware/tests -p 'test_runtime_core.py'
```

`test_brain.py` 和上述固件 host 夹具在托管 IDF cJSON 未下载时使用带许可证的 `computer/vendor/cjson`。完整固件构建请按 `firmware/README.md`，它会解析 BSP、LVGL、ESP-SR/ESP-DL 等依赖，不将本机 `managed_components` 提交进仓库。

`computer/build_home_assets.py` 只导出现有 palette/RGB565 素材，不重新生成角色。`firmware/tools/build_panel_resources.py` 会生成 panel C 表、资源清单和二进制；安装器在临时源码副本里运行它，避免改动 checkout。床遮挡数据由共享 `pet_home.h` 常量生成，睡姿使用独立遮挡层。

发布前运行完整回归、检查许可证与私人数据。禁止提交运行时导出、个人语音、原始私有参考图、实际服务 CA/私钥、数据库或包含凭据的固件。公共历史应只包含经过审查的公开文件。

部署配置统一由 `deployment_paths.py`、`runtime_config.py` 与 `backend_config.py` 读取；改动路径/模型字段时需跑安装器、配置一致性和实际请求回归。未知配置必须拒绝，不能悄悄回到另一块磁盘或其他付费模型。

多模型回归入口 `python3 -m unittest discover -s computer -p test_model_backends.py`，包含不调用云服务的本地 HTTP 和音频夹具。修改协议时同时检查模型/Key 路由、流结束、取消与任务执行，不只替换模型字符串。

浏览器视觉回归：`python3 -m unittest discover -s computer -p test_visual_browser.py`；执行器回归还核对图片仅进入一次推理、不进入任务检查点。真正 Chromium 合成探针 `computer/visual_probe.py` 需部署代理显式在独立端口/用户目录运行，参考 DESKTOP.md，不作为普通 CI 的真实账户操作。
