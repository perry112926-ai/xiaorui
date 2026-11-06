# 参与开发

欢迎通过可复现的问题、交互反馈、测试和小范围 PR 改进小瑞。当前优先级是让现有生活服务、记忆和语音行为可信、可核查、易恢复。

## 先了解项目的真实边界

- [README](README.md)：当前能力、运行方式和产品状态。
- [架构设计](ARCHITECTURE.md)：模块、数据流、存储和执行边界。
- [记忆架构](docs/memory.md)：明确资料、会话恢复和“忘记”的实际语义。
- [更新记录](CHANGELOG.md)：已进入主线的改进及独立实验分支。
- [验收清单](docs/acceptance.md)：自动化、真实服务和真人体验各自证明什么。
- [协作规则](AGENTS.md)：自动化检查及提交要求；用户当前任务的明确指令优先。

当前目标环境是可信本机、单用户、单进程。不要把本地 owner cookie 当成公网登录系统，或为了让手机能访问而开放任意 Host／Origin。

## 建立开发环境

需要 Git、Python **3.12**、[uv](https://docs.astral.sh/uv/) 和可运行当前 Vite／TypeScript 的 Node.js/npm。使用锁文件，不先升级依赖。

```sh
git clone https://github.com/perry112926-ai/xiaorui.git
cd xiaorui

git switch -c your-change
uv sync --locked --python 3.12
npm --prefix frontend ci

# 已有配置不覆盖；新配置仅在本机创建
if [ ! -e .env ]; then
  (umask 077; cp .env.example .env)
fi
chmod 600 .env
npm --prefix frontend run build
```

先运行禁交易的普通本机实例，支持配置和资料卡操作：

```sh
env MCD_ORDER_ENABLED=false LUCKIN_ORDER_ENABLED=false DIDI_ORDER_ENABLED=false \
  uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`；在启动终端按 `Control+C` 停止。三个订单开关不是“禁止所有外部写入”的总开关：新增麦当劳配送地址另有明确确认流程。需要禁止交易、地址新增及配置修改的演示时，额外设置 `XIAORUI_READ_ONLY=1` 并重启；只读允许集见 `app/read_only.py`，不是全部查询工具都开放。

没有凭据时，可以修改界面、检查错误状态和运行离线测试；不能把它记录成真实接口通过。不要共享 `.env`，也不要把现有用户的私有运行目录复制到新开发环境。

## 找到应改的模块

| 变更 | 首先阅读 |
|---|---|
| 页面、消息、卡片和通话导航 | `frontend/src/main.tsx`、`CallBar.tsx`、`ActionCard.tsx`、`ProfileCard.tsx` |
| 录音、停顿、插话和音频播放 | `frontend/src/useVoice.ts`、`app/voice.py`、`app/voice_protocol.py` |
| 模型与工具宿主 | `app/agent.py`、`app/nanobot_runtime.py`、`app/skills.py` |
| 个人资料与会话 | `app/foundation_store.py`、`app/profile_card.py`、`app/contact.py` |
| 高德查询 | `app/amap.py`、`skills/amap/SKILL.md` |
| 生活服务与交易 | `app/{mcd,luckin,didi}_scenario.py`、`app/actions.py`、`app/plans.py` |
| HTTP、安全边界与设置 | `app/main.py`、`app/settings.py`、`app/read_only.py` |
| 测试和真实实验 | `tests/`、`frontend/tests/`、`experiments/`；按各自用途运行 |

研究快照位于 `docs/research/`，它们保存当时的资料，**不是应用运行时目录**。不要用研究项目支持某功能的说明，代替核查小瑞是否实际启用该功能。

## 验证改动

先运行与变更直接相关的测试。功能修改还须验证实际流程；前端变更必须检查 TypeScript 与生产构建。需要完整离线回归时：

```sh
uv run --no-sync python -m unittest discover -s tests -q
node --test frontend/tests/*.test.cjs
npm --prefix frontend run build
git diff --check
```

纯文档修改检查差异、命令语法、链接和描述是否与源码一致即可；不为文档修改重复调用付费服务。

| 验证层 | 可以证明 | 不能替代 |
|---|---|---|
| 单元／交互测试 | 参数、状态、隔离、错误和去重行为 | 真实平台权限、设备和网络 |
| 生产构建 | 类型和打包可通过 | 实际页面可读性、手机触控 |
| 真实只读服务 | 该时刻、该凭据下查询可用 | 交易、付款和长期稳定性 |
| 真人／设备测试 | 对应设备、网络、语言的实际表现 | 所有老人、方言、场景 |
| 经授权的交易验收 | 已审阅具体方案的实际结果 | 无条件自动消费或可重复重放 |

`experiments/` 中有会调用付费模型、外部服务或提交交易的脚本。先读代码并明确该脚本的实际行为，不批量运行所有实验。真实下单、叫车、取消、支付或对外发送，必须由用户审阅并明确授权具体动作；不能把“帮我跑测试”理解为允许真实消费。

语音改动至少检查：权限拒绝、空录音、慢停顿、插话、停止播报、连续两轮、取消后迟到结果、断网和浏览器拒播。记录“真人说完到实际出声”，不要只量服务端首块，或用固定“嗯”当成有效回答。

记忆改动至少检查：重启读取、普通偏好增改删、重要字段不可由模型覆盖、忘记后的旧召回隔离，以及历史记录与有效资料的区别。交易改动至少检查：owner、方案版本、过期、重新核价、重复确认、未知结果及重启不重放。

## 提交一个便于审阅的 PR

1. 一个分支解决一个明确问题。先查看 `git status`，保留别人的未完成修改。
2. 在 PR 中写清触发条件、修改后的行为、验证命令及结果、仍未验证的边界。
3. 新功能同步更新 README／架构／服务说明中受影响的部分；已实现改动写入 CHANGELOG 的待发布区，带可追溯提交。
4. 前端改动运行构建，核对仓库已跟踪的 `frontend/dist/` 是否需同步；不要提交过时构建或无关产物。
5. 只暂存本任务文件，检查 `git diff --cached`。按当前任务指令和 `AGENTS.md` 决定提交／推送；用户明确要求只 staged 时不要 commit。不要强推、改写他人提交或自动合并 PR。

PR 示例：

> 电话自动播放被拒绝时，原提示指向隐藏的聊天消息。现在通话栏保留最近回复及“再说一遍”，用户可主动恢复播放。新增拒播与挂断后的迟到播放回归测试；类型检查和构建通过。未验证真实 iPhone 系统来电打断。

## 凭据、个人数据与问题反馈

`.env`、`.local-data/`、模型登录、会话数据库、完整电话转录、音频、家庭地址、手机号、订单号和支付链接不应出现在公开 Issue／PR。错误记录先脱敏；保存截图前检查屏幕中的私人内容。测试资料使用明确的虚构信息或公开地标，不能复用用户的真实住址来演示。

普通问题请提供：版本／提交、运行系统与浏览器、复现步骤、预期和实际结果、去敏错误、是否涉及外部服务。数据泄漏、确认绕过或可能重复消费的问题不要在公开 Issue 附上利用材料和凭据；先通过维护者已公开的私下联系方式报告。当前未指定安全响应邮箱或响应 SLA，不虚构联系方式。

## 许可与第三方资料

截至本说明基线，仓库根目录**尚未提供项目级 LICENSE，也未在项目元数据中声明许可**。不要把“源码公开”写成已经授予某种开源许可，不擅自添加 MIT／Apache／AGPL 标识。项目维护者需在正式采用开源许可证前确认源码、角色素材与第三方内容的授权；复用或分发前先确认项目许可。

依赖和 `docs/research/` 内的第三方资料保留各自许可证与版权；这些许可证不能替代小瑞自身的项目许可。提交来自其他项目的代码／素材时，说明来源和许可并保留要求的声明。不提交无法说明授权来源的内容。
