# M03 合成检验单

`synthetic-lab.png` 由 `backend/scripts/create_record_fixture.py` 使用 Pillow 绘制，不含患者资料、姓名或医院真实标识，仅用于软件验收。可从小程序相册选择该图，或拍摄打印件测试相机链路。

固定预期：5项；结果依次为 `6.30`、`4.20`、`128`、`215`、`<5.0`；日期 `2026-10-17`。

图中 `10^9/L`、`10^12/L` 的 `^` 在当前OCR实测被识别为 `~`，即便置信度较高仍会出错。这是刻意保留的核对用例：按原图修正单位并逐项确认，归档后查看原识别值及版本变化。不要把合成参考区间用于真实临床判断。

再生成：`backend/.venv/Scripts/python.exe backend/scripts/create_record_fixture.py`（Windows，使用本机微软雅黑字体）。
