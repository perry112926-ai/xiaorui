# 实时电话架构调研与短回应实验复盘

## 最新结论：固定短回应未满足实时聊天

用户实测反馈是反复“我在，您说”，无法自然聊天。此前249／348ms只证明固定音频能很快播放，不能作为语义接话或完整电话效果通过的证据。停止以短回应速度作为主要验收指标。

### 当前链路的实际问题

- `useVoice.ts` 在240ms短停顿时，用尚未到达的转录默认值“喂”选择固定音频；不能判断对方的真实意图与是否说完，还可能抢话。每次恢复说话清除回应记录，容易再次触发。
- ASR按轮新建连接，等待最终转录后才提交Agent；partial目前只显示字幕。减少固定静音阈值不能消除识别、模型首字和合成等待。
- `agent.py` 的电话分支等待整轮生成，复杂回答还等待播报改写；`main.tsx` 不消费电话delta来播放，仅在completed后调用speak。现有TTS“流式”是拿到完整文案后的音频流，尚未形成模型文字到语音的贯通流水线。
- 插话主要停本地播放器；尚无按真实已播放片段截断模型历史的完整机制。停止播放、取消推测回答、取消业务执行必须分别处理。

### GitHub架构核查

以下为阅读官方文档、README和指定源码后的结论，未在本机部署这些框架，也未验证其宣传时延。

