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
- 从仓库 `computer/` 将 `desktop_daemon.py`、`desktop_shell.py`、`desktop_stop.py`、`desktop_launcher.py`、`deployment_paths.py`、`runtime_config.py`、`runtime.defaults.json` 复制到定位配置的 `desktop_install_dir`，软件目录 root 所有、755，源文件 644。数据、浏览器 profile、缓存、下载和日志均在所选数据目录。
- 把安装器生成的 `数据目录/config/systemd/deskpet-desktop.service` 放到 systemd unit 目录，执行 `systemctl daemon-reload`。**不要设成开机自动拉起**：主脑按需启动桌面，空闲自动回收。服务内部按关键进程状态管理退出，`Restart=no` 是有意设置。
- 确认 `DESKPET_PUBLIC_ORIGIN` 是自己的真实 HTTPS origin，与浏览器地址完全一致。

浏览器从“她的电脑”打开桌面。观看通道禁用输入；“接管”取得有时限的服务端租约，暂停代理桌面动作；“交回小溪”释放控制权并让任务重新观察页面。

## 验收

检查 `systemctl status deskpet-desktop` 和私有 socket 是否已生成。先观看、再接管，实际打开终端/文件夹、拖动窗口、切换标签页、交回，确认画面持续刷新且两个通道一致。仅 RFB 握手成功不能证明桌面刷新正常。需要分别测试 Win11 Edge/Chrome 和 macOS 浏览器。

Unix VNC socket 只在主机内，配置的 CDP 端口仅 loopback，外部访问走同源 HTTPS/WSS 鉴权。不要为排错开放公网 VNC/CDP 或关闭 Origin 检查。注册/付款等受保护步骤仍受明确任务授权与交互防护约束，不保证任何网站都可自动完成。

渲染器、DRM device、帧率和私有调试端口可通过安装配置 `options.desktop` 调整；服务与定位/退出/连接校验共用配置，不要只改 Chromium 命令。路径/参数变动后重启相关服务；硬件适配仍需实测。
