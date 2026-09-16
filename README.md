# 环形拼接件 DXF 生成器

这是一个中文 Tkinter 桌面界面，用于生成激光切割用的环形扇区 DXF。

## Windows 运行

不需要在目标电脑安装 Python。GitHub Actions 会自动构建 Windows EXE：

1. 将本项目上传到 GitHub。
2. 打开仓库的 **Actions** 页面。
3. 选择 **构建 Windows EXE**。
4. 点击 **Run workflow**，或推送到 `main` / `master` 分支。
5. 工作流完成后，在运行页面底部下载 `环形拼接件生成器-windows`。
6. 解压 ZIP，双击 `环形拼接件生成器.exe`。

目标 Windows 电脑不需要 Python、pip 或浏览器。
默认 DXF 输出到 EXE 同级的 `输出` 文件夹，不会写入 PyInstaller 的 `_internal` 文件夹。
关闭 Tkinter 窗口后，EXE 会自动退出；再次双击不会创建重复实例。

## 本地构建

如果在 Windows 构建电脑上操作，也可以双击 `build_windows_exe.bat`。

## 主要参数

- 单文件模式只生成一个可复制排版的扇区 DXF。
- 梯形缺口高度固定为 8 mm；“缺口尺寸”改为梯形下底占切割环宽的百分比，默认 25%。
- 矩形缺口仍以毫米输入缺口高度。
- 默认激光间隙为 0.3 mm。
- 输入板厚 3 mm 时，切割内径增加 6 mm，切割外径减少 6 mm。
- 文件名示例：`203x262+6补.dxf`。
- 默认将外弧和一侧咬合边写成一条切割路径，将内弧和另一侧咬合边写成另一条切割路径，便于激光器分开走刀。
- 如果激光软件必须使用独立 `ARC`/`LINE` 实体，可在命令行使用 `--no-split-paths`。
