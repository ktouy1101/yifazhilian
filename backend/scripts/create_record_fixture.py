"""Generate a wholly synthetic, non-clinical OCR test chart; no patient data."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def create(output):
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    if not font_path.is_file():
        raise SystemExit("Supply a CJK font at C:/Windows/Fonts/msyh.ttc for this Windows fixture generator")
    font = ImageFont.truetype(str(font_path), 32)
    title = ImageFont.truetype(str(font_path), 42)
    image = Image.new("RGB", (1500, 1100), "white")
    draw = ImageDraw.Draw(image)
    draw.text((80, 55), "合成演示医院 · 检验报告", fill="#132930", font=title)
    draw.text((80, 135), "合成测试资料，不用于诊疗", fill="#51686f", font=font)
    draw.text((80, 205), "报告日期：2026-10-17", fill="black", font=font)
    rows = [("检验项目", "结果", "单位", "参考区间"),
            ("白细胞计数", "6.30", "10^9/L", "3.50-9.50"),
            ("红细胞计数", "4.20", "10^12/L", "3.80-5.10"),
            ("血红蛋白", "128", "g/L", "115-150"),
            ("血小板计数", "215", "10^9/L", "125-350"),
            ("C反应蛋白", "<5.0", "mg/L", "0-8.0")]
    for index, row in enumerate(rows):
        y = 320 + index * 90
        for x, text in zip((80, 620, 850, 1120), row):
            draw.text((x, y), text, font=font, fill="black")
        draw.line((80, y + 65, 1420, y + 65), fill="#c4d3d7", width=2)
    draw.text((80, 940), "以上全部为程序生成的测试文字与数值", font=font, fill="#51686f")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


if __name__ == "__main__":
    import sys
    create(sys.argv[1] if len(sys.argv) > 1 else "backend/fixtures/records-m03/synthetic-lab.png")
