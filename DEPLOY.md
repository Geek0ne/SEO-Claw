# 部署与选型

这份文档回答一个问题：**SEO-Claw 上线要花多少钱、配多大机器。**

所有数字都是实跑量出来的，不是拍的。量法写在每节末尾。

---

## 一句话结论

**先别买机器。** 用 Render 免费版跑几天，你会知道自己一天到底扫几个站——
而那正是决定该买 1G 还是 2G 的唯一依据。

如果只是你自己用，一个子都别花。

---

## 这个服务有多吃资源

### 它 87% 的时间在睡觉

抓 1000 个页面，实测 **382 秒**，其中 **333 秒是在等限速**。

爬虫规规矩矩按每秒 3 个请求排队等——这是它对第三方站礼貌的方式，也是它慢的原因。

**所以你买 4 核机器和 1 核跑出来一模一样，多出来的钱纯浪费。**
CPU 不是瓶颈，等都等在网络往返上。

### 内存

| 场景 | 峰值 RSS |
|---|---|
| 扫描 15 页 | **100 MB** |

比预想的低不少——本来以为正文抽取会吃内存，实际不。

> 量法：`/usr/bin/time -v` 包一层真实爬取任务，看 Maximum resident set size。

### 磁盘

镜像 **438 MB**（Docker 构建产物）。

数据库很小：一次 100 页的扫描，历史全部留档也就几 MB。

---

## 三档配置

| 档位 | 配置 | 价格（大陆小厂估） | 适合 |
|---|---|---|---|
| 🟢 能跑 | 1 核 / 1 GB | ¥30-40/月 | 每天几十次体检 |
| 🔵 舒服 | 2 核 / 2 GB | ¥70-90/月 | 同时跑多个任务，或想内存宽裕 |
| 🟢 先试 | Render 免费版 | **¥0** | 试水、演示、自己用 |

1G 内存装完系统剩 600MB，扫描占 100MB，绰绰有余。

**部署完先跑一遍验收：**

```bash
./tools/guard_smoke.sh
```

11 个用例挨个打 SSRF、限流、并发、黑名单四道闸。全绿才算部署成功——
单测绿不代表容器里的闸活着。

---

## 免费版的三个坑

比配置重要得多。

### 1. 带宽是真瓶颈，不是内存

抓 1000 页大概要下载 **100 MB** HTML。免费套餐通常只有 1GB/月，**扫十来个大站就吃光**。

真拿它干活，这个得先算清楚。

### 2. 15 分钟空闲就休眠

别人第一次打开你发的链接大概率白屏，得刷新一次。
Render 会在日志里显示 `Service is live`，等它变 `running` 再给链接。

### 3. 超时请求会被杀掉

扫 100 页要 5 分半，免费版必挂。所以 `render.yaml` 里默认 `max_pages` 压到 **30 页**（90 秒内）。

**结论：免费版够当演示，不够当生产。**

---

## 选平台：哪些不行

| 平台 | 行不行 | 为什么 |
|---|---|---|
| Cloudflare Pages | ❌ | 静态托管，只发 HTML/CSS/JS |
| Netlify | ❌ | 同上 |
| EdgeOne Pages | ❌ | 同上 |
| GitHub Pages | ❌ | 同上 |
| **Render** | ✅ | 有容器，能跑 Python 服务 |
| Railway | ✅ | 同上 |
| Koyeb | ✅ | 同上 |
| Fly.io | ✅ | 同上，但免费额度政策常变 |
| 自建云服务器 | ✅ | 最自由，也最省心 |

**判断标准很简单：能不能跑一个「去访问别人网址」的 Python 进程。**

SEO-Claw 的本质是「用户给个网址，服务端去访问它、抓回来、审计」。
静态托管环境里根本没法执行这个动作。

> 注意：**EdgeOne Pages 支持边缘函数**，但那是 JS/Worker 模型，
> 跑不了 Python 的 lxml/trafilatura。别被「函数」两个字骗了。

---

## 数据库必须换

免费版和单机场景可以用 SQLite，但：

⚠️ **SQLite 只适合单进程单机。** 它没有并发写保护，两个人同时扫就锁库。

上生产请用 PostgreSQL。`render.yaml` 里已经默认配好了：

```yaml
- key: DATABASE_URL
  fromDatabase:
    name: seoclaw-db
    property: connectionString
```

⚠️ 但 Render 的**免费 PostgreSQL 只活 30 天**，到期自动删、库一起没。
要长期留住数据得换付费的，或自己托管一个 PG。

---

## 四道闸（公网部署前必看）

