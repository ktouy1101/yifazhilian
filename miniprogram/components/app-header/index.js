// 通用顶栏。未登录时在右侧统一显示「登录」入口：患者端、志愿者端、审核端共用。
// 直接读存储里的 token（services/identity 用同一个键），避免组件依赖 service 层。
const TOKEN_KEY = 'yfz_token'

Component({
  properties:{title:{type:String,value:'小企鹅医法智联'},subtitle:{type:String,value:''},
    back:{type:Boolean,value:false},fallback:{type:String,value:'/pages/home/index'},
    loginEntry:{type:Boolean,value:true}},
  data:{statusHeight:20,barHeight:44,rightSpace:100,loggedIn:true},
  lifetimes:{
    attached(){
      const info=wx.getWindowInfo?wx.getWindowInfo():wx.getSystemInfoSync()
      const capsule=wx.getMenuButtonBoundingClientRect?wx.getMenuButtonBoundingClientRect():null
      const statusHeight=info.statusBarHeight||20
      this.setData({statusHeight,barHeight:Math.max(44,capsule&&capsule.height?(capsule.top-statusHeight)*2+capsule.height:44),rightSpace:capsule&&capsule.left?info.windowWidth-capsule.left+12:100})
      this.refreshLogin()
    }
  },
  pageLifetimes:{show(){this.refreshLogin()}},
  methods:{
    refreshLogin(){
      if(!this.properties.loginEntry){this.setData({loggedIn:true});return}
      const pages=getCurrentPages()||[]
      const route=(pages[pages.length-1]&&pages[pages.length-1].route)||''
      // 登录页本身不再显示登录入口，避免套娃。
      if(route.indexOf('pages/login/index')>=0){this.setData({loggedIn:true});return}
      let token=''
      try{ token=(wx.getStorageSync&&wx.getStorageSync(TOKEN_KEY))||'' }catch(e){ token='' }
      this.setData({loggedIn:!!token})
    },
    openLogin(){
      if(this._opening)return
      this._opening=true
      wx.navigateTo({url:'/pages/login/index',complete:()=>{this._opening=false}})
    },
    goBack(){
      if(this._returning)return
      this._returning=true
      const complete=()=>{this._returning=false}
      const fallback=()=>wx.switchTab({url:this.properties.fallback,
        fail:()=>wx.showToast({title:'暂时无法返回，请重试',icon:'none'}),complete})
      if(getCurrentPages().length>1){
        wx.navigateBack({delta:1,success:complete,fail:fallback})
      }else fallback()
    }
  }
})