| 项目 | 核查到的实现 | 借鉴与限制 |
| --- | --- | --- |
| [Pipecat基础语音源码](https://github.com/pipecat-ai/pipecat/blob/main/examples/getting-started/06-voice-agent.py) | 输入、STT、用户上下文、LLM、TTS、输出、助手上下文组成Pipeline；[轮次策略](https://docs.pipecat.ai/api-reference/server/utilities/turn-management/user-turn-strategies)区分起说、结束与打断，支持Smart Turn | 优先验证的语音编排层。适合现有Python/FastAPI；当前豆包ASR/TTS协议需确认适配，不能假设可直接插入；模型慢仍然会慢 |
| [LiveKit Agents](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent_activity.py) | AgentSession管理媒体、轮次和语音句柄；[预生成](https://docs.livekit.io/reference/agents/turn-handling-options/)可在轮次确认前推测生成；[打断](https://docs.livekit.io/agents/logic/turns/)后按已播放内容截断历史 | 借鉴轮次状态、推测取消与已听历史同步。完整采用会增加RTC服务与部署工作；部分增强能力有独立服务条件 |
| [TEN级联示例](https://github.com/TEN-framework/ten-framework/blob/main/ai_agents/agents/examples/voice-assistant/README.md)及[Realtime示例](https://github.com/TEN-framework/ten-framework/blob/main/ai_agents/agents/examples/voice-assistant-realtime/README.md) | 分别提供STT→LLM→TTS和语音到语音模型两种图，RTC与模型插件分开 | 借鉴双路线和可换供应商，不把RTC等同于语义实时。示例需要Agora与对应模型凭证，不能当作当前账号已可用 |
| [小智服务端流式对话源码](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/main/main/xiaozhi-server/core/connection.py) | chat循环将LLM增量送入tts_text_queue，句子ID与首／中／尾消息组织播放；client_abort和清队列处理打断 | 最直接证明普通文本模型也可边生成边合成。当前设备协议及线程管理不整套搬入网页；不能保证任意模型低延迟 |
| [FireRedChat](https://github.com/FireRedTeam/FireRedChat) | LiveKit、ASR、TTS、LLM及中文／英文轮次检测，可自托管 | 后续自托管参考；仍需模型服务与算力评估。README标注的Context-Aware TTS和Audio LLM为Coming soon，不能说均已交付 |

### 小瑞建议架构（待实现、待实测）

浏览器持续双向音频 → 独立语音会话层（优先Pipecat原型） → 实时对话模型，或贯通的流式ASR→低首字LLM→增量TTS → 持续音频输出。

[SmallWebRTC](https://docs.pipecat.ai/api-reference/server/services/transport/small-webrtc)可由浏览器直接连接Python端，不必先部署独立媒体集群；仍需信令，跨网络要评估STUN/TURN。改善传输不代表消除了模型推理等待。

语音会话负责直接闲聊、当前问题、打断及有意义的进度；现有nanobot负责生活服务工具、记忆及持久任务。只暴露受约束的查询／准备方案接口，真实交易继续经过宿主确认。慢查询作为独立任务，结果携带call_id、turn_id、task_id；用户换话题或挂断后不播放过期结果，不把“打断说话”等同于撤销已提交订单。语音与文字共用权威资料和业务记录，语音模型不自行改写资料卡。

首次接通允许一句欢迎；普通停顿不强制插话。内容已理解且任务真正开始时，才自然说具体承接，例如“您想去大兴机场，我先查一下车型”。普通闲聊直接回答，不每轮再加一句占位。口语作为主模型的直接输出，屏幕卡片承载明细，避免每轮串行再调一个播报编辑器。价格和确认资料只能使用已核实结果；推测生成不得执行交易。

### 实施与验收顺序

1. 隔离原型先验证语音模型权限；实时模型不可用时明确降级为流式级联。比较中文识别、内容接话首音、打断、模型首字和成本，再决定接入。现有模型首字约数秒时，换框架本身不能保证1秒内语义回复。
2. 先跑不带业务工具的10轮中文自然聊天；接通招呼、自由回答、改口、长停顿、插话后追问均须通过。记录从最后有声帧到**与本句内容相关**的首音，固定音频不计入。目标中位数≤1秒、P95≤2秒，打断到静音P95≤300ms；这是新目标，不是实测成绩。
3. 接入一个只读慢查询，处理中仍能接话；验证改口、过期结果、已听历史同步、模型错误不会变成重复占位语。然后接资料和现有确认卡片，验证回声不触发确认。
4. 最后真人物理麦克风连续通话，检查耳机和扬声器、回声、噪声、老人长停顿与网络中断。未通过前只称原型，不称达到真人电话效果。

以下保留此前短回应实验与证据边界，作为历史复盘。

验收要求：说“喂”能迅速听到“我在”；每轮先有承接，查询结果允许稍晚；用户再次开口立即打断；不能把收到请求说成任务已完成。

## 参考项目

- [LiveKit Agents：用户轮次完成回调](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent.py)：`on_user_turn_completed` 可发短回应；借鉴独立 `say` 和可打断语音句柄，不让短回应等待完整 LLM 回复。参考[抢先生成与打断](https://docs.livekit.io/agents/multimodality/audio/)。
- [Pipecat](https://github.com/pipecat-ai/pipecat)：语音帧流水线与独立打断事件；借鉴播放中断和后台任务分离。停止说话不等于取消交易，已有真实写操作仍按宿主台账处理。
- [TEN Framework](https://github.com/TEN-framework/ten-framework)：用于实时语音代理的整体框架参考；本轮没有引入其运行时或新增媒体服务器。

本轮是根据这些公开接口和架构模式实现当前项目的短回应通路，没有复制上游源码、安装整个框架或改变业务执行授权。

## 当前实现

- `callFeedback.ts`：本地固定语音包与意图选择，音频预加载。固定内容仅包括“我在，您说”“嗯，听到了”“我帮您看看”“您慢慢说”“我先核对一下”，不包含任何价格、结果或执行成功声明。
- `useVoice.ts`：检测到说话后的约240ms短停顿即可回应；无需等待ASR最终文本、大模型或云端TTS。转录尚未返回时先说“我在”，识别到查询请求后可进一步承接。短回应不提交尚未说完的文字。
- 单独的“喂”“在吗”“等一下”在通话中本地处理，不另排一次模型回答；同轮最终转录不重复播放已给出的回应。普通语音消息仍按原发送逻辑处理。
- 再次说话触发打断；挂断取消未开始的短回应，防止迟到播报。重要确认仍由原宿主机制验证，短回应不构成执行授权。
- 语音文件是当前豆包TTS合成的固定提示音，裁掉多余静音后作为WAV随前端交付；不含用户录音或个人资料。修改默认音色时应同步重制语音包。

## 验证边界

真实TTS与ASR准确识别合成的“喂”和天气请求；真实浏览器使用生产AudioWorklet、虚拟合成音频输入及真实ASR，两次最后有声帧到原生播放器开始播放为249ms、348ms。直接播放短回应的观察为16–22ms。这些是测试环境观察，不是所有设备的性能保证。

最后有声帧来自浏览器音量检测；播放事件不等于耳朵听到首个音素。未录制真人麦克风，房间回声、噪声误触发、方言仍须现场验收；本轮未声称已接入端到端语音模型。一次直接全双工端点探测返回HTTP403，未将其作为可用能力。
