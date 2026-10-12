Page({
  chat() { wx.navigateTo({url: '/pages/chat/index?domain=legal'}) },
  draft() { wx.showModal({title: '知情同意书草稿规划', content: '后续仅生成待医生审核的告知草稿，逐项确认风险、替代方案和理解情况；当前未生成或签署法律文书。', showCancel: false}) }
})
