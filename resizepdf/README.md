# PDF 压缩工具

减小 PDF 文件体积，同时尽量保持清晰度。

## 安装

### 1. 安装 Python 依赖

```bash
pip install pikepdf Pillow
```

### 2. 安装 Ghostscript（可选，推荐）

Ghostscript 压缩效果更好。如果未安装，程序会自动使用纯 Python 方案。

- **Ubuntu/Debian**: `sudo apt install ghostscript`
- **macOS**: `brew install ghostscript`
- **Windows**: 从 [官网](https://www.ghostscript.com/releases/gsdnld.html) 下载安装

## 使用方法

```bash
# 基本用法（默认中等质量）
python resize_pdf.py input.pdf

# 指定输出文件
python resize_pdf.py input.pdf -o output.pdf

# 选择压缩质量
python resize_pdf.py input.pdf -q high      # 高质量，适合打印
python resize_pdf.py input.pdf -q medium    # 中等质量（默认），适合屏幕阅读
python resize_pdf.py input.pdf -q low       # 最小体积，适合邮件发送

# 自定义目标 DPI
python resize_pdf.py input.pdf --dpi 120

# 指定压缩引擎
python resize_pdf.py input.pdf --engine gs       # 强制使用 Ghostscript
python resize_pdf.py input.pdf --engine pikepdf  # 强制使用纯 Python 方案
```

不指定 `-o` 时，输出文件自动保存为 `原文件名_compressed.pdf`，不会覆盖原文件。

## 质量等级说明

| 等级 | JPEG 质量 | 目标 DPI | 适用场景 |
|------|----------|---------|---------|
| high | 75 | 300 | 需要打印 |
| medium | 55 | 150 | 屏幕阅读 |
| low | 35 | 72 | 浏览/邮件发送 |

## 压缩引擎

| 引擎 | 优点 | 缺点 |
|------|------|------|
| Ghostscript | 压缩效果最好，支持全面 | 需要额外安装 |
| pikepdf + Pillow | 纯 Python，无需额外安装 | 仅压缩图片，效果稍弱 |

默认自动选择：检测到 Ghostscript 则优先使用，否则使用 pikepdf。
