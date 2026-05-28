# FnDesk · fnOS Edge 桌面

FnDesk 是为 fnOS 打包的 Microsoft Edge 桌面应用。它不安装 GNOME、KDE、XFCE 等完整桌面环境，只使用最小图形栈提供本地显示器 Edge 和 Web Edge 两种入口。

## 它能做什么

- **本地显示器打开 Edge**：在 tty1 上启动真实 Microsoft Edge。
- **Web 中打开 Edge**：通过 TigerVNC、noVNC 和 websockify 启动一个独立的真实 Edge 会话。
- **本地和 Web 相互独立**：两边不是同一个画面，可以分别使用。
- **不固定默认网页**：Edge 正常启动，用户自行输入地址或使用浏览器历史记录。
- **中文体验**：安装中文字体，配置 Edge 中文界面和 fcitx5 拼音输入。
- **显示器热插拔**：本地未接显示器时服务保持空闲，接入显示器后自动恢复。
- **Web 自动适配尺寸**：noVNC 调整虚拟屏幕尺寸后，同步 Edge 窗口大小，避免黑边和拉伸。
- **卸载可选清理**：卸载时可以选择是否删除 Web Edge 用户数据，以及是否卸载 FnDesk 依赖包。
- **内置 Edge 安装包**：在微软 apt 源不可用时，也可以使用包内自带的 Edge `.deb` 安装。

## 安装使用

将 `fndesk.fpk` 导入 fnOS 应用中心并安装。

安装完成后：

- 应用中心打开 FnDesk，会进入 Web Edge。
- 本地显示器连接后，会在 tty1 打开本地 Edge。

默认 Web 服务端口：

```text
18733
```

本地显示器画面卡死或需要恢复时，可以通过 SSH 或维护终端执行：

```bash
fndesk-restart
```

这个命令会重启本地显示器上的 FnDesk Edge 服务，并切回 tty1。它只影响本地显示器会话，不用于重启 Web Edge。

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
- `cmd/main`：Web Edge 运行入口。
- `cmd/common`：安装、升级、卸载回调逻辑。
- `app/install-kiosk.sh`：FPK 安装时调用的系统依赖和本地显示器配置脚本。
- `app/window-sync.sh`：同步 Web Edge 窗口尺寸。
- `wizard/uninstall`：fnOS 应用中心卸载向导配置。

## 开发说明

开发过程中，编码工作主要由 **GPT-5.5** 模型完成。

## License

MIT License. 见 [LICENSE](./LICENSE)。
