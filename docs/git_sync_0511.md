# Git 版本管理与服务器同步

0511 版本建议作为独立 Git 仓库管理，只同步代码，不同步音频数据、模型缓存、评测输出和 `.env`。

## 1. 本地初始化

```bash
cd vhf-agent-0511
git init
git add .
git commit -m "init vhf agent 0511"
```

如果首次提交提示没有用户信息：

```bash
git config user.name "your-name"
git config user.email "your-email@example.com"
```

## 2. 连接远端仓库

在 GitHub/Gitee/GitLab 创建空仓库后：

```bash
git remote add origin git@github.com:YOUR_NAME/vhf-agent-0511.git
git branch -M main
git push -u origin main
```

如果 AutoDL 服务器不方便配置 SSH key，也可以先用 HTTPS remote。

## 3. AutoDL 首次拉取

```bash
cd /root/autodl-tmp
git clone git@github.com:YOUR_NAME/vhf-agent-0511.git
cd vhf-agent-0511
bash scripts/setup_autodl_0511.sh
```

## 4. 本地改完同步到服务器

本地：

```bash
cd vhf-agent-0511
git status
git add .
git commit -m "update 0511 asr eval workflow"
git push
```

服务器：

```bash
cd /root/autodl-tmp/vhf-agent-0511
git pull --rebase
```

如果服务已经在跑，拉取后重启：

```bash
pkill -f "uvicorn app.main:app" || true
bash scripts/start_autodl.sh
```

## 5. 服务器上产生的数据不要提交

以下内容已由 `.gitignore` 排除：

- `.env`
- `.venv/`
- `data/`
- `outputs/`
- `models/`
- `model_cache/`
- `*.zip`

音频、人工标注、评测结果建议放在 AutoDL 数据目录，例如：

```text
/root/autodl-tmp/vhf-data/
```

如果后续人工标注文本需要版本管理，建议只提交脱敏后的小规模标注清单，或者单独建私有数据仓库。
