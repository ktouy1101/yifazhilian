Component({
  properties:{title:{type:String,value:'医法智联'},subtitle:{type:String,value:''},
    back:{type:Boolean,value:false},fallback:{type:String,value:'/pages/home/index'}},
  data:{statusHeight:20,barHeight:44,rightSpace:100},
  lifetimes:{attached(){
    const info=wx.getWindowInfo?wx.getWindowInfo():wx.getSystemInfoSync()
    const capsule=wx.getMenuButtonBoundingClientRect?wx.getMenuButtonBoundingClientRect():null
    const statusHeight=info.statusBarHeight||20
    this.setData({statusHeight,barHeight:Math.max(44,capsule&&capsule.height?(capsule.top-statusHeight)*2+capsule.height:44),rightSpace:capsule&&capsule.left?info.windowWidth-capsule.left+12:100})
  }},
  methods:{
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
