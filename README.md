# Fancy DWM：Ubuntu 一键配置

把当前的 Luke Smith 风格 DWM、终端、中文输入法和系统托盘部署到另一台 Ubuntu 桌面电脑。所有用户名、家目录和硬件状态在目标机器上读取；不携带原电脑的密码、浏览器资料、SSH 密钥、终端历史或输入法个人词库。

## 新电脑安装

从你的 GitHub 仓库克隆，部署本次完整配置（含 FortiClient 与真正休眠）：

```sh
git clone https://github.com/Flowming-ai/fancy_dwm.git
cd fancy_dwm
sh install.sh --full
```

`--full` 会先检查硬件和启动条件。休眠自动配置目前要求未加密的普通 ext4 根分区、GRUB、关闭 Secure Boot/lockdown，并支持 ACPI platform 休眠；不支持的机器会明确停止，不猜测磁盘偏移。FortiClient 的固定安装包仅有 amd64。只安装通用桌面、150% 缩放和 Teams 启动器时，运行 `sh install.sh`，不带 `--full`。


目标是 **Ubuntu Desktop 24.04 / 26.04，amd64 或 arm64**，需要可用的图形登录管理器、网络和 sudo 权限。其他 Ubuntu 版本会停止并提示，不保证所有版本或显卡驱动都兼容。安装源包括 Ubuntu 软件源和 GitHub 官方发布地址。

将整个安装包复制到新电脑，在普通用户的终端执行：

```sh
tar -xzf ubuntu-dwm-setup.tar.gz
cd ubuntu-dwm-setup
sh install.sh
```

不要在 `sh` 前加 `sudo`。脚本需要提权时会提示输入目标电脑的 sudo 密码。首次下载字体、插件及安装依赖需要联网；这是可携带的在线安装包，不是离线 Ubuntu 镜像。

完成后保存工作，注销并重新登录。脚本会为当前用户设置默认 DWM 会话；若登录管理器仍显示旧选择，在齿轮菜单中选择一次 **DWM**。不会自动注销或重启。GNOME 仍可在登录界面选择。

只检查安装包及系统条件（不安装、不下载、不休眠）：

```sh
sh install.sh --check
# 同时检查可选 VPN 与休眠模块的本机条件
sh install.sh --check --full
```

保留原有默认登录桌面：

```sh
sh install.sh --skip-default-session
```

按需选择功能：

```sh
sh install.sh --scale 125                 # 支持 100/125/150/175/200，默认 150
sh install.sh --with-forticlient          # 桌面 + VPN 客户端
sh install.sh --with-hibernation          # 桌面 + 真正休眠
```

## 包含内容

| 功能 | 安装与配置 |
| --- | --- |
| 桌面 | 固定版本的 Luke DWM、st、dmenu、dwmblocks 源码，现场编译 |
| 系统托盘 | 适配后的 XEmbed 托盘，固定最右侧显示器，保留状态栏点击与重载 |
| 终端 | st；Kitty 使用 JetBrainsMono Nerd Font，背景透明度 0.85 |
| Shell | Zsh 默认 Shell、Oh My Zsh、命令建议、语法高亮、Starship 彩色提示符 |
| 命令行 | fastfetch、eza、bat、btop；`ls` 使用 eza，`cat` 使用 bat |
| 启动器与通知 | Rofi、dmenu、Dunst、Papirus 图标 |
| 中文 | Fcitx5 拼音、GTK/Qt 前端、中文字体、候选预测；Ctrl+Space 切换 |
| 桌面效果 | Picom 透明、阴影与淡入淡出；保留当前壁纸 |
| 截图 | Flameshot 托盘；Print/Shift+Print 保留当前 maim 截图快捷键 |
| 屏保与锁屏 | XScreenSaver 在 DWM 会话启动，锁屏入口保留在会话菜单 |
| 日常工具 | lf、Neovim、音量、亮度、网络与显示器工具 |
| 显示缩放 | 默认 150%：Xft/GTK/Qt/Rofi、鼠标指针与 XSettings；目标机器安装 xsettingsd |
| Teams | Microsoft Teams 官方网页启动器；优先 Chrome/Edge/Chromium 独立窗口，其他浏览器回退网页 |
| 真正休眠（可选） | 动态计算 swap 容量、UUID 与偏移，识别 Dracut/initramfs-tools；platform/S4 与最小内存快照修正 |
| FortiClient（可选） | 官方 VPN-only 安装包，SHA-256 检查，APT 自动补齐 libnss3-tools 等依赖，启用后台服务 |

当前状态栏使用 **dwmblocks**，不同时启动早期方案中的 slstatus。输入法为开源 Fcitx5 拼音，未打包搜狗闭源安装器。已有个人词库保持原样。

## 常用快捷键

**Super 就是 Win 键。**

| 快捷键 | 功能 |
| --- | --- |
| **Win+空格** | 将当前平铺窗口提升为主窗口 |
| Win+Shift+空格 | 切换当前窗口的浮动状态 |
| Win+t | 切换左右平铺布局 |
| Win+j / k | 切换焦点窗口 |
| Win+h / l | 缩小 / 放大主区域 |
| Win+Enter | st 终端 |
| Alt+Shift+Enter / Ctrl+Alt+t | 备用终端快捷键 |
| Win+Shift+d | Kitty 终端 |
| Alt+d | Rofi 应用启动器 |
| Ctrl+Space | 中英文输入切换 |
| Ctrl+Shift+c / v | 终端复制 / 粘贴 |
| Win+Shift+Backspace | 重载 DWM，保留打开的窗口 |
| Win+Backspace | 会话菜单，含锁屏、真正休眠与注销 |
| Win+F1 | 完整快捷键说明 |

