# 部署到云服务器

目标：把后端跑在一台 Linux 服务器上，用域名 + 自动 HTTPS 对外提供服务，小程序以体验版/正式版访问。

本文按「轻量应用服务器（Ubuntu 22.04 / 24.04）」写，其它发行版同理。

---

## 0. 准备清单

| 东西 | 说明 |
|---|---|
| 服务器 | 1 核 2G 起，Ubuntu 22.04+，**包月 ≥ 3 个月**（备案要求） |
| 域名 | 任意注册商，需**实名认证** |
| 备案 | 在服务器所在云厂商提交（1–3 周），备案期间服务器必须保持运行 |
| 微信小程序后台 | 能登录的管理员账号 |

> 没有备案域名时，小程序体验版/正式版**无法**访问后端（微信强制校验合法域名），只能开发者工具本地调试。

---

## 1. 服务器初始化

```bash
# 以 root 或 sudo 用户执行
apt update && apt upgrade -y

# 安装 Docker（官方脚本，含 compose 插件）
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

docker --version
docker compose version
```

安全组 / 防火墙放行：

| 端口 | 用途 |
|---|---|
| 22 | SSH |
| 80 | HTTP（Caddy 签证书用，必须对外） |
| 443 | HTTPS |

**不要**对公网开放 8000（后端只在 Docker 内部网络监听）。

---

## 2. 拉代码

仓库是私有的，用 deploy key 或临时 token：

```bash
mkdir -p /srv && cd /srv
git clone https://github.com/ktouy1101/penguin.git yifazhilian
cd yifazhilian
```

---

## 3. 配置环境变量

```bash
cp deploy/env.example deploy/env
nano deploy/env
```

必须改的几项：

```ini
DOMAIN=api.你的域名.com
YIFAZHILIAN_ALLOWED_HOSTS=api.你的域名.com
YIFAZHILIAN_RUNTIME_MODE=production
YIFAZHILIAN_DEMO_AUTH=0
YIFAZHILIAN_ADMIN_PHONE=你的手机号
```

说明：

- `DOMAIN` 必须解析到这台服务器（先配好 A 记录，见第 4 步）。
- `YIFAZHILIAN_ALLOWED_HOSTS` 不填域名，所有请求会返回 `400 Invalid host header`。
- `YIFAZHILIAN_DEMO_AUTH=0` 时没有短信通道就**没人能登录**（见第 9 节）。

`backend/admins.txt` 里的号码同样会被识别为管理员，两者取并集。

---

## 4. 域名解析

在域名控制台加 A 记录：

```
主机记录  api
记录类型  A
记录值    服务器公网 IP
```

验证：

```bash
ping api.你的域名.com     # 应返回服务器 IP
```

---

## 5. 启动

```bash
cd /srv/yifazhilian
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs -f caddy   # 看证书签发
```

首次启动 Caddy 会自动向 Let's Encrypt 申请证书（需要 80 端口可达、域名已解析）。

验证：

```bash
curl https://api.你的域名.com/api/v1/health
# 期望：{"status":"ok","storage":"sqlite_local"}
```

---

## 6. 微信小程序配置

1. 打开 [微信公众平台](https://mp.weixin.qq.com) → 开发管理 → 开发设置 → 服务器域名
2. 「request 合法域名」添加 `https://api.你的域名.com`（保存后约 1 分钟生效）
3. 本地改小程序请求地址：

```js
// miniprogram/config/index.js
module.exports = {baseURL: 'https://api.你的域名.com/api/v1'}
```

4. 开发者工具「上传」→ 提交版本
5. 后台「版本管理」→ 把该版本**设为体验版**
6. 「成员管理 → 体验成员」添加同事的微信号，他们扫码即可使用

---

## 7. 备份与恢复

每日备份（在仓库根目录，建议加进 crontab）：

```bash
bash deploy/backup.sh
```

它会用 SQLite 的 backup API 生成一致性快照到容器内 `/data/backups/`，保留 14 天。

恢复到某个备份：

```bash
docker compose -f deploy/docker-compose.yml stop api
docker run --rm -v yifazhilian_yfz-data:/data -v $(pwd):/backup alpine \
  sh -c "cp /backup/某个备份.db /data/yifazhilian.db"
docker compose -f deploy/docker-compose.yml start api
```

> 卷名可用 `docker volume ls` 确认，默认是 `<目录名>_yfz-data`。

---

## 8. 升级代码

```bash
cd /srv/yifazhilian
git pull
docker compose -f deploy/docker-compose.yml up -d --build
```

数据库有 schema 迁移，容器启动时会自动执行（`PRAGMA user_version` 递增，不删数据）。升级前建议先跑一次备份。

---

## 9. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| 接口 400 `Invalid host header` | `YIFAZHILIAN_ALLOWED_HOSTS` 没加域名 |
| 浏览器打不开、证书签不下来 | 域名没解析 / 80 端口未放行 / 域名未备案（境外未备案域名 Let's Encrypt 仍可签，但微信不认） |
| 502 Bad Gateway | api 容器没起来，看 `docker compose logs api` |
| 登录一直失败 | `DEMO_AUTH=0` 且没有接短信服务商 —— 这是预期行为，见下 |
| 图片/OCR 功能报错 | 镜像**不含 OCR 依赖**（`requirements-ocr.txt` 体积大），图片识别在服务器上不可用，前端会提示手填 |
| 数据每次重建都没了 | 卷没挂上，确认 `docker volume ls` 里有 `yfz-data` |

### 关于登录（重要）

现在系统只有两种登录：手机号 + 验证码（演示模式）和微信登录。

- `DEMO_AUTH=1`：`/auth/send-code` 会直接把验证码返回给前端，**任何人只要知道手机号就能登录任何账号，包括管理员**。
- `DEMO_AUTH=0`：不会返回验证码，但也意味着**没有短信通道就没人能登录**。

给同事试用时，两种选择：

1. 保持 `DEMO_AUTH=1`，但只把体验版给信任的人，并且**管理员手机号用一个外人不知道的号**；
2. 接入真实短信（阿里云/腾讯云短信），把 `DEMO_AUTH` 关掉——需要额外开发发送验证码的代码。

微信登录（`YIFAZHILIAN_WECHAT_APP_ID/SECRET`）可作为免短信的登录方式，但需要小程序已认证且用户已授权。

---

## 10. 本仓库部署相关文件

| 文件 | 作用 |
|---|---|
| `deploy/Dockerfile` | 后端镜像（Python 3.12 + uvicorn） |
| `deploy/docker-compose.yml` | 编排 api + caddy，挂载数据卷 |
| `deploy/Caddyfile` | 自动 HTTPS、反向代理、访问日志 |
| `deploy/env.example` | 环境变量模板（复制成 `deploy/env`） |
| `deploy/backup.sh` | SQLite 每日备份与清理 |
| `.dockerignore` | 排除小程序、测试、本地产物 |
