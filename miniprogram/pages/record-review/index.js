const records = require('../../services/records')
const identity = require('../../services/identity')
const guard = require('../../utils/navigation-page')
const emptyForm = () => ({title: '检验单', record_type: '检验单', record_date: '', institution: '', visit: '', metadata_confirmed: false, fields: []})
const reset = {doc: null, form: emptyForm(), image: '', crop: '', localPath: '', version: null, active: false,
  confirmedCount: 0, archiveIssues: [], archiveReady: false, dirty: false, readOnly: false, privacyConfirmed: false, reason: '', rawVisible: false, historyVisible: false, choosing: false}
const ask = (title, content, confirmText = '继续') => new Promise(resolve => wx.showModal({title, content, confirmText,
  success: res => resolve(!!res.confirm), fail: () => resolve(false)}))

Page({
  data: {...reset, busy: false, loading: false, error: '', notice: '', types: ['检验单', '检查报告', '影像报告', '门诊病历', '入院记录', '出院记录', '病案首页', '手术记录', '麻醉记录', '病理报告', '医嘱单', '处方', '诊断证明', '费用清单', '其他']},
  onLoad(options = {}) {
    guard.bind(this, reset)
    this._id = options.id || ''
    this._unloaded = false
  },
  async onShow() {
    if (this.data.busy || this._choosing || this._viewing) return
    await this.perform(async current => {
      const access = await records.access()
      if (!current()) return
      if (!access.active) { this.lock('本地病历处理尚未授权或已到期，请返回资料列表重新授权'); return }
      this.setData({active: true})
      this._expiresAt = access.expiresAt
      this.armExpiry(current)
      if (this._id && !this.data.doc) await this.loadDocument(current)
    })
  },
  onUnload() { this._unloaded = true; clearTimeout(this._expiry); guard.dispose(this); records.clearTemp() },
  armExpiry(current) {
    clearTimeout(this._expiry)
    const remaining = this._expiresAt - Date.now()
    if (remaining <= 0) { this.lock('授权已到期，请返回资料列表重新授权'); return }
    this._expiry = setTimeout(() => {
      if (!current()) return
      if (Date.now() < this._expiresAt) { this.armExpiry(current); return }
      this.lock('授权已到期，请返回资料列表重新授权')
    }, Math.min(remaining, 2147483647))
  },
  lock(message) {
    this._epoch += 1
    records.clearTemp()
    this.setData({...reset, busy: false, error: message})
  },
  async perform(action) {
    if (this.data.busy) return
    const current = guard.begin(this)
    this.setData({busy: true, error: '', notice: ''})
    try { await action(current) }
    catch (error) {
      if (current()) {
        if (error.status === 401 || error.status === 403) this.lock(error.message)
        else this.setData({error: error.message})
      }
    } finally { if (current()) this.setData({busy: false}) }
  },
  setDocument(doc) {
    this._id = doc.id
    const form = JSON.parse(JSON.stringify(doc.draft))
    form.fields = form.fields.map(field => ({...field, lowConfidence: field.confidence !== null && field.confidence < .9,
      confidenceLabel: field.confidence === null ? '手动填写' : Math.round(field.confidence * 100) + '%'}))
    const format = records.formatTime || (value => value)
    this.setData({doc: {...doc, statusLabel: records.statusLabel(doc.status),
      versions: doc.versions.map(v => ({...v, createdLabel: format(v.created_at)})),
      jobs: doc.jobs.map(j => ({...j, startedLabel: format(j.started_at)}))}, form,
      readOnly: doc.status === 'archived', version: null, dirty: false, reason: doc.status === 'archived' ? '' : (doc.draft.reason || ''), crop: '',
      confirmedCount: form.fields.filter(field => field.confirmed).length})
    this.updateReviewState()
  },
  async loadDocument(current) {
    const doc = await records.get(this._id)
    if (!current()) return
    this.setDocument(doc)
    const image = await records.image(doc.id)
    if (!current()) { records.removeTemp(image); return }
    records.removeTemp(this.data.image)
    this.setData({image})
  },
  async reload() {
    if (this.data.busy || !this._id) return
    const version = identity.getVersion()
    if (this.data.dirty && !await ask('重新载入资料', '尚未保存的修改会被丢弃，已归档版本不受影响。', '重新载入')) return
    if (version !== identity.getVersion()) return
    await this.perform(current => this.loadDocument(current))
  },
  async choosePhoto(e) {
    if (this.data.busy || this._choosing || !this.data.active) return
    const source = e && e.currentTarget && e.currentTarget.dataset.source
    const sourceType = ['album', 'camera'].includes(source) ? [source] : ['album', 'camera']
    const sourceLabel = source === 'camera' ? '相机' : (source === 'album' ? '相册' : '照片选择')
    const version = identity.getVersion()
    const epoch = this._epoch
    const current = () => !this._unloaded && version === identity.getVersion() && epoch === this._epoch && this.data.active
    this._choosing = true
    this.setData({choosing: true, error: ''})
    const legacyPicker = () => new Promise((resolve, reject) => {
      if (typeof wx.chooseImage !== 'function') { reject(new Error('当前微信版本不支持选择照片，请升级微信后重试')); return }
      wx.chooseImage({count: 1, sourceType, sizeType: ['original'],
        success: res => {
          const first = res.tempFiles && res.tempFiles[0]
          resolve({tempFilePath: first && first.path || res.tempFilePaths && res.tempFilePaths[0], size: first && first.size})
        }, fail: reject})
    })
    try {
      let file
      if (typeof wx.chooseMedia === 'function' && (!wx.canIUse || wx.canIUse('chooseMedia'))) {
        try {
          file = await new Promise((resolve, reject) => wx.chooseMedia({count: 1, mediaType: ['image'],
            sourceType, sizeType: ['original'],
            success: res => resolve(res.tempFiles && res.tempFiles[0]), fail: reject}))
        } catch (error) {
          // Only unsupported API errors may fall back. Never retry a refusal or cancellation.
          if (!current()) return
          if (!/not support|not available|not a function/i.test(error.errMsg || error.message || '')) throw error
          file = await legacyPicker()
        }
      } else file = await legacyPicker()
      if (!current()) return
      if (!file || !file.tempFilePath) throw new Error('未取得照片，请重新选择')
      if (file.size > 8 * 1024 * 1024) throw new Error('照片超过8MB，请在相册缩小图片后重新选择')
      this.setData({localPath: file.tempFilePath, privacyConfirmed: false, error: '', notice: '照片尚未上传。请检查清晰度与遮挡情况。'})
    } catch (error) {
      const detail = error.errMsg || error.message || ''
      if (current() && !/cancel/i.test(detail)) {
        let message = error.message || sourceLabel + '未能打开，请重试'
        if (/privacy/i.test(detail)) message = '微信隐私授权未完成，暂时无法选择照片；请同意微信弹出的隐私提示后重试。若没有提示，请检查小程序后台的照片选取声明。'
        else if (/auth|denied|permission|authorize/i.test(detail)) message = sourceLabel + '权限未开启，请在微信或手机系统设置中允许访问后重试'
        else if (error.errMsg) message = sourceLabel + '未能打开：' + detail.slice(0, 180)
        this.setData({error: message})
      }
    } finally {
      this._choosing = false
      if (current()) this.setData({choosing: false})
    }
  },
  privacyChange(e) { this.setData({privacyConfirmed: e.detail.value.includes('yes')}) },
  async upload() {
    if (this._choosing || !this.data.localPath || !this.data.privacyConfirmed || !this.data.active) return
    await this.perform(async current => {
      const doc = await records.upload(this.data.localPath)
      if (!current()) return
      const localPath = this.data.localPath
      this.setDocument(doc)
      this.setData({localPath: '', image: localPath, notice: doc.duplicate ? '这张照片已上传，已打开原有资料，不会重复归档。' : '原图已保存，尚未归档。现在可以开始本地识别。'})
    })
  },
  async recognize() {
    const doc = this.data.doc
    if (!doc || this.data.busy || doc.archived_version) return
    const version = identity.getVersion()
    if ((this.data.dirty || doc.status === 'review') && !await ask('重新识别原图', '重新识别会替换当前核对草稿；此前OCR原文仍可回查。', '重新识别')) return
    if (version !== identity.getVersion()) return
    await this.perform(async current => {
      const key = doc.id + ':' + doc.revision
      if (!this._ocrRequest || this._ocrRequest.key !== key) this._ocrRequest = {key, id: records.requestId()}
      const result = await records.recognize(doc.id, {revision: doc.revision, request_id: this._ocrRequest.id})
      if (!current()) return
      this.setDocument(result)
      this._ocrRequest = null
      this.setData({rawVisible: false, notice: result.status === 'review' ? (result.draft.fields.length ? '已提取 ' + result.draft.fields.length + ' 项。请对照原图逐项核对，尤其是小数点、单位和参考区间，确认后即可归档。' : '已识别文字，但未提取到检验项目。请重新识别或对照原图手动添加项目，核对后再归档。') : '',
        error: result.job && result.job.error || ''})
    })
  },
  preview() {
    const url = this.data.image || this.data.localPath
    if (!url) return
    this._viewing = true
    wx.previewImage({current: url, urls: [url], complete: () => { this._viewing = false }})
  },
  inputMeta(e) {
    if (this.data.readOnly || this.data.busy) return
    const key = e.currentTarget.dataset.key
    if (!['title', 'record_date', 'institution', 'visit'].includes(key)) return
    this.setData({['form.' + key]: e.detail.value, 'form.metadata_confirmed': false, dirty: true})
    this.updateReviewState()
  },
  pickType(e) {
    if (this.data.readOnly || this.data.busy) return
    this.setData({'form.record_type': this.data.types[Number(e.detail.value)], 'form.metadata_confirmed': false, dirty: true})
    this.updateReviewState()
  },
  metadataChange(e) {
    if (this.data.readOnly || this.data.busy) return
    this.setData({'form.metadata_confirmed': e.detail.value.includes('yes'), dirty: true})
    this.updateReviewState()
  },
  inputField(e) {
    if (this.data.readOnly || this.data.busy) return
    const {index, key} = e.currentTarget.dataset
    if (!['name', 'result', 'unit', 'reference'].includes(key) || !this.data.form.fields[index]) return
    this.setData({[`form.fields[${index}].${key}`]: e.detail.value, [`form.fields[${index}].confirmed`]: false, dirty: true})
    this.updateReviewState()
  },
  confirmField(e) {
    if (this.data.busy || this.data.readOnly) return
    this.setData({[`form.fields[${e.currentTarget.dataset.index}].confirmed`]: e.detail.value.includes('yes'), dirty: true})
    this.updateReviewState()
  },
  updateReviewState() {
    const {form, doc, reason} = this.data
    const issues = []
    if (!form.title.trim()) issues.push({text: '请填写资料标题', target: '#metadata-panel'})
    if (form.record_date) {
      const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(form.record_date)
      if (!parts || +parts[1] < 1 || +parts[2] < 1 || +parts[2] > 12 || +parts[3] < 1 || +parts[3] > new Date(+parts[1], +parts[2], 0).getDate()) {
        issues.push({text: '请填写有效的报告日期（YYYY-MM-DD），未记载可留空', target: '#metadata-panel'})
      }
    }
    if (!form.fields.length) issues.push({text: '尚无可归档的检验项目，请重新识别或手动添加', target: '#review-items'})
    else {
      const incomplete = form.fields.findIndex(field => !field.name.trim() || !field.result.trim())
      if (incomplete !== -1) issues.push({text: '第 ' + (incomplete + 1) + ' 项缺少项目名称或结果', target: '#review-field-' + incomplete})
      const pending = form.fields.filter(field => !field.confirmed).length
      if (pending) issues.push({text: '还有 ' + pending + ' 项未勾选“已对照原图核对本项”', target: '#review-field-' + form.fields.findIndex(field => !field.confirmed)})
    }
    if (!form.metadata_confirmed) issues.push({text: '请勾选“已核对资料信息，检查了表格中的遗漏项目”', target: '#metadata-confirmation'})
    if (doc && doc.archived_version && !reason.trim()) issues.push({text: '请填写本次更正原因', target: '#correction-reason'})
    this.setData({confirmedCount: form.fields.filter(field => field.confirmed).length, archiveIssues: issues, archiveReady: !issues.length})
    return issues
  },
  goToReview(e) {
    if (this.data.busy || this.data.readOnly || !this.data.active) return
    const index = e && e.currentTarget ? Number(e.currentTarget.dataset.index) : 0
    const issue = this.data.archiveIssues[index]
    if (issue) this.setData({rawVisible: false}, () => {
      const header = this.selectComponent && this.selectComponent('app-header')
      const headerHeight = header ? header.data.statusHeight + header.data.barHeight : 100
      wx.pageScrollTo({selector: issue.target, offsetTop: -(headerHeight + 12), duration: 200})
    })
  },
  addField() {
    if (this.data.readOnly || this.data.busy || this.data.form.fields.length >= 100) return
    const field = {id: 'manual-' + records.requestId(), name: '', result: '', unit: '', reference: '', confirmed: false,
      original: null, confidence: null, source_ids: [], box: null, confidenceLabel: '手动填写'}
    this.setData({'form.fields': this.data.form.fields.concat(field), dirty: true})
    this.updateReviewState()
  },
  removeField(e) {
    if (this.data.readOnly || this.data.busy) return
    this.setData({'form.fields': this.data.form.fields.filter((_, index) => index !== Number(e.currentTarget.dataset.index)), dirty: true})
    this.updateReviewState()
  },
  async locate(e) {
    if (this.data.busy) return
    const field = this.data.form.fields[e.currentTarget.dataset.index]
    const job = this.data.version ? this.data.version.snapshot.job_id : this.data.doc.draft.source_job_id
    if (!field || !field.box || !job) { this.preview(); return }
    await this.perform(async current => {
      const crop = await records.crop(this._id, job, field.id)
      if (!current()) { records.removeTemp(crop); return }
      records.removeTemp(this.data.crop)
      this.setData({crop, cropLabel: field.name || '对应原图'})
      wx.pageScrollTo({selector: '#source-panel', duration: 200})
    })
  },
  edit() {
    if (this.data.busy || this.data.version) return
    this.setData({readOnly: false, reason: '', 'form.metadata_confirmed': false, dirty: true,
      notice: '修改将保存为新版本，旧版本与原图保留。'})
    this.updateReviewState()
  },
  inputReason(e) {
    if (this.data.readOnly || this.data.busy) return
    this.setData({reason: e.detail.value, dirty: true})
    this.updateReviewState()
  },
  async save() { await this.write(false) },
  async confirm() { await this.write(true) },
  async write(confirm) {
    if (!this.data.doc || this.data.busy || this.data.readOnly || !this.data.active) return
    const {form, doc} = this.data
    if (confirm && this.updateReviewState().length) { this.goToReview(); return }
    if (!form.title.trim()) { this.setData({error: '请填写资料标题'}); return }
    const version = identity.getVersion()
    if (confirm && !await ask('确认核对并归档', '确认已对照原图检查所有项目，包括遗漏项目、结果、单位与参考区间。归档后仍可更正并回查旧版本。', '确认归档')) return
    if (version !== identity.getVersion()) return
    await this.perform(async current => {
      const body = {revision: doc.revision, title: form.title, record_type: form.record_type, record_date: form.record_date,
        institution: form.institution, visit: form.visit, metadata_confirmed: form.metadata_confirmed, reason: this.data.reason,
        fields: form.fields.map(f => ({id: f.id, name: f.name, result: f.result, unit: f.unit, reference: f.reference, confirmed: f.confirmed}))}
      const signature = JSON.stringify([confirm, body])
      if (!this._writeRequest || this._writeRequest.signature !== signature) this._writeRequest = {signature, id: records.requestId()}
      const result = await (confirm ? records.confirm : records.save)(doc.id, {...body, request_id: this._writeRequest.id})
      if (!current()) return
      this.setDocument(result); this._writeRequest = null
      this.setData({notice: confirm ? '已归档为第 ' + result.archived_version + ' 版，可随时回查。' : '草稿已保存，尚未确认归档。'})
    })
  },
  toggleRaw() { this.setData({rawVisible: !this.data.rawVisible}) },
  toggleHistory() { this.setData({historyVisible: !this.data.historyVisible}) },
  async openVersion(e) {
    if (this.data.busy) return
    if (this.data.dirty) { this.setData({error: '请先保存草稿或重新载入，再查看历史版本'}); return }
    await this.perform(async current => {
      const version = await records.version(this._id, e.currentTarget.dataset.version)
      if (!current()) return
      this.setData({version, form: version.snapshot.draft, readOnly: true, crop: '', notice: '正在查看第 ' + version.snapshot.version + ' 版；当前资料未被修改。'})
      this.updateReviewState()
    })
  },
  async openJob(e) {
    await this.perform(async current => {
      const job = await records.job(this._id, e.currentTarget.dataset.id)
      if (current()) this.setData({'doc.ocr': job.result, rawVisible: true, notice: '正在查看所选识别任务的原文；核对字段未被修改。'})
    })
  },
  async discard() {
    if (this.data.busy) return
    const version = identity.getVersion()
    const doc = this.data.doc
    if (!await ask('放弃这份草稿', doc ? '将删除尚未归档的照片、识别任务及核对草稿。' : '这张照片尚未上传，将退出本次录入。', '放弃草稿')) return
    if (version !== identity.getVersion()) return
    if (!doc) { wx.navigateBack(); return }
    await this.perform(async current => {
      await records.discard(doc.id, doc.revision)
      if (current()) { records.clearTemp(); wx.navigateBack() }
    })
  },
  async retake() {
    if (this.data.busy) return
    const version = identity.getVersion()
    if (!await ask('重新拍摄', '将新建另一份资料；当前已保存的照片和草稿保留在列表中。', '重新拍摄')) return
    if (version === identity.getVersion()) wx.redirectTo({url: '/pages/record-review/index?source=camera'})
  },
  backToList() { wx.redirectTo({url: '/pages/records/index'}) }
})
