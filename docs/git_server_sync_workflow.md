# Git 与服务器同步工作流

本项目固定使用 Git 同步本地和 AutoDL 服务器代码。不要直接在服务器手改业务代码，否则下一次 `git pull` 会产生版本分叉。

## 架构

```text
本地工作区
  -> git commit + git push
GitHub rollback-0521-1620 分支
  -> 服务器 git pull
AutoDL FastAPI 后端 :8000
  -> ui_prototype/server.py 代理 /api/*
AutoDL 原型界面 :8766/maritime_ai_agent.html
```

`8766` 必须通过 `scripts/start_ui_prototype.sh` 启动。不要使用 `python -m http.server 8766`，因为普通静态服务器不会把 `/api/*` 转发给 FastAPI。

## 一键同步

在本地执行：

```bash
cd "/Users/adasunnylily/Documents/New project/vhf-agent-0511"
bash scripts/sync_to_server.sh "feat: describe current change"
```

脚本依次执行：

1. 提交本次相关文件。
2. 推送 `rollback-0521-1620` 分支。
3. 登录服务器并执行 `git pull --ff-only`。
4. 重启 `8000` FastAPI 后端和 `8766` 原型网关。
5. 请求健康检查和公开配置接口。

## 手动检查

服务器执行：

```bash
cd /root/autodl-tmp/original/autodl-tmp/vhf_agent_0511
git rev-parse --short HEAD
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8766/api/config/public
```

浏览器打开：

```text
http://服务器地址:8766/maritime_ai_agent.html?v=当前提交号
```

查询参数用于绕过浏览器缓存。页面接口由 `8766` 网关转发到 `8000`。
