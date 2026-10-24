"""CPU OCR subprocess boundary. No AI provider, cloud OCR or runtime downloads."""
from io import BytesIO
import json
import os
from pathlib import Path
import re
from statistics import median
import subprocess
from threading import BoundedSemaphore

from PIL import Image, ImageOps

BACKEND = Path(__file__).resolve().parents[2]
_slots = BoundedSemaphore(2)


class OCRError(Exception):
    pass


def worker_python():
    default = BACKEND / ".ocr-venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return Path(os.getenv("YIFAZHILIAN_OCR_PYTHON", str(default)))


class LocalOCR:
    def recognize(self, image: bytes) -> dict:
        python = worker_python()
        if not python.is_file():
            raise OCRError("本地OCR环境未安装，请运行 setup-ocr.ps1；也可对照原图手填。")
        if not _slots.acquire(blocking=False):
            raise OCRError("本地OCR正在处理其他照片，请稍后重试。")
        try:
            env = {key: value for key, value in os.environ.items()
                   if not any(word in key.upper() for word in ("KEY", "SECRET", "TOKEN", "PROXY"))}
            env.update(PYTHONUTF8="1", ORT_DISABLE_TELEMETRY="1")
            result = subprocess.run([str(python), str(BACKEND / "scripts" / "ocr_worker.py")],
                                    input=image, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=75, env=env,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if result.returncode:
                raise OCRError("本地OCR未完成，请重试、重拍或对照原图手填。")
            data = json.loads(result.stdout)
            if not data.get("lines"):
                raise OCRError("没有识别到文字，请拍清晰完整的检验单，或手填核对。")
            return data
        except subprocess.TimeoutExpired as error:
            raise OCRError("本地OCR超时，未归档；可稍后重试或手填。") from error
        except (OSError, ValueError) as error:
            raise OCRError("本地OCR运行异常，未归档；请检查环境或手填。") from error
        finally:
            _slots.release()


def upright_png(data):
    """An OCR/display derivative only; the original bytes are never overwritten."""
    with Image.open(BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        out = BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()


def empty_draft():
    return {"title": "检验单", "record_type": "检验单", "record_date": "", "institution": "",
            "visit": "", "metadata_confirmed": False, "fields": []}


def parse_report(result):
    """Conservative table extraction. Never infer missing numeric values or units.

    Column positions come from this image's detected header, not hard-coded lab
    ranges. Unstructured lines remain available for full-image/manual checking.
    """
    draft = empty_draft()
    lines = result.get("lines", [])
    groups = []
    for line in sorted(lines, key=lambda item: ((item["box"][1] + item["box"][3]) / 2, item["box"][0])):
        box = line["box"]
        center = (box[1] + box[3]) / 2
        group = next((g for g in reversed(groups) if abs(g["y"] - center) <= max(8, (box[3] - box[1]) * .55)), None)
        if group is None:
            group = {"y": center, "lines": []}
            groups.append(group)
        group["lines"].append(line)
        # A wrapped header such as “序 / 号” must not anchor the entire row
        # to the first, unusually high token and split “项目名称” from “结果”.
        group["y"] = median((item["box"][1] + item["box"][3]) / 2 for item in group["lines"])
    aliases = {"name": ("项目", "检验项目", "项目名称"), "result": ("结果", "检验结果", "测定值"),
               "unit": ("单位",), "reference": ("参考范围", "参考区间", "参考值")}
    header_aliases = aliases | {"_sequence": ("序号", "编号", "序", "号"),
                                "_flag": ("标志", "标记", "提示", "异常标志")}
    columns = None
    for group in groups:
        ordered = sorted(group["lines"], key=lambda item: item["box"][0])
        text = " ".join(item["text"] for item in ordered)
        if "医院" in text or "检验中心" in text:
            if not draft["institution"]:
                draft["institution"] = text[:120]
        if "日期" in text or "时间" in text:
            match = re.search(r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})", text)
            if match and not draft["record_date"]:
                draft["record_date"] = f"{match[1]}-{int(match[2]):02d}-{int(match[3]):02d}"
        found = {}
        for item in ordered:
            for key, names in header_aliases.items():
                if item["text"].replace(" ", "").rstrip(":：") in names:
                    found[key] = item["box"][0]
        if "name" in found and "result" in found:
            columns = sorted(found.items(), key=lambda item: item[1])
            continue
        if not columns:
            continue
        values = {key: [] for key in aliases}
        for item in ordered:
            x = item["box"][0]
            # Nearest left-aligned column start tolerates varying token widths.
            key = min(columns, key=lambda col: abs(x - col[1]))[0]
            # Keep sequence numbers and printed flags in raw text/crops,
            # without mixing them into names, numeric results or ranges.
            if key in values:
                values[key].append(item["text"])
        values = {key: " ".join(parts) for key, parts in values.items()}
        if not values["name"] or not values["result"] or not re.search(r"\d|阴性|阳性|[+-]", values["result"]):
            continue
        if any(word in values["name"] for word in ("审核", "医生", "备注", "报告时间", "采样")):
            continue
        confidence = min(item["confidence"] for item in ordered)
        box = [min(i["box"][0] for i in ordered), min(i["box"][1] for i in ordered),
               max(i["box"][2] for i in ordered), max(i["box"][3] for i in ordered)]
        draft["fields"].append({"id": f"ocr-{len(draft['fields']) + 1}", **values,
                                "source_ids": [i["id"] for i in ordered], "box": box,
                                "confidence": confidence, "original": dict(values), "confirmed": False})
        if len(draft["fields"]) >= 100:
            break
    return draft
