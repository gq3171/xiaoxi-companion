# Linux 主脑

正式入口为 `agent.py`，导入 `brain.py` 和 `companion.py`；协议标识 `desktop-v1`。主脑集中持有记忆、任务、生活状态和模型调用。Web 房间与 ESP32 共享 `firmware/main/pet_scene*.c` 和 `pet_home.c` 的 native 场景引擎。

从根目录的 [安装说明](../docs/INSTALL.md) 开始，不要直接复制文件覆盖正在运行的服务。`scripts/install.py` 首次引导主脑和资源；`release_runtime.py` 对审查过的升级包做精确基线校验、空闲检查、软件备份、TLS 验收和源码回滚。

- [部署代理合同](../docs/INSTALL_FOR_AGENTS.md)
- [可选真实桌面](../docs/DESKTOP.md)
- [测试与目录](../docs/DEVELOPMENT.md)
- [隐私边界](../SECURITY.md)

`env.example` 是私有输入的空模板。实际域名由安装器写入 `DESKPET_PUBLIC_ORIGIN`，没有内置个人服务器地址。
