# 更新记录

本文件按 Git 历史整理小瑞的演进，帮助读者看清“哪次改进解决了什么问题”，并能回到代码与验收证据。

**早期历史基线：上游 `main` 的 [`2216add`](https://github.com/perry112926-ai/xiaorui/commit/2216add)，2026-11-05。**目前没有发布 tag；`pyproject.toml` 中的 `0.1.0` 是包元数据，不代表以下阶段已发布为多个正式版本。日期取自提交记录，时区差异可能使主线与实验分支的同一阶段显示不同日期。

## 待发布 · 文档完善

本轮正在整理 README、架构、记忆实现、开发指南及本更新记录。它们是文档改进，尚未创建发布版本，不表示新增语音模型、记忆算法或生活服务。后续发布时由维护者补充实际提交与发布标签。

## 2026-11-06 · 飞猪机票、语音与记忆

- 飞猪支持家人设置、固定版本组件、公开航班连接检查、聊天卡片和官方预订跳转。真实航班与浏览器恢复通过，结算由用户在飞猪完成。见[飞猪验收](docs/acceptance/fliggy-family-2026-11-06.json)。
- 文字正文可先交付，后台准备播报。电话去掉普通停顿中的重复占位语。Pipecat 已通过独立合成语音和双向 WebRTC 验证，正式入口沿用 ASR、Agent 与 TTS。见[电话交互](docs/phone-interaction.md)。
- 新增带原话证据的偏好整理、检索和主题遗忘，加入旧任务召回屏障。见[记忆评估](docs/evaluations/personal-agent-2026-11-06/results.md)。

以下各阶段链接显示首个纳入的提交及末尾提交。GitHub Compare 使用阶段之前的提交作为比较基点。

## 2026-11-05 · 查询覆盖与老人交互验证

主线范围：[`1855c1b…2216add`](https://github.com/perry112926-ai/xiaorui/compare/5bd374e...2216add)。

- **新增高德只读查询**：地点搜索、地理编码、步行／驾车路线及实时天气接入现有工具宿主；固定官方 REST 端点，保留距离、耗时和报告时间。路线是快照，不是持续导航。
- **修复实际交互路径**：未完成请求的重复发送去重、通话中打开设置不误挂断、“＋”中的挂断行为一致，并延长部分明确犹豫词后的等待。
- **校准能力说明**：明确麦当劳点餐、独立瑞幸饮品与高德餐厅搜索的边界，不将其他餐厅查询写成通用外卖下单能力。
- **补充验收证据**：高德公开地标／路线／天气查询、真实模型天气工具轨迹及老人模拟交互记录。最新该阶段记录为后端241项、前端51项测试与构建通过；这些数量是当时快照，非持续 CI 承诺，也不代替真人体验。
- **重写使用入口说明**：配置、确认、当前可用能力和未完成事项集中到 README。

证据：[高德接入](docs/amap.md) · [老人交互场景](docs/acceptance/elderly-interaction-scenarios.md) · [模拟对话记录](docs/acceptance/elderly-dialogue-2026-11-05.json)。

## 2026-11-05 · 通话与消息各自清楚，保留同一持续对话

主线范围：[`518b7d5…5bd374e`](https://github.com/perry112926-ai/xiaorui/compare/8cbda71...5bd374e)。

- **恢复文字输入基本习惯**：覆盖输入、键盘发送、中文输入法与换行；不把切换语音作为打字的前置条件。
- **独立通话界面**：顶部通话控制、时长与明确挂断；通话不逐句刷屏，必要操作卡片仍进入聊天，结束后保留时长记录。
- **通话期间可继续发文字**：区分 call_id 与普通消息通道，避免不同通道互相覆盖播报。
- **每条消息显示真实进度**：进度和合并回复附着具体请求，用户能看出哪些内容已收到、正在处理或已完成。

限制：底层处理记录可能仍保存转录；当前通话仍为 ASR → Agent → TTS，不是端到端全双工语音模型。电话纯文本核查、拒播恢复、慢停顿和真人听感仍需专项验证。

证据：[电话交互](docs/phone-interaction.md) · `tests/test_phone_calls.py` · `tests/test_phone_api.py` · `frontend/tests/call-bar.test.cjs`。

## 2026-11-05 · 选择性整合陪伴角色、家人设置与语音控制

主线提交：[`8cbda71`](https://github.com/perry112926-ai/xiaorui/commit/8cbda71)。

从用户实验分支的 `60f4425` 选择性吸收角色素材、昵称／头像设置、家人服务配置、录音释放与取消、迟到结果隔离、实际工具进度及只读模式。保留主线自己的整段渐进语音播放、布局和后续定位／地址逻辑。

**未整合**实验分支的整页暖色侧栏重设计、输入框长按语音、逐句音频预取、Flutter 客户端和 Linux 启动工具。PR 的取舍不等于整批合并，未整合功能不能写成当前主线已有。

证据：[选择性整合说明](docs/acceptance/pr1-selected-integration.md) · [三平台公开查询记录](docs/acceptance/pr1-selected-public-services.json)。

## 2026-11-05 · 从地点与预算走向可核对的生活服务方案

主线范围：[`1e1a416…beb8d19`](https://github.com/perry112926-ai/xiaorui/compare/e15b2e3...beb8d19)。

- **滴滴取消前先查条件**：绑定本人订单，展示实际条件或明确失败原因；不将本地停止误报为平台取消。
- **麦当劳新增配送地址**：结合经授权的位置或用户地址，核对城市、门牌、联系人与电话，经独立“确认新增地址”后才写入平台。
- **分段补充与多件餐品**：地址草稿逐项补充，购物车支持同店多项商品、数量、删除及整单含费核价；预算和套餐选择受宿主校验。
- **定位反馈收敛**：成功／失败通知短暂显示后收起，避免占据聊天。

边界：地址新增属于外部写入，订单执行开关关闭不等于该写入禁用；强制只读模式会拒绝新增地址。真实订单、支付、取消和退款仍分别依赖确认与官方回执，代码覆盖不代表配送到家已验收。

证据：[麦当劳老人场景](docs/acceptance/mcd-elderly-scenarios.md) · [服务边界](docs/services.md)。

## 2026-11-05 · 可确认资料、短期定位与渐进语音播放

主线范围：[`7348a2b…e15b2e3`](https://github.com/perry112926-ai/xiaorui/compare/cd9f27f...e15b2e3)。

- **个人资料卡**：家庭地址、本人及联系人电话由人工核对保存；普通偏好与重要资料分开，模型不能直接覆盖重要字段，变更使旧方案失效。
- **临时浏览器定位**：显式权限、精度和120秒有效期检查，按 owner 隔离；过期位置不能继续批准旧出行方案，也不会自动成为家庭住址。
- **渐进 MP3 播放**：一次性、短时有效、owner绑定的票据连接原生音频播放器，上游音频块可边到边播；短回复减少额外口语改写。
- **授权提示可操作**：定位失败时解释浏览器限制，提供重新授权或地标回退。
- **验证与运行边界**：补充三平台真实服务证据、报价限流处理、环境变量优先级说明，以及功能修改须自动测试的协作要求。

延迟记录仅为单次服务端观测，未包括真人收音、ASR及浏览器实际出声；前后文本长度和测量边界不同，不计算稳定提速百分比。

证据：[定位说明](docs/location.md) · [语音延迟记录](docs/acceptance/voice-latency-live-2026-11-05.json) · [服务联调记录](docs/acceptance/services-live-2026-11-05.json)。

## 2026-11-05 · 联系人式交互与三平台受控工作流

主线范围：[`32cc876…cd9f27f`](https://github.com/perry112926-ai/xiaorui/compare/18b2430...cd9f27f)。

- **屏幕正文与播报分开**：独立 `speech_text`，根据预算、改口与选项组织短口语；关键交易事实由宿主组合。
- **持久消息收件箱**：client_id去重、补充消息合并、SSE事件、图片处理与任务回执；重启中断不自动重放交易。
- **三家生活服务场景**：麦当劳、瑞幸、滴滴的真实候选／核价／具体方案／确认／本人记录查询，以及共享交易台账。
- **收紧执行授权**：模型准备方案，宿主绑定owner、版本、有效期及明确确认，金额或内容变化需重新确认，未知状态不盲目重试。
- **产品方向与文档整合**：明确老人自主生活、家人前期协助及后续陪伴方向，保留原始任务和研究证据。

这些实现形成查询到受控执行的基础，不代表所有平台、支付、取消或完整老人语音闭环已通过。

## 2026-11-04 · 本地助手原型与持久基础

主线范围：[`c702d27…18b2430`](https://github.com/perry112926-ai/xiaorui/compare/c702d27...18b2430)。

- **建立本地产品骨架**：FastAPI、React、Mac启动入口、麦当劳真实查询、具体方案与确认预览。
- **接入固定版本 nanobot 0.4.0**：受控工具、豆包模型、推荐和语音网关；将模型调用与生活服务宿主分开。
- **持久个人基础**：明确个人事实、会话标识、召回代际、候选与每轮执行记录；有基础调度生命周期，但没有可承诺送达的用户提醒。
- **固定聊天导航**并补充后续维护与自动提交规则。

初始实现、真实API探针和架构文档均可从下方提交索引追溯。依赖自身的通用能力不等于小瑞已启用全部能力，尤其不能据框架文档宣称已完成自动长期记忆或主动提醒。

## 独立实验分支：保留探索记录，不计入当前主线能力

用户 fork：[kevinguo0351/xiaorui](https://github.com/kevinguo0351/xiaorui)。以下是与主线分开的历史，不采用正式发布版本号：

| 分支／提交 | 日期（提交记录） | 主要产出 | 主线状态 |
|---|---|---|---|
| `xiaohu_flutter` · `a39133b` | 2026-11-04 | 独立Flutter Web陪伴预览、大麦克风、任务与设置、强制只读入口 | 未合入；不是原生Android／iOS发布 |
| `trial/local-run-rust-assessment` · `1d4a927` | 2026-11-04 | 录音／播报连续性、可见进度与明确停止控制 | 部分能力后来经8cbda71选择性吸收；不是整提交合并 |
| 同分支 · `88785aa` | 2026-11-04 | Linux原版预览启动工具 | 未合入Mac主线 |
| 同分支 · `60f4425` | 2026-11-04 | 暖色侧栏、角色场景、家人设置、输入框长按语音 | 角色／配置等部分吸收；侧栏与长按未吸收 |
| 同分支 · `30d7ccb`、`e6eecad` | 2026-11-05 | Mac／Poki／Tailscale／实时语音交接及PR状态记录 | 交接与设计说明，非已部署的GPT-Live或Poki集成 |

当前主线没有Poki手机工具、GPT-Live／Seeduplex、任意自定义MCP注册、远程HTTPS多用户认证或主动提醒投递。实验分支的规划不应进入“已完成”清单。

## 完整主线提交索引

以下31个提交覆盖从仓库初始化到本记录基线的完整主线可达历史；短标题来自Git提交，可用于核对阶段与代码。初始化合并也保留，避免把阶段摘要当作完整历史。

| 日期 | 提交 | 内容 |
|---|---|---|
| 2026-11-04 | [`c702d27`](https://github.com/perry112926-ai/xiaorui/commit/c702d27) | Initial commit |
| 2026-11-04 | [`a767736`](https://github.com/perry112926-ai/xiaorui/commit/a767736) | Initial commit: local personal assistant project |
| 2026-11-04 | [`4f5df4c`](https://github.com/perry112926-ai/xiaorui/commit/4f5df4c) | Merge GitHub repository initialization |
| 2026-11-04 | [`b1add03`](https://github.com/perry112926-ai/xiaorui/commit/b1add03) | Integrate agent runtime, recommendations, voice, and persistent foundation |
| 2026-11-04 | [`2d46452`](https://github.com/perry112926-ai/xiaorui/commit/2d46452) | docs: require automatic commits after project changes |
| 2026-11-04 | [`18b2430`](https://github.com/perry112926-ai/xiaorui/commit/18b2430) | Keep chat navigation fixed at the top of the page |
| 2026-11-05 | [`32cc876`](https://github.com/perry112926-ai/xiaorui/commit/32cc876) | Add context-aware spoken guidance separate from screen text |
| 2026-11-05 | [`cce110a`](https://github.com/perry112926-ai/xiaorui/commit/cce110a) | Integrate life-service workflows and contact-style interactions |
| 2026-11-05 | [`283cf2f`](https://github.com/perry112926-ai/xiaorui/commit/283cf2f) | Clarify Xiaorui vision for voice assistance, memory, and proactive companionship |
| 2026-11-05 | [`cd9f27f`](https://github.com/perry112926-ai/xiaorui/commit/cd9f27f) | Consolidate project documentation while preserving the original task |
| 2026-11-05 | [`7348a2b`](https://github.com/perry112926-ai/xiaorui/commit/7348a2b) | Validate real life-service flows and reduce DiDi quote throttling |
| 2026-11-05 | [`e6e3968`](https://github.com/perry112926-ai/xiaorui/commit/e6e3968) | Add confirmed personal profile card to the ongoing conversation |
| 2026-11-05 | [`231ba02`](https://github.com/perry112926-ai/xiaorui/commit/231ba02) | Add browser location for rides and streaming speech playback |
| 2026-11-05 | [`e4a5894`](https://github.com/perry112926-ai/xiaorui/commit/e4a5894) | Validate browser location isolation and reject expired ride origins |
| 2026-11-05 | [`c6b5195`](https://github.com/perry112926-ai/xiaorui/commit/c6b5195) | Reduce spoken reply latency with progressive audio playback |
| 2026-11-05 | [`3c3ebeb`](https://github.com/perry112926-ai/xiaorui/commit/3c3ebeb) | Show actionable location authorization in chat and explain browser failures |
| 2026-11-05 | [`486d7bd`](https://github.com/perry112926-ai/xiaorui/commit/486d7bd) | docs: require automatic tests and functional verification |
| 2026-11-05 | [`e15b2e3`](https://github.com/perry112926-ai/xiaorui/commit/e15b2e3) | Document explicitly enabling real DiDi rides and environment precedence |
| 2026-11-05 | [`1e1a416`](https://github.com/perry112926-ai/xiaorui/commit/1e1a416) | Add owner-bound ride cancellation review and actionable failure feedback |
| 2026-11-05 | [`d3c98e6`](https://github.com/perry112926-ai/xiaorui/commit/d3c98e6) | feat: add confirmed McDonald delivery address creation from current location |
| 2026-11-05 | [`5066e4a`](https://github.com/perry112926-ai/xiaorui/commit/5066e4a) | feat: support elderly delivery address drafts and multi-item dining flows |
| 2026-11-05 | [`beb8d19`](https://github.com/perry112926-ai/xiaorui/commit/beb8d19) | Dismiss location result notices after five seconds |
| 2026-11-05 | [`8cbda71`](https://github.com/perry112926-ai/xiaorui/commit/8cbda71) | Integrate selected PR #1 companion, voice controls and family settings |
| 2026-11-05 | [`518b7d5`](https://github.com/perry112926-ai/xiaorui/commit/518b7d5) | Restore original text composer and cover typing and keyboard submission |
| 2026-11-05 | [`205fa3a`](https://github.com/perry112926-ai/xiaorui/commit/205fa3a) | Separate phone conversations from chat with top call controls and durable summaries |
| 2026-11-05 | [`5bd374e`](https://github.com/perry112926-ai/xiaorui/commit/5bd374e) | Keep texting available during calls and attach progress to individual replies |
| 2026-11-05 | [`1855c1b`](https://github.com/perry112926-ai/xiaorui/commit/1855c1b) | Integrate query-only Amap REST tools for places routes geocoding and weather |
| 2026-11-05 | [`5ae5bba`](https://github.com/perry112926-ai/xiaorui/commit/5ae5bba) | fix: align product promises with supported dining and runtime capabilities |
| 2026-11-05 | [`5e475b6`](https://github.com/perry112926-ai/xiaorui/commit/5e475b6) | Test elderly interaction scenarios and fix duplicate sends and phone navigation |
| 2026-11-05 | [`a0f61da`](https://github.com/perry112926-ai/xiaorui/commit/a0f61da) | Record successful live Amap queries and agent weather acceptance |
| 2026-11-05 | [`2216add`](https://github.com/perry112926-ai/xiaorui/commit/2216add) | Rewrite README around current features setup and verified service boundaries |

后续更新请在对应真实提交进入主线后补充；正式发版另记录tag、兼容变化、配置／数据迁移与回退方式。不要根据演示次数或文档标题追认未发布的版本。
