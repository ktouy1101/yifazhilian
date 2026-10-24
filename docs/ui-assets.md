# 界面资源来源

主要图标、院内示意地图及法律知识图谱来自用户提供的「医法智联小程序-demo.zip」内 HTML 原型。
颜色、字号、圆角、间距及页面层次均按原型源码移植；CSS px 按 2 rpx 对应。
院内地图去掉静态移动点，改由小程序定位点图层播放本地演示；未接入真实定位。

源矢量资源转为 PNG 供小程序本地加载，不需要网络图片、付费素材或运行时图标依赖。
补充的 camera / check / volume-2 / shield 来自 [Feather Icons](https://github.com/feathericons/feather)，MIT 许可证保留在 `miniprogram/assets/FEATHER-LICENSE.txt`。

`.work/` 下的生成工具、原始附件、开发截图及临时 npm 依赖不提交 Git；小程序仅使用 `miniprogram/assets/` 内的最终资源。
