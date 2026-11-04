// 真机调试：手机和电脑同一 WiFi 时，用电脑局域网 IP 访问后端。
// 上线必须换成 HTTPS 合法域名。
//
// 云托管模式（不需要备案域名）：把 cloudRun.enabled 改成 true，
// 填上云托管的环境 ID 与服务名；此时所有请求走 wx.cloud.callContainer，
// baseURL 不再使用。详见 docs/cloudrun.md。

const cloudRun = {
  enabled: false,
  env: '',        // 云托管环境 ID，例如 prod-1g2h3j4k
  service: ''     // 云托管服务名，例如 yifazhilian
}

module.exports = {baseURL: 'http://192.168.199.126:8000/api/v1', cloudRun}
