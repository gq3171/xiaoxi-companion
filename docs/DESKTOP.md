# 可选真实 Linux 桌面

此功能不是静态截图：小溪的任务与 noVNC 观看/接管共用同一 labwc/Chromium 桌面。普通主脑安装不会自动安装图形栈。以下为已验证 RK3399 路径；其他主机的 DRM/EGL、软件包版本必须先检查，不能宣称通用一键可用。

## 先检查

确认安装配置记录的数据盘已挂载、内存充足，存在所配置的 DRM render device（默认 `/dev/dri/renderD128`），`render`/`video` 组可用。确认发行版能提供 WayVNC 0.9.1 对应的开发依赖；`apt-cache policy` 与 `apt-get -s install ...` 可以先检查，不必升级整机系统。

桌面运行包：`labwc swaybg waybar wofi foot thunar chromium grim wtype ydotool websockify python3-websocket dbus-user-session fonts-noto-cjk`。命令/包在不同 Debian/Ubuntu 版本上可能有差异；缺包时先核对发行版，不盲目替换为另一套未经测试的远控服务。

WayVNC 本地构建包：`meson ninja-build pkg-config patch libwayland-dev libneatvnc-dev libaml-dev libpixman-1-dev libdrm-dev libxkbcommon-dev libgbm-dev libjansson-dev wayland-protocols`。

## 构建与部署

先由用户授权安装上面的缺失软件包。脚本从官方源下载固定 WayVNC 0.9.1 归档并校验 SHA-256，应用 `computer/wayvnc-headless.patch`，通过上游测试才安装独立二进制；不会覆盖系统 `/usr/bin/wayvnc` 或自动重启桌面。

```sh
sudo python3 computer/build_wayvnc_headless.py --install
```

这个补丁对 HEADLESS/NOOP 输出跳过物理屏幕电源独占，避免观看与控制两个采集通道互相冻结。不能用未修补的系统 WayVNC 代替。

首次创建独立 `deskpet-desktop` 系统账户，home 为 `/etc/xiaoxi/install.json` 的 `desktop_root`（默认数据目录下的 `desktop`），shell `/usr/sbin/nologin`，附加组 `render,video`，不授予 sudo。先检查是否已有同名账户、目录或服务；有的话保留配置并核对归属，不能覆盖。

- 创建并将配置中的 `desktop_root` 归属该账户；祖先目录须允许该账户通行，必要时用仅 traverse 的具名 ACL，权限 700。
- 从仓库 `computer/` 将 `desktop_daemon.py`、`desktop_shell.py`、`desktop_stop.py`、`desktop_launcher.py`、`deployment_paths.py`、`runtime_config.py`、`backend_config.py`、`runtime.defaults.json`、`providers.defaults.json` 复制到定位配置的 `desktop_install_dir`，软件目录 root 所有、755，源文件 644。数据、浏览器 profile、缓存、下载和日志均在所选数据目录。
- 把安装器生成的 `数据目录/config/systemd/deskpet-desktop.service` 放到 systemd unit 目录，执行 `systemctl daemon-reload`。**不要设成开机自动拉起**：主脑按需启动桌面，空闲自动回收。服务内部按关键进程状态管理退出，`Restart=no` 是有意设置。
- 确认 `DESKPET_PUBLIC_ORIGIN` 是自己的真实 HTTPS origin，与浏览器地址完全一致。

浏览器从“她的电脑”打开桌面。观看通道禁用输入；“接管”取得有时限的服务端租约，暂停代理桌面动作；“交回小溪”释放控制权并让任务重新观察页面。

## 验收

检查 `systemctl status deskpet-desktop` 和私有 socket 是否已生成。先观看、再接管，实际打开终端/文件夹、拖动窗口、切换标签页、交回，确认画面持续刷新且两个通道一致。仅 RFB 握手成功不能证明桌面刷新正常。需要分别测试 Win11 Edge/Chrome 和 macOS 浏览器。

Unix VNC socket 只在主机内，配置的 CDP 端口仅 loopback，外部访问走同源 HTTPS/WSS 鉴权。不要为排错开放公网 VNC/CDP 或关闭 Origin 检查。注册/付款等受保护步骤仍受明确任务授权与交互防护约束，不保证任何网站都可自动完成。

渲染器、DRM device、帧率和私有调试端口可通过安装配置 `options.desktop` 调整；服务与定位/退出/连接校验共用配置，不要只改 Chromium 命令。路径/参数变动后重启相关服务；硬件适配仍需实测。


## 主动补充网站信息

