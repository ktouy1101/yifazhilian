// 谁能看到「采集 / 审核」入口：有采集权限的志愿者，或审核员。
// 规则只写在这里；隐藏入口不等于鉴权，接口仍会各自校验。
function canEnterWorkbench(capabilities) {
  const caps = capabilities || {}
  return !!(caps.can_collect || caps.is_reviewer)
}

module.exports = {canEnterWorkbench}
