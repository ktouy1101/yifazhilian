# 演示片素材与复现方式

## 成片
- `demo-28s.mp4`：1920×1080 / 30fps / 28 秒 / H.264 + AAC
- `contact-sheet.png`：六个镜头关键帧

## 复现
```bash
# 1. 灌演示数据（本地后端需跑在 127.0.0.1:8000，DEMO_AUTH=1）
backend/.venv/Scripts/python.exe .work/seed-video-demo.py      # 6 条导诊路线
backend/.venv/Scripts/python.exe .work/seed-people-legal.py    # 志愿者 / 病历 / 工单

# 2. 渲染成片（脚本内按镜头组织，改文案只改 SCENES）
backend/.venv/Scripts/python.exe .work/video/render.py --frames  # 只出预览帧
backend/.venv/Scripts/python.exe .work/video/render.py           # 出完整 mp4
```

## 分镜与文案
见 `../video-plan.md`，其中含 AE 工作流与数据准备清单。

## 说明
- 画面里的数字（6 条路线 / 4 名志愿者 / 3 类病历）来自后台真实查询，不是写死的
- 背景音乐由 `render.py` 里的 `make_bed()` 程序生成，无版权风险；如需更有情绪的配乐，替换 `bed.wav` 即可
