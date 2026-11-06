// 请求地址策略
// 云托管模式：所有请求走 wx.cloud.callContainer（不需要备案域名，也不需要 HTTPS 白名单）
// 本地调试：把 enabled 改成 false，请求打到局域网后端
//
// 已部署实例：环境 prod-d7gck81ghb168ec59 / 服务 flask-iiym（上海）。

const cloudRun = {
  enabled: true,
  env: 'prod-d7gck81ghb168ec59',
  service: 'flask-iiym'
}

module.exports = {
  // 云模式下不使用这个地址；保留它是为了 enabled=false 时本机联调
  baseURL: 'http://192.168.199.126:8000/api/v1',
  cloudRun
}
