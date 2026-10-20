# 安装

在 Debian/Ubuntu、Python 3.11+、systemd 的 Linux 主机上克隆仓库后：

```sh
sudo ./install.sh --setup
```

向导只询问：

1. **数据目录**：按你实际磁盘路径填写，例如 `/srv/ssd/xiaoxi`。没有独立数据盘也可以选择普通目录；不要求叫 NVMe 或挂载到指定位置。
2. **访问地址**：域名或本机局域网 IP，用于网页、板子与 HTTPS 证书。
3. **服务商、API 地址和实际模型名称**：可选预设或自定义兼容接口；确认地址对应自己的地域/套餐。
4. **该服务的 API Key**：隐藏输入，保存成权限 600 的私有配置。无鉴权的本地 HTTP 模型可留空。
5. **语音服务（按需）**：更换对话服务商时，可独立选择 MiniMax / OpenAI 兼容语音，或先关闭；不把对话 Key 自动交给其它服务。

软件包安装、native 编译、房间素材生成、随机服务 Token、证书和 systemd 由安装器自动处理。默认 HTTPS 端口 8791，需修改时传 `--port`。首次使用约需 2 GiB 可用空间；完整桌面与媒体需更多。数据盘/目录需要支持 Unix 权限；不会分区、格式化或清空已有目录。

## 自动部署

给协助部署的大模型阅读 [INSTALL_FOR_AGENTS.md](INSTALL_FOR_AGENTS.md)。无交互例子：

```sh
./install.sh --check --data-dir /srv/ssd/xiaoxi --json
sudo ./install.sh --apply --data-dir /srv/ssd/xiaoxi --hostname YOUR_DNS_OR_LAN_IP --env-file /private/provider.env --json
sudo ./install.sh --doctor --json
```

`provider.env` 包含 `LLM_PROVIDER`、`LLM_MODEL`、`LLM_API_KEY`，以及按需设置的 `LLM_BASE_URL` / `LLM_API_TYPE`，权限 600，放仓库外。各服务商及独立语音配置见 [MODELS.md](MODELS.md)，旧 MiniMax env 仍兼容。不要在命令参数中放 API Key。路径保存后，后续 `--doctor` 和同一版本重跑不需再输入路径或密钥。

退出码 2 表示本地 HTTPS 主脑就绪、还需板端身份导入；不是要求重装。详情和高级可调项见 [配置清单](CONFIGURATION.md)。主脑检查不发付费模型请求，不能据此声称 API 套餐已验收。

## 必要的人工步骤

- 在自己的浏览器/系统导入本次安装生成的 `数据目录/config/ca.pem` **公共 CA**（核对指纹），或使用自己的公有证书。不要复制 `ca.key`、`server.key`。服务器证书默认一年有效，需在到期前续签。
- 确保选择的 IP/域名能从客户端访问；需要外网时自行配置 DNS/路由器。只开放 HTTPS，VNC/CDP 保持私有。
- 按 [固件说明](../firmware/README.md) 核对板型/串口、配置主脑并完成身份创建；网页与板子共享同一只小溪，不能伪造身份导入跳过主人确认。

首次网页配对：在已安装的主机上运行 `sudo python3 软件目录/home_pair_admin.py`，取得一次性配对码。配对后可在网页生成独立持久 Token。

## 可选桌面和维护

[真实桌面](DESKTOP.md) 的显卡驱动/依赖需按目标机器验收，不是所有 Linux 硬件都一样。路径和 unit 由同一安装配置生成，不再手改目录名。

同一版本安装器可幂等重跑；版本升级使用 `computer/release_runtime.py` 的精确基线/备份/健康检查流程。不能删除配置或把旧数据库覆盖新记忆来“重新安装”。停用主脑使用 `sudo systemctl disable --now deskpet-computer.service`，不自动删除数据。
