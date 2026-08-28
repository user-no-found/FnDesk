# FnDesk · fnOS 本地 Edge 控制台

FnDesk 是为 fnOS 打包的 Microsoft Edge 本地显示器控制工具。应用中心打开的是 Web 控制台；真实 Microsoft Edge 只在本地显示器 tty1 上运行，并且只在用户从控制台启动时运行。

它不安装 GNOME、KDE、XFCE 等完整桌面环境，只使用最小图形栈在本地显示器上启动 Edge。

## 它能做什么

- **Web 控制台**：在应用中心打开 FnDesk 后，可以启动、关闭、重启本地 Edge，并查看日志。
- **本地显示器 Edge**：在 tty1 上启动真实 Microsoft Edge，不在 Web 端运行虚拟浏览器。
- **手动启停**：本地 Edge 默认不自动启动；从控制台点击启动、关闭或重启。
- **单显卡隔离**：启动时只选择带物理连接器的 DRM 卡，避免同时探测无显示输出的计算卡。
- **无显示器安全退出**：通过 Wayland 注册表判断 Cage 是否发布了有效输出；未连接显示器
  或 modeset 失败时快速退出，不读取可能阻塞的 DRM sysfs 状态文件。
- **安全控制面**：Web 状态查询不读取 DRM/VT 状态，不调用 `fgconsole`；启停请求不会阻塞 HTTP 线程。
- **中文日志摘要**：控制台默认把 systemd、seatd、Cage 的关键事件整理为中文；诊断时仍可切换到完整原始日志。
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
sudo systemctl --no-block start fndesk-local.service
sudo systemctl --no-block stop fndesk-local.service
sudo systemctl --no-block restart fndesk-local.service
```

## 控制台功能

控制台提供这些常用操作：

- **启动**：提交启动本地显示器 Edge 的请求；独立 seatd 会接管 tty1。
- **关闭**：停止本地 Edge 服务。
- **重启**：异步提交重启本地 Edge 服务的请求。
- **重置失败**：执行 `systemctl reset-failed fndesk-local.service`。
- **日志查看**：查看 `fndesk-local.service` 和控制台自身日志。

控制台不提供 `fgconsole`、`chvt` 或强制杀死 Cage 的入口。这些操作在 DRM/KMS
异常时可能进入不可中断内核等待，并进一步阻塞 systemd。

本地 Edge 的 systemd 服务名：

```text
fndesk-local.service
```

显示器电源策略服务名：

```text
fndesk-display-power.service
```

## DRM 兼容与安全策略

FnDesk 默认针对 fnOS 的 AMD 核显和 Debian 12 自带 Cage/wlroots 组合启用保守设置：

- 禁用全局的 `Restart=always` seatd，并使用 `seatd-launch` 为每次本地桌面创建独立
  seatd；完整卸载时会恢复全局 seatd 的开机启用状态。
- Cage 只使用一个带物理连接器的 DRM 卡，并采用单显示器模式。
- 优先使用 `/usr/lib/x86_64-linux-gnu` 中与系统 GBM/EGL 配套的 `libdrm`，避免与
  `/opt/amdgpu` 的库混装。
- 默认设置 `WLR_DRM_NO_ATOMIC=1` 和 `WLR_DRM_NO_MODIFIERS=1`，规避旧 wlroots
  在新 amdgpu 内核上的 atomic modeset/formatter 兼容问题。
- 默认使用 wlroots 的 pixman 软件渲染并禁用 Edge GPU，避免旧 Mesa 探测不受支持的
  Strix GPU 或无显示输出的 NVIDIA 计算卡。
- systemd 不再执行 `chvt`、`TTYReset` 或 `TTYVHangup`；服务仍以 tty1 作为控制终端，
  但 PID 1 不参与停止时的控制台复位。

安装后可以在 `/etc/default/fndesk` 调整以下高级选项：

```bash
# 留空时自动选择带物理连接器的 DRM 卡；也可指定 /dev/dri/card0 或 by-path 路径。
FNDESK_DRM_DEVICE=

# 设为 0 可逐项关闭兼容模式。
FNDESK_DRM_LEGACY=1
FNDESK_DRM_NO_MODIFIERS=1
FNDESK_USE_SYSTEM_LIBDRM=1
FNDESK_SOFTWARE_RENDERER=1
```

Web 控制台不会实时读取 `/sys/class/drm/*/status` 或当前 VT；显示器故障以
`fndesk-local.service` 日志为准。这是有意的安全设计，因为 KMS 卡死后这些“只读”查询
也可能永久阻塞。

启动器会在 Cage 建立 Wayland socket 后使用 `wayland-info` 检查标准 `wl_output`。
如果没有输出，服务以状态 75 安全退出；该检查只访问本地 Wayland socket，不直接查询
DRM 或 VT。启动器同时显式恢复 kiosk 用户的 `HOME`、`USER` 和 `LOGNAME`，避免降权后
Edge 误用 `/root`。

每次启动前还会检查 `/run/seatd.sock`：只有确认 socket 文件无人监听时才清理残留；如果
仍有服务监听或路径不是 socket，则拒绝删除并安全失败。这使连续启动测试不会被上一次
私有 seatd 延迟清理留下的文件干扰。

## 从源码构建

```bash
bash build_fpk.sh
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
