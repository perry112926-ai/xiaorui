# Pipecat 独立技术验证

验证版本：`pipecat-ai==1.15.0`，Mac arm64 / Python 3.12。实验不接入正式路由，不读取资料卡或生产历史，不提供业务工具。凭据只从本地忽略的 `.env` 读取；音频和原始报告写入忽略的 `.local-data/pipecat-proof/`。

## 运行

```sh
uv venv .local-data/pipecat-proof/.venv --python .venv/bin/python
UV_HTTP_TIMEOUT=600 uv pip install --python .local-data/pipecat-proof/.venv/bin/python -r experiments/pipecat_proof/requirements.lock.txt
.local-data/pipecat-proof/.venv/bin/python -m experiments.pipecat_proof.media
.local-data/pipecat-proof/.venv/bin/python -m experiments.pipecat_proof.probe --live --turns 10 --audio-turns 10
.local-data/pipecat-proof/.venv/bin/python -m experiments.pipecat_proof.turns
```

`--live` 会调用已配置的真实模型和语音 API，使用固定的合成中文闲聊；会产生对应接口用量。可用 `--model` 对比账号已开通的其他模型，不会修改当前产品配置。`requirements.txt` 是直接依赖，`requirements.lock.txt` 固定本轮隔离安装的完整版本；正式项目没有新增 Pipecat 依赖。

## 验证什么

- `probe.py`：真实 Pipecat PipelineWorker、Ark 流式 LLM 和自定义豆包 PCM TTSService；前 N 轮把合成语音按实际时长送到真实 ASR。TTS复用连接池，按框架句子增量合成，无固定占位音频和第二次播报改写。长期记忆与交易不在本原型范围。
- `asr.py`：单遍流式识别，显式结束音频；记录发送完最后一包到最终转录的时间。不能把这个结束策略称为自动判断老人说完了。
- `media.py`：Pipecat SmallWebRTC 两端本机连接，分别发送合成音调，双向各接收至少25帧非静音音频。没有浏览器和物理麦克风。
- `turns.py`：实际运行包内 Silero VAD 和 Smart Turn ONNX，检查一段中文合成语音的截断片段与完整句子；不代表中文、方言、长停顿的普遍正确率。
- `evaluation.py`：拒绝让固定提示音、文字测量、手工结束或单独服务器帧测试通过完整电话验收。评分区分服务器收音、合成和浏览器播放。

[隔离运行记录](../../docs/acceptance/pipecat-isolated-2026-11-06.json)
