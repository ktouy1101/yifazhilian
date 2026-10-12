module.exports = function showError(error) {
  wx.showModal({title: '操作未完成', content: error.message || '请稍后重试', showCancel: false})
}
