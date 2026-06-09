# FnDesk · fnOS 本地 Edge 控制台

FnDesk 是为 fnOS 打包的 Microsoft Edge 本地显示器控制工具。应用中心打开的是 Web 控制台；真实 Microsoft Edge 只在本地显示器 tty1 上运行，并且只在用户从控制台启动时运行。

它不安装 GNOME、KDE、XFCE 等完整桌面环境，只使用最小图形栈在本地显示器上启动 Edge。

## 它能做什么

- **Web 控制台**：在应用中心打开 FnDesk 后，可以启动、关闭、重启本地 Edge，并查看日志。
- **本地显示器 Edge**：在 tty1 上启动真实 Microsoft Edge，不在 Web 端运行虚拟浏览器。
- **手动启停**：本地 Edge 默认不自动启动；从控制台点击启动、关闭或重启。
- **显示器检测**：启动前检测 DRM 显示器连接状态，无显示器时启动失败并在日志里说明原因。
- **中文体验**：安装中文字体，配置 Edge 中文界面和 fcitx5 拼音输入。
- **保守卸载**：卸载不会删除本地 Edge 用户数据；依赖卸载只处理 FnDesk 安装时记录的包，并排除 Mesa/显卡驱动相关包。
- **内置 Edge 安装包**：在微软 apt 源不可用时，也可以使用包内自带的 Edge `.deb` 安装。

## 安装使用

将 `fndesk.fpk` 导入 fnOS 应用中心并安装。

安装完成后：

- 应用中心打开 FnDesk，会进入控制台。
- 本地 Edge 不会自动启动。
- 点击控制台中的 **启动** 后，本地显示器 tty1 才会打开 Edge。

默认控制台端口：

```text
18733
```

也可以通过 SSH 或维护终端控制本地 Edge：

```bash
fndesk-start
fndesk-stop
fndesk-restart
```

这些别名分别对应：

```bash
sudo systemctl start fndesk-local.service && sudo chvt 1
sudo systemctl stop fndesk-local.service
sudo systemctl restart fndesk-local.service && sudo chvt 1
```

## 控制台功能

控制台提供这些常用操作：

- **启动**：启动本地显示器上的 Edge，并切换到 tty1。
- **关闭**：停止本地 Edge 服务。
- **重启**：重启本地 Edge 服务，并切换到 tty1。
- **切到 tty1**：只切换本地显示器，不改变 Edge 运行状态。
- **重置失败**：执行 `systemctl reset-failed fndesk-local.service`。
- **日志查看**：查看 `fndesk-local.service` 和控制台自身日志。

本地 Edge 的 systemd 服务名：

```text
fndesk-local.service
```

显示器电源策略服务名：

```text
fndesk-display-power.service
```

## 从源码构建

```bash
./build_fpk.sh
```

构建完成后会生成：

```text
fndesk.fpk
```

构建脚本会临时生成 `app.tgz`，打包完成后自动删除。

## 目录结构

```text
kiosk/
├── README.md
├── LICENSE
├── build_fpk.sh
├── manifest
├── fndesk.fpk
├── ICON.PNG
├── ICON_256.PNG
├── cmd/
├── config/
├── wizard/
└── app/
```

## 关键文件

- `manifest`：fnOS 应用包元数据。
- `cmd/main`：FnDesk 控制台服务入口。`start`/`stop`/`status`/`restart` 供 fnOS 调用。
- `cmd/common`：安装、升级、卸载回调逻辑。升级/卸载时会清理旧 Web Edge 虚拟会话残留。
- `app/install-kiosk.sh`：FPK 安装时调用的系统依赖、本地 Edge 服务和控制台配置脚本。
- `app/server/fndesk-server.py`：控制台 HTTP 服务和本地 Edge 控制 API。
- `app/www/index.html`：Web 控制台前端。
- `wizard/uninstall`：fnOS 应用中心卸载向导配置。

## 卸载说明

FnDesk 卸载不会删除本地 Edge 用户数据。选择卸载依赖包时，只会卸载 FnDesk 安装时记录的依赖，并显式跳过 Mesa、libgl、libdrm、firmware、linux 等显卡驱动和系统基础包。

## 开发说明

开发过程中，编码工作主要由 **GPT-5.5** 模型完成。

## License

MIT License. 见 [LICENSE](./LICENSE)。
