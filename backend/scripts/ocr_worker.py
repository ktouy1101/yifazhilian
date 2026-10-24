"""One isolated, local, bounded OCR invocation. Input image bytes, output JSON.

RapidOCR 1.4.4 includes its PP-OCR models in the installed wheel. Disable
telemetry and socket connections: a missing model fails, never downloads.
"""
from contextlib import redirect_stdout
from io import BytesIO
import json
import socket
import sys
import time


def no_network(*args, **kwargs):
    raise RuntimeError("OCR worker has no network access")


def main():
    socket.socket.connect = no_network
    socket.socket.connect_ex = no_network
    socket.create_connection = no_network
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    import numpy as np
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR
    started = time.monotonic()
    data = sys.stdin.buffer.read(80 * 1024 * 1024 + 1)
    with Image.open(BytesIO(data)) as image:
        pixels = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
    with redirect_stdout(sys.stderr):
        engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
        results, _ = engine(pixels)
    lines = []
    for index, (points, text, score) in enumerate(results or []):
        lines.append({"id": f"line-{index + 1}", "text": text[:300], "confidence": float(score),
                      "box": [min(p[0] for p in points), min(p[1] for p in points),
                              max(p[0] for p in points), max(p[1] for p in points)]})
    json.dump({"engine": "RapidOCR 1.4.4 / PP-OCRv4 / CPU", "lines": lines[:500],
               "elapsed_ms": round((time.monotonic() - started) * 1000)}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