浏览器任务遇到缺少的账号、密码、验证码或注册资料时，先保存当前页面和任务检查点，再发起一次私密填写请求。已授权网页会主动弹出窗口，显示实际 HTTPS 网站 origin、字段和本次可以点击的继续按钮。主人提交后，执行器直接填入绑定的控件，重新观察结果，再继续同一项任务。普通页面中的搜索框不会触发账号填写。

ESP32 发起的任务会在小屏主动提示，可选择「在这里填写」「到网页填写」「稍后处理」。小屏用屏幕键盘输入，密码和验证码遮挡显示；较大的下拉列表转到已授权网页处理。窗口只授权本页这一步，不提前授权后续步骤。人机验证、扫码、不可识别的 iframe/canvas、条款复选框以及付款等最终动作仍由主人在真实页面处理。

`private_input.py` 管理 10 分钟有效的内存请求和 90 秒填写权；网页前台续租，小屏提交前重新核对填写权。不同设备不能同时抢填。`private_browser.py` 绑定 tab、document、完整 URL、origin、控件身份、类型和按钮上下文。页面跳转、控件替换、撤销授权、任务停止或接管桌面会阻止旧提交继续发送。网络结果不确定时先核对实际页面，不自动重发密码或重复点击。

应用不把字段值写进聊天、模型请求、任务步骤、检查点或数据库。提交值只在请求和执行器内存中短暂存在，使用后释放并尽量清零；Python、浏览器、操作系统的内存/交换区不提供可证明的安全擦除。浏览器会保留正常的网站登录状态，目标网站自身的数据处理不属于本应用的存储保证。执行器在任务存活期间过滤页面回显中的已填写值，并阻止保存隐私填写后的网页截图；实时桌面仍可供主人查看。服务重启后需重新提供尚未完成的信息，不从磁盘恢复密码。

验收：`python3 -m unittest discover -s computer -p test_private_input.py`、`node computer/test_private_input.cjs`；真实网站还需核对其表单、跨页跳转和人工验证。测试账号密码必须使用本地合成页面，不把私人真实凭据用于自动回归。

## 截图视觉定位与模拟点击

普通网页控件优先使用 AX 元素引用。遇到图标或结构不清楚的非敏感页面，执行器可调用 `browser_look`：真实 Chromium 的当前视口截图作为图片发送给同一个已配置模型，供下一次判断使用。模型返回 `browser_visual_click(visual,box,target)`；`box` 是相对整张截图的 0..1000 整数框，适配实际截图像素、CSS 视口与 HiDPI，而不是凭经验猜屏幕坐标。`browser_screenshot` 仍是保存任务产物的独立工具，不等于模型看过图片。

点击要求同一任务标签、文档、URL、滚动与视口，截图不超过 60 秒；控件须存在于截图时的 AX 观察中。执行器核对真实命中元素和动作语义，鼠标移入后两次检查目标区域像素，目标变化、遮挡或移动则重新观察。一个截图编号只能尝试一次；输入回执超时也不重发点击。点击之后仍须 `browser_snapshot` / `browser_check` 核对具体可见结果，视觉模型的自我判断不能直接标记成功。Canvas 仅在无表单和受保护动作语义的简单页面开放；复杂 Canvas 的最终动作仍需主人核对。

图片只驻留任务 RAM，并只附加到一次模型请求，不写入步骤日志、检查点、技能或媒体产物。密码、验证码、已填写输入内容、可见框架和专用私密填写期间禁止此截图通道。账号资料继续走私密填写，不因开启视觉而暴露给模型。页面图文同属低信任数据。

当前范围是任务拥有的 Chromium 网页，并未开放任意原生 Linux 窗口的像素操作或拖拽。视觉模型仍可能识别错误，以上检查减少误点，不代表任意网页都保证识别成功。

需要当前后端模型支持图片输入。MiniMax M3.1 Flash 支持该能力，适配形状见 [MiniMax 官方说明](https://platform.minimax.io/docs/api-reference/text-anthropic-api)。其他后端按自身模型能力配置；纯文本模型请设置共享配置 `options.desktop.browser_vision=false`，或进程环境 `DESKPET_BROWSER_VISION=0`，保留元素工具；不会自动切换付费服务。默认开启，依赖 Pillow，安装器已包含 `python3-pil`。

本地回归 `test_visual_browser.py` 与执行器回归核对坐标、过期/遮挡/移动、取消、隐私和图片不落盘。`visual_probe.run(root,port,account,infer=None)` 是自愿执行的真实 Chromium 合成夹具：独立用户目录与调试端口，启动普通账户的临时浏览器、结束后清理，不连接真实桌面。默认不请求模型；显式提供 `infer` 才把几何图形截图交给模型，模型调用可能消耗部署者额度。不要拿真实登录页或桌面执行该夹具。
