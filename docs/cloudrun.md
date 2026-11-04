# 部署到微信云托管

适用场景：**没有备案域名、也不想等备案**，但要让同事在微信里打开体验版。

云托管通过 `wx.cloud.callContainer` 调用，**不经过服务器域名白名单**，因此不需要备案域名。

---

## 现在的完成度

| 能力 | 状态 |
|---|---|
| 数据库持久化 | ✅ 支持 MySQL（`YIFAZHILIAN_DB_URL=mysql://...`），SQLite 仍可用于本地开发 |
| 文字类接口（登录、审核、工单、问答、用户） | ✅ 走 `callContainer` |
| 拍照上传（路线采集） | ✅ 压缩后转 base64 走 `media-base64` |
| 律师凭证上传与核验看图 | ✅ `credentials-base64` / `image-base64` |
| 图片读取（详情页显示照片） | ✅ `media/{id}/base64` 返回 data URL |
| 病历照片上传与读出（M03） | ✅ `record-documents/base64` 上传、`image-base64` 读出 |
| 病历字段裁剪图 | ✅ `.../fields/{id}/image-base64` |

> 也就是说：**采集、法律帮扶、审核、问答、病历照片全链路都能用了。**

---

## 一、开通环境

1. 微信公众平台 → 开发管理 → 云服务 → 云托管 → 开通
2. 创建环境（例如 `prod-1g2h3j4k`），记录**环境 ID**
3. 同一环境里开通 **MySQL**（云托管自带的数据库）

首环境有 3 个月免费额度（CPU 720 核·时、内存 1440 GB·时、MySQL 720 CCU·时），之后按量计费。

## 二、部署后端

```bash
# 仓库根目录
docker build -f deploy/cloudrun/Dockerfile -t yifazhilian:latest .
```

推到云托管镜像仓库，或在控制台用「代码包部署」：

```
Dockerfile 路径：deploy/cloudrun/Dockerfile
构建上下文：仓库根目录
端口：80
健康检查路径：/api/v1/health
```

必需的环境变量：

| 变量 | 值 |
|---|---|
| `YIFAZHILIAN_DB_URL` | `mysql://user:password@内网地址:3306/库名`（云托管 MySQL 详情里复制） |
| `YIFAZHILIAN_ALLOWED_HOSTS` | `*`（callContainer 的 Host 不固定） |
| `YIFAZHILIAN_RUNTIME_MODE` | `production` |
| `YIFAZHILIAN_DEMO_AUTH` | `1`（内部试用）或 `0`（配真实短信） |
| `YIFAZHILIAN_ADMIN_PHONE` | 你的手机号 |

启动时会自动建库建表（`CREATE DATABASE IF NOT EXISTS` + schema v12）并写入演示种子数据（合成账号、两条导航任务、知识库）。

## 三、小程序侧开关

```js
// miniprogram/config/index.js
const cloudRun = {
  enabled: true,
  env: 'prod-1g2h3j4k',   // 环境 ID
  service: 'yifazhilian'  // 服务名
}
```

`app.js` 会 `wx.cloud.init`，`services/api.js` 与 `services/navigation.js` 自动切到 `callContainer`；图片走 base64，不再需要 `uploadFile`。改完上传代码、设为体验版即可。

## 四、验证

1. 云托管控制台 → 日志，确认启动无报错
2. 浏览器打开默认域名 + `/api/v1/health`，应返回 `{"status":"ok","storage":"mysql"}`
3. 小程序里登录 → 首页有数据 → 志愿者采集能拍照上传 → 审核员能看图
4. 重启一次服务，数据仍在（说明 MySQL 生效）

---

## 实现说明（改了什么）

| 位置 | 改动 |
|---|---|
| `backend/app/mysql_adapter.py` | SQLite→MySQL 翻译层：`?`→`%s`、`INSERT OR IGNORE`、`ON CONFLICT…DO UPDATE`、DDL 类型映射、去掉外键、统一 `utf8mb4_unicode_ci` |
| `backend/app/db.py` | `YIFAZHILIAN_DB_URL` 存在时走 MySQL；`schema_meta` 表记录版本 |
| `backend/app/api/navigation.py` | 抽出 `_prepare_image` / `_store_media`，新增 `media-base64` 上传与 `media/{id}/base64` 读取 |
| `backend/app/api/legal_help.py` | 凭证图片的 base64 上传与读取 |
| `backend/app/api/record_documents.py` | 病历照片的 base64 上传、整图与裁剪图读取 |
| `miniprogram/services/api.js` | `cloudRun.enabled` 时走 `callContainer` |
| `miniprogram/services/navigation.js` | 云模式下 JSON 走 `callContainer`，上传/读图走 base64 |
| `miniprogram/services/image_upload.js` | 压缩 + 读 base64 的小工具 |

## 还没做的

- 云上真实数据回归：本地用 MariaDB 11.4 验证了功能与集成测试，云托管环境需再跑一次
- 批量数据与并发压测未做
- 病历 OCR 仍依赖本机 OCR 环境，容器里没装（会提示手填）

## 本地怎么验证 MySQL

```bash
# 任意一个 MySQL/MariaDB 实例
YIFAZHILIAN_DB_URL=mysql://root:root@127.0.0.1:3307/yfz_local \
YIFAZHILIAN_DEMO_AUTH=1 \
  ./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8010

# 集成测试（会用随机库名，跑完删除）
YIFAZHILIAN_TEST_MYSQL_URL=mysql://root:root@127.0.0.1:3307/yfz_tmp \
  ./.venv/Scripts/python.exe -m pytest tests/test_mysql_backend.py -q
```
