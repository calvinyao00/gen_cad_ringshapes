# 环形拼接件 DXF 生成器

这是一个中文本地浏览器界面，用于生成激光切割用的环形扇区 DXF。

## Windows 运行

不需要在目标电脑安装 Python。GitHub Actions 会自动构建 Windows EXE：

1. 将本项目上传到 GitHub。
2. 打开仓库的 **Actions** 页面。
3. 选择 **构建 Windows EXE**。
4. 点击 **Run workflow**，或推送到 `main` / `master` 分支。
5. 工作流完成后，在运行页面底部下载 `环形拼接件生成器-windows`。
6. 解压 ZIP，双击 `环形拼接件生成器.exe`。

目标 Windows 电脑不需要 Python、pip 或其他 Python 依赖，只需要浏览器。
默认 DXF 输出到 EXE 同级的 `输出` 文件夹，不会写入 PyInstaller 的 `_internal` 文件夹。

## 本地构建

如果在 Windows 构建电脑上操作，也可以双击 `build_windows_exe.bat`。

## 主要参数

- 单文件模式只生成一个可复制排版的扇区 DXF。
- 自动缺口比例为径向环宽的 25%。
- 默认激光间隙为 0.3 mm。
- 输入板厚 3 mm 时，切割内径增加 6 mm，切割外径减少 6 mm。
- 文件名示例：`203x262+6补.dxf`。