代码里有四个守卫，都在 `backend/seoclaw/web/guard.py`。
它们挡的不是「服务器被打」，而是**你替别人担责**。

| 闸 | 挡谁 | 触发时 |
|---|---|---|
| **SSRF** | 填 `169.254.169.254` 偷云平台 IAM 凭据 | 400 |
| **限流** | 一个人狂刷，把你 IP 当爬虫使、被目标站拉黑 | 429 |
| **并发** | 一群人各刷一次，10 个爬虫同时打你的 IP | 503 |
| **黑名单** | 拿你的服务器去反复抓**别人的**站 | 403 |

### 最要命的是 SSRF

Web 端本质是「用户给个网址，服务端去访问它」。放到公网上，
等于把整台机器的出网能力交给任何陌生人。

攻击者填 `http://169.254.169.254/latest/meta-data/iam/security-credentials/`，
云平台把容器的 IAM 凭据**原文返回**。拿到就能横向拿整个项目的数据、以你的身份调 API。

Render / AWS / GCP / 阿里云全都有这个地址。

### 残余风险（说清楚，不假装堵死了）

这一层**减少攻击面，不是消除**。还挡不住两类：

1. **DNS rebinding** —— 提交时解析返回公网 IP 通过校验，真正建连时返回 `127.0.0.1`
2. **302 跳转内网** —— 外站跳转到 `169.254.169.254`

彻底堵需要 socket 层 connect-time 校验（自己实现 httpx 的 transport 钩子），
那是改架构的事。**真正的护栏是网络层的 egress 策略**——Render 上限制出网目的地。

### 黑名单怎么加

```bash
# 方式一：改 denylist.txt（每请求读一次，改完立即生效，不用重启）
echo "competitor.example  # 2026-10-03 对方要求停止" >> denylist.txt

# 方式二：环境变量（容器部署）
SEO_DENYLIST=competitor.example,other.example
```

子域一起挡：写 `example.com` 会连 `www.example.com` 一起拦。
但**不会**误伤 `notexample.com`。

### 限流的真实强度

进程内限流。**多进程部署时每个进程各限各的**，总配额会被放大 N 倍。

Nginx 层按 IP 限流才是主防线，应用层这个是兜底。
单进程（`--workers 1`）时它就是完整的。

---

## 上线检查清单

```
[ ] ./tools/guard_smoke.sh 全绿（11/11）
[ ] DATABASE_URL 指向 PostgreSQL，不是 SQLite
[ ] 端口只绑 127.0.0.1，公网入口交给 nginx（有 TLS 和限流）
[ ] denylist.txt 已按需填写
[ ] 已知悉：SSRF 那层不能替代网络 egress 策略
[ ] 日志有轮转上限（compose 里已配 10m × 3）
```

---

## 更新已有部署（改了代码怎么生效）

⚠️ **拉了代码 ≠ 生效。** 服务加载的是**进程启动时**的代码，
静态页面还有浏览器缓存。两层都要处理，少一层就会出现
「怎么打开还是旧界面」：

```bash
# 方式 A：源码部署（venv / pip install -e）
git pull
pip install -e ".[api]"          # 依赖有变时才需要
# 重启 uvicorn / systemd 服务 —— 不重启就还在跑旧代码

# 方式 B：Docker 部署
git pull
docker compose up -d --build      # --build 不能省：镜像里是构建时的代码
```

浏览器侧：**Ctrl+F5（或 Cmd+Shift+R）强刷一次**——`static/index.html`
会被浏览器缓存，普通刷新可能仍是旧页面。

**怎么确认真的更新了（30 秒三步）：**

1. 打开 `GET /api/v1/health` —— 字段 `stale: true` 表示
   **磁盘代码比运行中的进程新**：你拉了代码但没重启；
2. 看页面品牌：新版是「SEO-Claw」纸白界面，旧版是「SEOClaw」深色界面；
3. 版本号：`seoclaw --version`（或 `python -m seoclaw.cli --version`）。

⚠️ **2026-10 仓库结构扁平化提醒**：代码从 `SEOClaw/` 子目录上移到了仓库根。
如果你的启动脚本 / systemd / Dockerfile 里写着 `.../SEOClaw/backend` 这类
路径，pull 之后要改成 `.../backend`；`PYTHONPATH` 同理。

---

## 常用命令

```bash
./tools/guard_smoke.sh                    # 四道闸真容器验收
docker compose up -d                      # 起服务
docker compose logs -f                    # 看日志
pytest backend/tests -q                   # 624 个测试
python -m seoclaw.cli rules               # 规则清单（默认注册表 39 条）
python -m seoclaw.cli --version           # 版本号
```
