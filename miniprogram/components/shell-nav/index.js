// 工作台外壳的底部导航：志愿者/审核员用同一套组件，传不同的 items。
Component({
  properties: {
    items: {type: Array, value: []},
    active: {type: String, value: ''}
  },
  methods: {
    pick(e) {
      const key = e.currentTarget.dataset.key
      if (!key || key === this.properties.active) return
      this.triggerEvent('change', {key})
    }
  }
})
