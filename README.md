# FnDesk · fnOS Edge 桌面

FnDesk 是为 fnOS 打包的 Microsoft Edge 桌面应用。它不安装 GNOME、KDE、XFCE 等完整桌面环境，只使用最小图形栈提供本地显示器 Edge 和 Web Edge 两种入口。

## 它能做什么

- **本地显示器打开 Edge**：在 tty1 上启动真实 Microsoft Edge。
- **Web 中打开 Edge**：通过 TigerVNC、noVNC 和 websockify 启动一个独立的真实 Edge 会话。
- **本地和 Web 相互独立**：两边不是同一个画面，可以分别使用。
- **不固定默认网页**：Edge 正常启动，用户自行输入地址或使用浏览器历史记录。
- **中文体验**：安装中文字体，配置 Edge 中文界面和 fcitx5 拼音输入。
- **显示器热插拔**：本地未接显示器时服务保持空闲，接入显示器后自动恢复。
- **Web 精确适配窗口**：noVNC 把虚拟屏尺寸实时设成应用窗口可视区，并同步 Edge 窗口大小，不留黑边也不超出。
- **Web 按需启停，不常驻后台**：只有 websockify 常驻监听端口，真正耗资源的 Xvnc 和 Edge 在有人访问时按需启动；关闭窗口、切走或空闲超时后自动回收，再次打开自动恢复。
- **Web 端内置控制按钮**：noVNC 画面右下角提供菜单，可启动、重启、关闭本地显示器 Edge，也可以一键关闭 Web 后台。
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

## Web 端控制与按需启停

打开 Web Edge 后，画面右下角有一个 `☰ 控制` 菜单：

- **启动 / 重启 / 关闭本地 Edge**：操作本地显示器上的 `web-kiosk.service`（重启会自动切回 tty1）。
- **关闭 Web 后台**：立即回收远端 Xvnc 和 Edge 并断开连接。

Web 会话采用按需启停，避免“打开后一直占用后台”：

- 监听端口的 websockify 常驻，资源占用很小。
- 真正耗资源的 Xvnc 和 Edge 在有客户端连接时按需启动。
- 关闭应用窗口、切到其他标签页，或连续无人访问超过空闲超时后，自动回收 Xvnc 和 Edge；再次打开会自动恢复。

空闲回收时长由 `/etc/default/web-kiosk` 中的环境变量控制：

```text
FNDESK_IDLE_TIMEOUT=180
```

单位为秒，默认 180。设为 `0` 可关闭自动回收（只靠控制按钮或关闭窗口来回收）。

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
- `cmd/main`：Web Edge 服务入口。`start`/`stop`/`status`/`restart` 供 fnOS 调用，`web-up`/`web-down` 用于按需启停 Xvnc+Edge 会话（websockify 保持常驻）。
- `cmd/common`：安装、升级、卸载回调逻辑。
- `app/install-kiosk.sh`：FPK 安装时调用的系统依赖和本地显示器配置脚本。
- `app/server/fndesk-ws.py`：websockify 包装。提供图片剪贴板（`/clipboard/image`）、按需唤醒/空闲回收 Web 会话，以及控制 API（`/api/web/*`、`/api/local/*`、`/api/status`）。
- `app/server/fndesk-server.py`：依赖缺失或启动失败时的兜底状态页与控制接口。
- `app/novnc/fndesk.html`：noVNC 前端。负责精确适配窗口尺寸、中文输入法与剪贴板，以及右下角控制按钮。
- `app/window-sync.sh`：同步 Web Edge 窗口尺寸，使其铺满当前虚拟屏。
- `wizard/uninstall`：fnOS 应用中心卸载向导配置。

## 开发说明

开发过程中，编码工作主要由 **GPT-5.5** 模型完成。

## License

MIT License. 见 [LICENSE](./LICENSE)。
