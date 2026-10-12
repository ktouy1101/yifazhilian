Page({
  data: {departments: ['护士站', '检验科', '影像科'], selected: ''},
  choose(e) { this.setData({selected: e.currentTarget.dataset.name}) },
  volunteer() { wx.showModal({title: '志愿者工作台规划', content: '下一阶段实现：领取导诊任务、查看公开地点、提交路线纠错，由院方审核后发布。此处未连接真人志愿者。', showCancel: false}) }
})
