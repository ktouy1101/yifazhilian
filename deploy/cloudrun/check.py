"""上传前自检：确认云托管配置填全了。

用法（项目根目录）：
    .\\backend\\.venv\\Scripts\\python.exe deploy\\cloudrun\\check.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "miniprogram" / "config" / "index.js"


def main() -> int:
    text = CONFIG.read_text(encoding="utf-8")
    enabled = re.search(r"enabled:\s*(true|false)", text)
    env = re.search(r"env:\s*'([^']*)'", text)
    service = re.search(r"service:\s*'([^']*)'", text)

    problems: list[str] = []
    if not enabled or enabled.group(1) != "true":
        problems.append("miniprogram/config/index.js 里 cloudRun.enabled 还是 false")
    if not env or not env.group(1).strip():
        problems.append("cloudRun.env 没填（云托管环境 ID）")
    if not service or not service.group(1).strip():
        problems.append("cloudRun.service 没填（云托管服务名）")

    print("云托管配置检查")
    print(f"  enabled : {(enabled.group(1) if enabled else '未找到')}")
    print(f"  env     : {(env.group(1) if env else '未找到') or '(空)'}")
    print(f"  service : {(service.group(1) if service else '未找到') or '(空)'}")

    if problems:
        print("\n不能直接上传，需要先处理：")
        for item in problems:
            print("  -", item)
        return 1

    print("\n配置完整，可以编译上传并把该版本设为体验版。")
    print("别忘了云托管控制台里也配好环境变量（见 deploy/cloudrun/env.cloudrun）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
