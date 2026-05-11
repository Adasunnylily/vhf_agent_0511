# AutoDL 故障排查

## FunASR 下载/加载后进程显示 `Killed`

现象：

```text
Downloading Model from https://www.modelscope.cn ...
WARNING:root:trust_remote_code: False
Killed
```

含义：进程通常被系统 OOM killer 杀掉，常见原因是多个上传任务并发触发模型下载/加载，或者显存/内存不足。

0511 版本已在 `app/services/asr.py` 中加入模型加载锁和推理锁：

- 同一个 ASR 模型只会初始化一次。
- 多个后台任务会排队调用同一个模型，不会同时 `generate`。

服务器同步：

```bash
cd /root/autodl-tmp/vhf_agent_0511
git pull --rebase
```

重启服务后再试。

## 仍然被 Killed 时

1. 先只上传一个短音频，不要连续点多次上传。
2. 确认服务进程已完全重启，避免旧进程还占显存：

```bash
pkill -f "uvicorn app.main:app" || true
nvidia-smi
```

3. 如果显存很小，先把 `.env` 改为 CPU 或换更小模型：

```bash
VHF_ASR_DEVICE=cpu
```

4. 如果模型已经下载过，可确认缓存目录：

```bash
ls /root/.cache/modelscope/hub/models/iic/SenseVoiceSmall
```

5. 如果下载阶段重复失败，先在服务器上单独预热一次模型，再启动 Web 服务。
