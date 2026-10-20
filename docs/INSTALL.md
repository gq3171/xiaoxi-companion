# 安装主脑

详细执行合同见 [INSTALL_FOR_AGENTS.md](INSTALL_FOR_AGENTS.md)。可把该文件交给协助部署的大模型。

## 准备 Linux

使用 Debian/Ubuntu、Python 3.11+、systemd。RK3399 已验证；其他 ARM64/x86_64 的主脑路径可检查，桌面/音频硬件仍需适配。先自行将数据盘挂载到 `/mnt/nvme`，安装器不会处理磁盘分区。主脑安装要求至少 2 GiB 空间，桌面/浏览器/模型产物需要更多；建议至少 4 GiB RAM，具体并发量需实测。

```sh
./install.sh --check --json
```

在仓库外创建只有自己能读的 `provider.env`，填入自己的 MiniMax API Key；格式参照 `computer/env.example`，然后 `chmod 600 /private/provider.env`。不要使用个人 Wi-Fi 密码当 Token。

```sh
sudo ./install.sh --apply --hostname YOUR_ACTUAL_DNS_NAME --env-file /private/provider.env --json
sudo ./install.sh --doctor --json
```

退出码 2 说明服务已就绪、还需板端身份导入。退出码 1 则应先查看具体错误，别反复重装。脚本不验证套餐是否包含目标模型/语音能力，实际调用权限和计费以你的账号为准。

## HTTPS 与网页

默认 HTTPS 端口 8791。为实际域名配置 DNS 和需要的路由器映射，仅暴露 HTTPS；SSH、VNC 与 CDP 不属于网页访问所需的公共端口。

CA 公共证书位于 `/mnt/nvme/deskpet/config/ca.pem`。通过可信 SSH/SCP 取走该公共证书，核对指纹后在自己的 Windows/macOS 浏览器/系统信任库导入。**不要取走 `ca.key`、`server.key`。** 也可使用自己的公有证书替换服务证书并保留严格校验。服务器证书默认一年有效，要安排续签。

打开 `https://你的实际域名:8791/home/`，在主机运行下面命令取得 3 分钟有效的一次性网页配对码：

```sh
sudo python3 /opt/deskpet-computer/home_pair_admin.py
```

完成配对后，网页“设备授权”可以生成独立的持久网页 Token，妥善保存，以后新电脑也能登录。网页 Token 不等于服务间的 Computer/Brain Token。

首次仍需 [ESP32 身份创建](../firmware/README.md)，网页不单独新建另一只小溪。

## 卸载与升级

`sudo systemctl disable --now deskpet-computer.service` 可以停用主脑。不要自动删除 NVMe 数据或用户账户；记忆和任务产物可能是用户需要保留的内容。本安装器只接受初次安装或相同版本重跑，版本升级见 `computer/release_runtime.py`。任何操作前先备份配置和 SQLite 的一致快照，不拷贝正在写入的单个数据库文件冒充完整备份。
