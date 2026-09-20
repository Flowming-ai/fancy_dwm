# Ubuntu DWM 一键配置

把当前的 Luke Smith 风格 DWM、终端、中文输入法和系统托盘部署到另一台 Ubuntu 桌面电脑。所有用户名、家目录和硬件状态在目标机器上读取；不携带原电脑的密码、浏览器资料、SSH 密钥、终端历史或输入法个人词库。

## 新电脑安装

目标是 **Ubuntu Desktop 24.04 / 26.04，amd64 或 arm64**，需要可用的图形登录管理器、网络和 sudo 权限。其他 Ubuntu 版本会停止并提示，不保证所有版本或显卡驱动都兼容。安装源包括 Ubuntu 软件源和 GitHub 官方发布地址。

将整个安装包复制到新电脑，在普通用户的终端执行：

```sh
tar -xzf ubuntu-dwm-setup.tar.gz
cd ubuntu-dwm-setup
sh install.sh
```

不要在 `sh` 前加 `sudo`。脚本需要提权时会提示输入目标电脑的 sudo 密码。首次下载字体、插件及安装依赖需要联网；这是可携带的在线安装包，不是离线 Ubuntu 镜像。

完成后保存工作，注销并重新登录。脚本会为当前用户设置默认 DWM 会话；若登录管理器仍显示旧选择，在齿轮菜单中选择一次 **DWM**。不会自动注销或重启。GNOME 仍可在登录界面选择。

只检查安装包及系统条件：

```sh
sh install.sh --check
```

保留原有默认登录桌面：

```sh
sh install.sh --skip-default-session
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
| Win+Backspace | 会话菜单，含锁屏与注销 |
| Win+F1 | 完整快捷键说明 |

浮动窗口需要先按 Win+Shift+空格，再按 Win+空格才能提升到平铺主区域。若当前布局没有主区域，可先按 Win+t。

## 配置位置与备份

- 源码：`~/.local/src/larbs-ubuntu/`。
- Shell 美化：`~/.config/dwm-shell/zshrc`；个人扩展可写 `~/.zshrc.local`。
- 输入法：`~/.config/fcitx5/`。
- Kitty / Picom / Rofi：`~/.config/` 下的对应目录。
- 本次安装的备份与日志：`~/.local/state/ubuntu-dwm-setup/时间戳/`，安装结束时会输出确切位置。
- DWM 会话日志：`~/.local/state/dwm/`。

重复安装会备份并重新应用仓库中管理的桌面配置；请先把希望保留的定制改入仓库。已有 `.zshrc` 与 `.profile` 通过受管理区块接入配置，保留其他内容。回滚不会卸载 apt 软件包，以免连带删除别的软件依赖。

```sh
# 先查看将恢复的文件。
sh scripts/rollback.sh "$HOME/.local/state/ubuntu-dwm-setup/实际备份目录"
# 确认预览后，执行恢复。
sh scripts/rollback.sh "$HOME/.local/state/ubuntu-dwm-setup/实际备份目录" --apply
```

## 继续用 Git 管理

本机交付包含独立的 Git 仓库；另附 `.bundle` 可完整携带初始提交历史。新电脑可以直接解压安装，也可以从 bundle 克隆：

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

不要将密码、密钥和个人浏览器目录加入仓库。Git 远端未配置，需要时可自行添加 GitHub 或其他托管地址。

## 验证与来源

见 [验证记录](VALIDATION.md)、[来源与许可证](NOTICE.md) 和 [固定下载版本](scripts/downloads.json)。源码自带上游许可证。固定下载文件会验证 SHA-256，插件使用固定 Git 提交；Ubuntu 软件包仍随软件源更新。

开发时可在临时目录中编译，完全不安装：

```sh
sh scripts/build-check.sh
python3 -m unittest discover -s tests -v
```
