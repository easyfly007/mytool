#!/usr/bin/env python3
"""
PDF 文件压缩工具
================
将 PDF 文件按指定质量等级压缩，在减小文件体积的同时尽量保持清晰度。

支持两种压缩引擎：
  1. Ghostscript（推荐，压缩效果最好）
  2. pikepdf + Pillow（纯 Python 方案，无需额外安装）

用法：
  python resize_pdf.py input.pdf                    # 默认中等质量
  python resize_pdf.py input.pdf -q high            # 高质量（文件较大）
  python resize_pdf.py input.pdf -q low             # 低质量（文件最小）
  python resize_pdf.py input.pdf -o output.pdf      # 指定输出文件名
  python resize_pdf.py input.pdf --dpi 150          # 指定目标 DPI
  python resize_pdf.py input.pdf --engine pikepdf   # 强制使用 pikepdf 引擎
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# 质量预设：(Ghostscript 预设名, JPEG 质量, 目标 DPI)
QUALITY_PRESETS = {
    "high":   ("printer",    75, 300),
    "medium": ("ebook",      55, 150),
    "low":    ("screen",     35, 72),
}


def get_file_size_str(path: str) -> str:
    size = os.path.getsize(path)
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    else:
        return f"{size / (1024 * 1024):.2f} MB"


def has_ghostscript() -> bool:
    return shutil.which("gs") is not None


def compress_with_gs(input_path: str, output_path: str, quality: str, dpi: int) -> bool:
    """使用 Ghostscript 压缩 PDF（效果最佳）。"""
    gs_preset = QUALITY_PRESETS[quality][0]
    cmd = [
        "gs",
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.5",
        f"-dPDFSETTINGS=/{gs_preset}",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        "-dColorImageDownsampleType=/Bicubic",
        f"-dColorImageResolution={dpi}",
        "-dGrayImageDownsampleType=/Bicubic",
        f"-dGrayImageResolution={dpi}",
        f"-dMonoImageResolution={dpi}",
        "-dAutoRotatePages=/None",
        f"-sOutputFile={output_path}",
        input_path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def compress_with_pikepdf(input_path: str, output_path: str, quality: str, dpi: int):
    """使用 pikepdf + Pillow 压缩 PDF 中的图片。"""
    try:
        import pikepdf
        from PIL import Image
    except ImportError:
        print("错误：需要安装依赖，请运行：pip install pikepdf Pillow")
        sys.exit(1)

    jpeg_quality = QUALITY_PRESETS[quality][1]

    pdf = pikepdf.Pdf.open(input_path)
    images_compressed = 0

    for page in pdf.pages:
        if "/Resources" not in page:
            continue
        resources = page["/Resources"]
        if "/XObject" not in resources:
            continue

        xobjects = resources["/XObject"]
        for key in list(xobjects.keys()):
            xobj = xobjects[key]
            if not isinstance(xobj, pikepdf.Stream):
                continue
            if xobj.get("/Subtype") != pikepdf.Name.Image:
                continue

            width = int(xobj.get("/Width", 0))
            height = int(xobj.get("/Height", 0))
            if width == 0 or height == 0:
                continue

            try:
                pil_image = _extract_image(xobj, width, height)
            except Exception:
                continue

            if pil_image is None:
                continue

            # 按 DPI 限制缩放图片
            scale = _calc_scale(pil_image, dpi, xobj)
            if scale < 1.0:
                new_w = max(1, int(pil_image.width * scale))
                new_h = max(1, int(pil_image.height * scale))
                pil_image = pil_image.resize((new_w, new_h), Image.LANCZOS)

            # 重新压缩为 JPEG
            if pil_image.mode in ("RGBA", "P", "LA"):
                background = Image.new("RGB", pil_image.size, (255, 255, 255))
                if pil_image.mode == "P":
                    pil_image = pil_image.convert("RGBA")
                background.paste(pil_image, mask=pil_image.split()[-1])
                pil_image = background
            elif pil_image.mode != "RGB":
                pil_image = pil_image.convert("RGB")

            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                pil_image.save(tmp_path, "JPEG", quality=jpeg_quality, optimize=True)
                with open(tmp_path, "rb") as f:
                    jpeg_data = f.read()
            finally:
                os.unlink(tmp_path)

            new_image = pikepdf.Stream(pdf, jpeg_data)
            new_image[pikepdf.Name.Type] = pikepdf.Name.XObject
            new_image[pikepdf.Name.Subtype] = pikepdf.Name.Image
            new_image[pikepdf.Name.Width] = pil_image.width
            new_image[pikepdf.Name.Height] = pil_image.height
            new_image[pikepdf.Name.ColorSpace] = pikepdf.Name.DeviceRGB
            new_image[pikepdf.Name.BitsPerComponent] = 8
            new_image[pikepdf.Name.Filter] = pikepdf.Name.DCTDecode

            xobjects[key] = new_image
            images_compressed += 1

    # 保存并压缩 PDF 流
    pdf.save(
        output_path,
        compress_streams=True,
        object_stream_mode=pikepdf.ObjectStreamMode.generate,
    )
    pdf.close()
    print(f"  已压缩 {images_compressed} 张图片")


def _extract_image(xobj, width: int, height: int):
    """从 PDF XObject 中提取 PIL Image。"""
    from PIL import Image
    import io

    raw = bytes(xobj.read_raw_bytes())
    filters = xobj.get("/Filter", None)

    # 处理 DCTDecode (JPEG)
    if filters == "/DCTDecode" or (isinstance(filters, list) and "/DCTDecode" in filters):
        return Image.open(io.BytesIO(raw))

    # 处理 FlateDecode (PNG-like)
    decoded = bytes(xobj.read_bytes())
    bpc = int(xobj.get("/BitsPerComponent", 8))
    cs = xobj.get("/ColorSpace")

    if cs == "/DeviceRGB" and bpc == 8:
        if len(decoded) >= width * height * 3:
            return Image.frombytes("RGB", (width, height), decoded[:width * height * 3])
    elif cs == "/DeviceGray" and bpc == 8:
        if len(decoded) >= width * height:
            return Image.frombytes("L", (width, height), decoded[:width * height])

    # 尝试用 pikepdf 内置方法
    try:
        import pikepdf
        pil_image = pikepdf.PdfImage(xobj).as_pil_image()
        return pil_image
    except Exception:
        return None


def _calc_scale(pil_image, target_dpi: int, xobj) -> float:
    """根据目标 DPI 计算缩放比例。"""
    # 简单估算：假设页面上图片按 72 DPI 基准显示
    current_effective_dpi = max(pil_image.width, pil_image.height) / 8.0  # 粗略估计
    if current_effective_dpi <= target_dpi:
        return 1.0
    return target_dpi / current_effective_dpi


def main():
    parser = argparse.ArgumentParser(
        description="PDF 文件压缩工具 - 减小体积，保持清晰度",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  %(prog)s document.pdf                     中等质量压缩
  %(prog)s document.pdf -q high             高质量压缩
  %(prog)s document.pdf -q low -o small.pdf 低质量压缩并指定输出
  %(prog)s document.pdf --dpi 120           自定义目标 DPI
        """,
    )
    parser.add_argument("input", help="输入 PDF 文件路径")
    parser.add_argument("-o", "--output", help="输出文件路径（默认：原文件名_compressed.pdf）")
    parser.add_argument(
        "-q", "--quality",
        choices=["high", "medium", "low"],
        default="medium",
        help="压缩质量：high=高质量/较大, medium=中等(默认), low=低质量/最小",
    )
    parser.add_argument("--dpi", type=int, help="目标图片 DPI（覆盖质量预设值）")
    parser.add_argument(
        "--engine",
        choices=["auto", "gs", "pikepdf"],
        default="auto",
        help="压缩引擎：auto=自动选择(默认), gs=Ghostscript, pikepdf=纯Python",
    )
    args = parser.parse_args()

    input_path = os.path.abspath(args.input)
    if not os.path.isfile(input_path):
        print(f"错误：文件不存在 - {input_path}")
        sys.exit(1)

    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        stem = Path(input_path).stem
        suffix = Path(input_path).suffix
        output_path = str(Path(input_path).parent / f"{stem}_compressed{suffix}")

    dpi = args.dpi if args.dpi else QUALITY_PRESETS[args.quality][2]

    original_size = os.path.getsize(input_path)
    print(f"输入文件：{input_path}")
    print(f"文件大小：{get_file_size_str(input_path)}")
    print(f"压缩质量：{args.quality} | 目标 DPI：{dpi}")
    print()

    # 选择压缩引擎
    use_gs = False
    if args.engine == "gs":
        if not has_ghostscript():
            print("错误：未找到 Ghostscript (gs)，请先安装。")
            sys.exit(1)
        use_gs = True
    elif args.engine == "auto":
        use_gs = has_ghostscript()
    # engine == "pikepdf" -> use_gs = False

    if use_gs:
        print("压缩引擎：Ghostscript")
        print("正在压缩...")
        success = compress_with_gs(input_path, output_path, args.quality, dpi)
        if not success:
            print("Ghostscript 压缩失败，回退到 pikepdf...")
            compress_with_pikepdf(input_path, output_path, args.quality, dpi)
    else:
        print("压缩引擎：pikepdf + Pillow")
        print("正在压缩...")
        compress_with_pikepdf(input_path, output_path, args.quality, dpi)

    if not os.path.isfile(output_path):
        print("错误：压缩失败，未生成输出文件。")
        sys.exit(1)

    compressed_size = os.path.getsize(output_path)
    ratio = (1 - compressed_size / original_size) * 100 if original_size > 0 else 0

    print()
    print(f"输出文件：{output_path}")
    print(f"压缩后大小：{get_file_size_str(output_path)}")
    if ratio > 0:
        print(f"体积减小：{ratio:.1f}%")
    else:
        print("提示：压缩后文件未变小，原文件可能已是最优压缩状态。")


if __name__ == "__main__":
    main()
