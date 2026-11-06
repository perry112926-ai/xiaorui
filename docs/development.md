# 开发地图：从一个行为找到代码、状态与验证

[架构](../ARCHITECTURE.md)解释系统如何协作；本文帮助开发者定位改动。先读[CONTRIBUTING](../CONTRIBUTING.md)与[AGENTS](../AGENTS.md)，环境见[setup](setup.md)。当前主线为React与FastAPI，不包含Flutter或手机自动化适配。

## 按需求找到维护入口

| 要改的行为 | 实现入口 | 首选回归测试 |
|---|---|---|
| 发送、重复点击、回复位置、恢复 | `frontend/src/main.tsx`、`app/contact.py`、`contact_events.py` | `frontend/tests/app-events.test.cjs`、`tests/test_contact.py` |
| 电话起止、时长、文字隔离 | `CallBar.tsx`、`main.tsx`、`app/contact.py` | `call-bar.test.cjs`、`test_phone_calls.py`、`test_phone_api.py` |
| 录音、停顿、迟到权限、插话 | `useVoice.ts`、`app/voice.py`、`voice_protocol.py` | `frontend/tests/voice.test.cjs`、`tests/test_voice.py` |
| 渐进TTS与票据 | `useVoice.ts`、`app/voice.py` | `voice.test.cjs`、`test_voice_stream.py` |
| 口语重点与关键事实 | `app/speech.py`、`agent.py` | `test_speech.py`、`test_speech_host.py` |
| 普通偏好、忘记、会话恢复 | `foundation_store.py`、`agent.py`、`nanobot_runtime.py` | `test_foundation_store.py`、`test_agent.py` |
| 人工确认资料 | `ProfileCard.tsx`、`profile_card.py`、`main.py` | `test_profile_card.py` |
| 新增查询工具 | `skills.py`、领域适配器、`read_only.py`、`progress.py`、`skills/` | 对应工具测试＋`test_agent.py`＋`test_read_only.py` |
| 麦当劳地址、购物车与核价 | `mcd_scenario.py`、`mcd.py`、`actions.py` | `test_mcd_address.py`、`test_mcd_elderly.py`、`test_mcd_scenario.py` |
| 滴滴／瑞幸流程 | `didi_scenario.py`、`luckin_scenario.py`、`life_services.py` | `test_didi_scenario.py`、`test_luckin_scenario.py` |
| 高德与定位 | `amap.py`、`location.py`、`frontend/src/location.ts` | `test_amap.py`、`test_location.py`、`frontend/tests/location.test.cjs` |
| 交易确认与未知结果 | `actions.py`、旧`plans.py`、`main.py` | `test_actions.py`、`test_actions_api.py`、`test_confirmation.py` |
| 凭据与网络边界 | `settings.py`、`main.py`、`service_transport.py` | `test_settings.py`、`test_read_only.py`、`test_service_transport.py` |
| 图片 | `attachments.py`、`main.tsx` | `test_attachments.py` |
| Cron基础生命周期 | `foundation_scheduler.py` | `test_foundation_scheduler.py`；用户提醒尚未开放 |

上表测试名称以`tests/`和`frontend/tests/`为准，升级依赖或重构时同步维护。前端测试使用Node与TypeScript转译执行交互逻辑，不是完整浏览器／真机覆盖。

飞猪查询和组件准备分别维护在 [fliggy.py](../app/fliggy.py) 与 [fliggy_setup.py](../app/fliggy_setup.py)，测试见 [test_fliggy.py](../tests/test_fliggy.py) 与 [test_fliggy_setup.py](../tests/test_fliggy_setup.py)。记忆证据与召回维护在 [companion_memory.py](../app/companion_memory.py)，相关测试见 [test_companion_memory.py](../tests/test_companion_memory.py) 与 [test_memory_capabilities.py](../tests/test_memory_capabilities.py)。

## 新能力进入系统的最小路径

1. **确定业务边界。** 输入来自用户、记忆或真实候选？输出是否会产生费用、发送数据或改变外部状态？先写明确的失败和未知语义。
2. **实现适配器。** 固定官方目标，验证真实返回，不接受模型任意URL，不拿假数据作为运行时回退。
3. **声明工具schema与注册。** 在宿主显式允许，沿用参数校验、模型安全数据过滤和真实进度。Skill文本是使用说明，不能授予执行权限。
4. **外部写操作走确认层。** 模型只能提案；绑定owner、方案版本、有效期、确认凭据，重核价与预算。任何超时未知不自动重试。
5. **持久状态与恢复。** 说明存哪里、如何兼容旧库、重启是否恢复／中断；不能默认所有任务都可安全再执行。
6. **测试并同步文档。** 覆盖错误、重复、旧版本、权限与生命周期；更新能力表、架构、配置模板和待发布日志。真实联调另按授权进行。

## 三条不要混淆的边界

- **记录与召回**：SQLite历史存在，不代表模型每轮看见；当前事实取结构化资料，详见[memory](memory.md)。
- **流式与实时对话**：SSE文字delta、ASR字幕、TTS音频块是不同流；渐进播放不等于模型全双工。
- **收件回执与业务成功**：202表示已接收；completed是本轮处理结束；订单创建／支付／送达必须分别核实。

## 日常验证

```sh
uv sync --locked --python 3.12
npm --prefix frontend ci
uv run --no-sync python -m unittest discover -s tests -q
node --test frontend/tests/*.test.cjs
npm --prefix frontend run build
git diff --check
```

文档修改检查描述、链接和命令即可，无需重复付费联调。功能变更先跑相关测试；前端需构建。仓库跟踪`frontend/dist/`，交付前核对构建与源码一致，不把无关构建差异混入PR。

## 证据文件怎么写

放入`docs/acceptance/`的去敏报告应包含：日期、实际commit、系统／浏览器、配置存在与远端通过的区别、脚本和退出码、样本与失败数、是否使用真人／测试桩、是否调用外部写操作、未测项和回退方式。

真实价格和时延是当次快照。对比时保持测量边界一致；单样本不同长度回复不能推导稳定改善比例。不要提交原始手机号、住址、cookie、密钥、订单号、支付链接、完整转录或截图中的隐私内容。

代码审阅完成不等于发布。按本轮任务要求决定暂存、提交与推送；只有明确授权的发布动作才更新远端。维护者正式发版时另补tag、兼容变更、数据迁移及回退说明。
