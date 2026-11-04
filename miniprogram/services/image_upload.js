// 云托管模式下的图片辅助：callContainer 不能发 multipart，
// 图片改为压缩后转 base64 走 JSON 接口。
const {cloudRun} = require('../config/index')

function compress(src, quality = 70) {
  return new Promise(resolve => {
    wx.compressImage({
      src, quality,
      success: res => resolve(res.tempFilePath),
      fail: () => resolve(src)
    })
  })
}

function readBase64(filePath) {
  return new Promise((resolve, reject) => {
    wx.getFileSystemManager().readFile({
      filePath, encoding: 'base64',
      success: res => resolve(res.data),
      fail: () => reject(new Error('读取本地图片失败'))
    })
  })
}

function mimeOf(filePath) {
  return /\.png$/i.test(filePath || '') ? 'image/png' : 'image/jpeg'
}

// 返回可直接放进 JSON 的 data URL
async function toDataUrl(filePath, quality = 70) {
  const compressed = await compress(filePath, quality)
  const base64 = await readBase64(compressed)
  return 'data:' + mimeOf(filePath) + ';base64,' + base64
}

const enabled = () => !!(cloudRun && cloudRun.enabled && cloudRun.env && cloudRun.service)

module.exports = {enabled, toDataUrl, compress}
