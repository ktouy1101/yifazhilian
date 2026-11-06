// 真机调试：手机和电脑同一 WiFi 时，用电脑局域网 IP 访问后端。
// 上线（含体验版）必须换成 HTTPS 合法域名，或改用云托管模式。
//
// 云托管模式：不需要备案域名，请求走 wx.cloud.callContainer。
// 已部署实例：环境 prod-d7gck81ghb168ec59 / 服务 flask-iiym（上海）。
// 想切回局域网调试，把 enabled 改成 false。

const cloudRun = {
  enabled: true,
  env: 'prod-d7gck81ghb168ec59',
  service: 'flask-iiym'
}

module.exports = {baseURL: 'http://192.168.199.126:8000/api/v1', cloudRun}
