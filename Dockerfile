# SEOClaw 在线体检服务
#
# ⚠️ 镜像里不装浏览器。`--render-js` 需要 Chromium（约 400MB），
# 那属于「可选的重量级能力」，不该让每个部署都背这份体积。
# 需要 JS 渲染的部署请另开 `Dockerfile.render-js` 那种加层。
FROM python:3.12-slim

# curl 用来跑健康检查；ca-certificates 用来抓 https 站点
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# ⚠️ 先装依赖再拷代码：改代码不会让依赖层缓存失效。
# 顺序反了的话，每次改一行 README 都要重装一遍 lxml/trafilatura。
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir fastapi uvicorn

COPY pyproject.toml ./
COPY backend/ ./backend/

# ⚠️ 不用 root 跑服务。扫描器要去外网请求，容器逃逸面越小越好。
RUN useradd --create-home --shell /usr/sbin/nologin seoclaw \
    && mkdir -p /srv/data \
    && chown -R seoclaw:seoclaw /srv
USER seoclaw

ENV PYTHONPATH=/srv/backend \
    PYTHONUNBUFFERED=1 \
    SEO_CLAW_DATABASE_URL=sqlite+aiosqlite:////srv/data/seoclaw.db

EXPOSE 8000

# 容器健康检查。⚠️ 探 /api/v1/health 而不是 /：后者会返回整个首页 HTML，
# 几 KB，白白传给 Docker daemon，而且页面挂掉跟服务挂掉不是一回事。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

CMD ["uvicorn", "seoclaw.main:app", "--host", "0.0.0.0", "--port", "8000"]
