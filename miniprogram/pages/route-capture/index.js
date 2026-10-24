const nav = require('../../services/navigation')
const identity = require('../../services/identity')
const guard = require('../../utils/navigation-page')
const KINDS = [{value: 'start', label: '起点'}, {value: 'turn', label: '转弯'}, {value: 'landmark', label: '地标'},
  {value: 'elevator', label: '电梯'}, {value: 'stairs', label: '楼梯'}, {value: 'end', label: '终点'}]
const STATUS = {draft: '草稿', submitted: '待审核', changes_requested: '需补拍', published: '已发布', disabled: '已停用'}
const EMPTY = {sub: {}, nodes: [], editable: false, canRevise: false, privacyOk: false, sourceIndex: 0}
const seed = () => [{node_key: 'start', kind: 'start', position: 0}, {node_key: 'end', kind: 'end', position: 1}]
Page({
  data: {...EMPTY, id: '', kindOptions: KINDS, statusLabel: STATUS, busy: false, error: ''},
  onLoad(query) { guard.bind(this, EMPTY); this.setData({id: query.id}); return this.load() },
  onShow() {
    if (this._identityVersion !== identity.getVersion()) {
      this._identityVersion = identity.getVersion()
      return this.load()
    }
  },
  onUnload() { guard.dispose(this) },
  async load() {
    const current = guard.begin(this)
    this.setData({busy: true, error: ''})
    try {
      const [sub, me] = await Promise.all([nav.getSubmission(this.data.id), nav.me()])
      if (!current()) return
      const editable = me.permissions.collect && sub.collector_id === me.user.id && ['draft', 'changes_requested'].includes(sub.status)
      const nodes = (sub.nodes.length ? sub.nodes : seed()).map(n => {
        const media = (sub.media || []).find(m => m.node_key === n.node_key)
        return {...n, kindIndex: KINDS.findIndex(k => k.value === n.kind), mediaId: media ? media.id : '', tempPath: ''}
      })
      this.setData({sub, nodes, editable, privacyOk: false, sourceIndex: 0,
        canRevise: me.permissions.collect && sub.collector_id === me.user.id && ['published', 'disabled'].includes(sub.status) && !!(sub.versions || []).length})
      nodes.forEach(n => {
        if (!n.mediaId) return
        nav.fetchMediaTempUrl(n.mediaId).then(path => {
          if (!current()) return
          const i = this.data.nodes.findIndex(x => x.node_key === n.node_key && x.mediaId === n.mediaId)
          if (i >= 0) this.setData({['nodes[' + i + '].tempPath']: path})
        }).catch(e => {
          if (current()) this.setData({error: '已有照片读取失败：' + e.message})
        })
      })
    } catch (e) { if (current()) this.setData({...EMPTY, error: e.message}) }
    finally { if (current()) this.setData({busy: false}) }
  },
  onTitle(e) { if (this.data.editable && !this.data.busy) this.setData({'sub.title': e.detail.value, privacyOk: false}) },
  onField(e) {
    if (!this.data.editable || this.data.busy) return
    const {index, key} = e.currentTarget.dataset
    if (!['floor', 'direction', 'description'].includes(key)) return
    this.setData({['nodes[' + index + '].' + key]: e.detail.value, privacyOk: false})
  },
  pickKind(e) {
    if (!this.data.editable || this.data.busy) return
    this.setData({['nodes[' + e.currentTarget.dataset.index + '].kindIndex']: Number(e.detail.value), privacyOk: false})
  },
  addNode() {
    if (!this.data.editable || this.data.busy || this.data.nodes.length >= 30) return
    const nodes = this.data.nodes.slice()
    nodes.splice(nodes.length - 1, 0, {node_key: 'n' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5),
      kind: 'turn', kindIndex: 1, floor: '', direction: '', description: ''})
    nodes.forEach((n, i) => { n.position = i })
    this.setData({nodes, privacyOk: false})
  },
  removeNode(e) {
    if (!this.data.editable || this.data.busy) return
    const i = Number(e.currentTarget.dataset.index)
    if (i <= 0 || i >= this.data.nodes.length - 1) return
    const nodes = this.data.nodes.filter((_, index) => index !== i).map((n, position) => ({...n, position}))
    this.setData({nodes, privacyOk: false})
  },
  togglePrivacy() { if (!this.data.busy) this.setData({privacyOk: !this.data.privacyOk}) },
  async capturePhoto(e) {
    if (!this.data.editable || this.data.busy) return
    const current = guard.begin(this), i = Number(e.currentTarget.dataset.index)
    this.setData({busy: true, error: ''})
    try {
      const result = await wx.chooseMedia({count: 1, mediaType: ['image'], sourceType: ['camera', 'album'], sizeType: ['compressed']})
      if (!current()) return
      const file = result.tempFiles[0]
      if (file.size > 5 * 1024 * 1024) throw new Error('图片超过 5MB，请压缩或重拍')
      this.setData({['nodes[' + i + '].pendingPath']: file.tempFilePath,
        ['nodes[' + i + '].uploadId']: 'up-' + Date.now() + '-' + i, privacyOk: false})
    } catch (e) {
      if (current() && !/cancel/i.test(e.errMsg || '')) this.setData({error: e.message || '无法拍照，请允许相机权限或从相册选择'})
    } finally { if (current()) this.setData({busy: false}) }
  },
  async editPhoto(e) {
    const i = Number(e.currentTarget.dataset.index), node = this.data.nodes[i]
    if (!this.data.editable || this.data.busy || !node.pendingPath) return
    if (!wx.editImage) { this.setData({error: '当前设备不支持编辑，请使用不含隐私内容的照片或重拍。'}); return }
    const current = guard.begin(this)
    this.setData({busy: true})
    try {
      const result = await wx.editImage({src: node.pendingPath})
      if (current()) this.setData({['nodes[' + i + '].pendingPath']: result.tempFilePath,
        ['nodes[' + i + '].uploadId']: 'up-' + Date.now() + '-' + i, privacyOk: false})
    } catch (e) { if (current() && !/cancel/i.test(e.errMsg || '')) this.setData({error: '照片编辑失败，可重新拍摄。'}) }
    finally { if (current()) this.setData({busy: false}) }
  },
  preview(e) {
    const n = this.data.nodes[Number(e.currentTarget.dataset.index)]
    const path = n.pendingPath || n.tempPath
    if (path) wx.previewImage({urls: [path], current: path})
  },
  _payload() {
    return {revision: this.data.sub.revision, title: this.data.sub.title.trim(), nodes: this.data.nodes.map((n, i) => ({
      node_key: n.node_key, position: i, kind: KINDS[n.kindIndex].value,
      floor: (n.floor || '').trim() || null, direction: (n.direction || '').trim() || null,
      description: (n.description || '').trim() || null
    }))}
  },
  async _save(current) {
    const sub = await nav.updateSubmission(this.data.id, this._payload())
    if (!current()) return null
    const nodes = this.data.nodes.map(n => {
      const media = sub.media.find(m => m.node_key === n.node_key)
      return {...n, mediaId: media ? media.id : '', tempPath: media && media.id === n.mediaId ? n.tempPath : ''}
    })
    this.setData({sub, nodes})
    return sub
  },
  async uploadPhoto(e) {
    if (!this.data.editable || this.data.busy) return
    const i = Number(e.currentTarget.dataset.index), node = this.data.nodes[i]
    if (!node.pendingPath) return
    const current = guard.begin(this)
    this.setData({busy: true, error: ''})
    try {
      const confirm = await new Promise(resolve => wx.showModal({title: '确认这张照片可上传',
        content: '请先检查照片：仅限允许采集的公共环境，不含患者、人脸、腕带、病历或屏幕信息。需要处理时请取消并编辑或重拍。',
        confirmText: '确认上传', success: resolve, fail: () => resolve({confirm: false})}))
      if (!current() || !confirm.confirm) return
      const saved = await this._save(current)
      if (!saved || !current()) return
      const up = await nav.uploadMedia(this.data.id, {nodeKey: node.node_key, revision: saved.revision,
        filePath: node.pendingPath, uploadId: node.uploadId})
      if (!current()) return
      this.setData({'sub.revision': up.submission_revision, ['nodes[' + i + '].mediaId']: up.id,
        ['nodes[' + i + '].tempPath']: node.pendingPath, ['nodes[' + i + '].pendingPath']: '', privacyOk: false})
      wx.showToast({title: '照片已上传', icon: 'success'})
    } catch (e) { if (current()) this.setData({error: e.message + '；照片保留，可刷新确认后重试。'}) }
    finally { if (current()) this.setData({busy: false}) }
  },
  async saveDraft() {
    if (!this.data.editable || this.data.busy) return
    const current = guard.begin(this)
    this.setData({busy: true, error: ''})
    try {
      if (await this._save(current)) wx.showToast({title: '文字草稿已保存', icon: 'success'})
    } catch (e) { if (current()) this.setData({error: e.message}) }
    finally { if (current()) this.setData({busy: false}) }
  },
  async submit() {
    if (!this.data.editable || this.data.busy) return
    const incomplete = this.data.nodes.findIndex(n => !(n.floor || '').trim() || !(n.description || '').trim())
    if (incomplete >= 0) { this.setData({error: '请补全第 ' + (incomplete + 1) + ' 个节点的楼栋 / 楼层和位置说明。'}); return }
    if (!this.data.privacyOk) { this.setData({error: '请核对所有照片并勾选隐私确认。'}); return }
    if (this.data.nodes.some(n => n.pendingPath || !n.mediaId)) {
      this.setData({error: '请先上传每个节点的照片；预览中的新照片尚未上传。'}); return
    }
    const current = guard.begin(this)
    this.setData({busy: true, error: ''})
    try {
      const saved = await this._save(current)
      if (!saved || !current()) return
      const sub = await nav.submit(this.data.id, {revision: saved.revision, privacy_confirmed: true})
      if (!current()) return
      this.setData({sub, editable: false, privacyOk: false})
      wx.showToast({title: '已提交，等待他人审核', icon: 'none'})
    } catch (e) { if (current()) this.setData({error: e.message}) }
    finally { if (current()) this.setData({busy: false}) }
  },
  selectSource(e) { this.setData({sourceIndex: Number(e.detail.value)}) },
  async revise() {
    if (!this.data.canRevise || this.data.busy) return
    const current = guard.begin(this)
    this.setData({busy: true, error: ''})
    try {
      const answer = await new Promise(resolve => wx.showModal({title: '恢复历史版本为草稿',
        content: '当前已发布路线将暂时下线。恢复的内容需要重新提交，由另一位审核员实走核验后才能再次发布。',
        confirmText: '开始修订', success: resolve, fail: () => resolve({confirm: false})}))
      if (!current() || !answer.confirm) return
      await nav.revise(this.data.id, {revision: this.data.sub.revision,
        source_revision: this.data.sub.versions[this.data.sourceIndex].revision})
      if (!current()) return
      await this.load()
    } catch (e) { if (current()) this.setData({error: e.message}) }
    finally { if (current()) this.setData({busy: false}) }
  },
  viewHistory() { wx.navigateTo({url: '/pages/route-review/index?id=' + encodeURIComponent(this.data.id)}) }
})