浮动窗口需要先按 Win+Shift+空格，再按 Win+空格才能提升到平铺主区域。若当前布局没有主区域，可先按 Win+t。

## 休眠与 VPN 的使用边界

休眠模块不复制这台电脑的 UUID、swap 偏移、固定 36 GiB 容量或用户名。新机器根据 RAM 分配专用 swap，保留已有 swap，并在改动前备份启动配置和 initramfs；失败时恢复配置，保留已创建的 swap，避免 `swapoff` 引发内存不足。普通重启一次后用 `~/.local/bin/dwm-hibernate --check` 检查，再通过 Win+Backspace 的菜单确认休眠。未配置的机器会显示原因，不会把“睡眠”冒充“真正休眠”。

本次保留的最新策略是 **ACPI S4/platform + image_size=0**。键鼠唤醒还依赖固件、端口和 USB 待机供电；脚本不承诺所有主板都能实现，也不批量打开未知设备的唤醒权限。NVIDIA 驱动的休眠服务、显存保存与临时存储仍需目标机器的驱动配置配合。详见 [休眠模块](scripts/hibernate/README.md)。

FortiClient 固定为本机已使用的 VPN-only 7.4.3.5411，保持已有健康安装版本，避免自动升级/降级和升级脚本中断现有 VPN。固定版本用于重现本机配置，并非“永远最新”的承诺；后续更新需重新验证下载与哈希。新机器安装后自行填写学校/公司的 VPN 网关并完成 SAML 登录；不会携带 VPN 数据库、密码或证书。26.04/DWM 的本机使用记录不等于厂商兼容认证，厂商该版支持列表见 [Fortinet 7.4.3 文档](https://docs.fortinet.com/document/forticlient/7.4.3/linux-release-notes/136392/product-integration-and-support)。

Teams 入口使用目标电脑现有浏览器，不复制浏览器账户或强制安装 Chrome。Grammarly/LanguageTool 没有完成部署，因此不在安装内容中；Smart Academic Reader 是另一个项目，也未混入此桌面仓库。

## 配置位置与备份

- 源码：`~/.local/src/larbs-ubuntu/`。
- Shell 美化：`~/.config/dwm-shell/zshrc`；个人扩展可写 `~/.zshrc.local`。
- 输入法：`~/.config/fcitx5/`。
- Kitty / Picom / Rofi：`~/.config/` 下的对应目录。
- 本次安装的备份与日志：`~/.local/state/ubuntu-dwm-setup/时间戳/`，安装结束时会输出确切位置。
- 缩放：`~/.Xresources`、`~/.config/xsettingsd/`、`~/.config/dwm-scale/`。
- Teams：`~/.local/bin/teams-web`。
- 休眠系统备份与独立回滚：`/var/backups/dwm-hibernate/portable-时间戳/`。
- DWM 会话日志：`~/.local/state/dwm/`。

重复安装会备份并重新应用仓库中管理的桌面配置；请先把希望保留的定制改入仓库。已有 `.zshrc` 与 `.profile` 通过受管理区块接入配置，保留其他内容。桌面回滚不会卸载 apt 软件包，也不撤销可选休眠的启动设置。休眠有独立 root 备份和回滚脚本，见模块说明。FortiClient 包和后台服务保留；安装前的包/服务状态记录在该次备份的 `extras/forticlient-before.json`，不包含 VPN 资料。

```sh
# 先查看将恢复的文件。
sh scripts/rollback.sh "$HOME/.local/state/ubuntu-dwm-setup/实际备份目录"
# 确认预览后，执行恢复。
sh scripts/rollback.sh "$HOME/.local/state/ubuntu-dwm-setup/实际备份目录" --apply
```

## 继续用 Git 管理

本机交付包含独立的 Git 仓库；另附 `.bundle` 可完整携带提交历史。新电脑可以直接解压安装，也可以从 bundle 克隆：

```sh
git clone ubuntu-dwm-setup.bundle ubuntu-dwm-setup
cd ubuntu-dwm-setup
sh install.sh
```

修改配置后，检查内容并更新快照校验清单，然后提交：

```sh
python3 scripts/update-checksums.py
sh install.sh --check
git add .
git commit -m "Update my desktop configuration"
```

不要将密码、密钥和个人浏览器目录加入仓库。远端为 `https://github.com/Flowming-ai/fancy_dwm.git`。安装器包含 GitHub CLI；需要从新电脑推送时先运行 `gh auth login --hostname github.com --git-protocol https --web`，自行在 GitHub 页面完成设备码授权。认证信息由 GitHub CLI 在该电脑本地管理，不加入此仓库。提交后可运行 `git push origin main`。

更新可拷贝安装包（要求工作区已提交且完整性检查通过）：

```sh
sh scripts/package.sh ../outputs
```

这会重新生成 `ubuntu-dwm-setup.tar.gz`、`ubuntu-dwm-setup.bundle` 和各自的 SHA-256 文件。GitHub 仓库只保存配置和源码，不提交下载缓存、专有 VPN 二进制或本机备份。

## 验证与来源

见 [验证记录](VALIDATION.md)、[来源与许可证](NOTICE.md) 和 [固定下载版本](scripts/downloads.json)。源码自带上游许可证。固定下载文件会验证 SHA-256，插件使用固定 Git 提交；Ubuntu 软件包仍随软件源更新。

开发时可在临时目录中编译，完全不安装：

```sh
sh scripts/build-check.sh
python3 -m unittest discover -s tests -v
```
