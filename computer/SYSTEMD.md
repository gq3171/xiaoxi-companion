# systemd 服务

不再分发写死数据盘名称的静态 unit。安装器根据用户选择的数据目录与实际挂载点生成三份服务：

`DATA_DIRECTORY/config/systemd/deskpet-{computer,desktop,browser}.service`

主脑 unit 由安装器自动启用。可选桌面按 docs/DESKTOP.md 安装依赖/普通账户后，使用这里生成的 desktop unit；browser unit 仅用于独立 headless 模式。不要同时运行两套占用同一 CDP 端口的浏览器。

非秘密路径定位文件默认 `/etc/xiaoxi/install.json`，程序与服务共享它。模型名和 Key 位于所选数据目录的私有 `config/service.env`。数据盘卸载时服务拒绝启动，避免数据落回系统盘。
