# 配置与运行详解

## 快速开始

### Mac 一键启动

下载或克隆仓库，双击根目录的 `启动.command`。先安装 uv（家人可运行 `brew install uv`）；首次启动需要联网准备 Python 3.12 和依赖，并创建本地 `.env`；随后打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。关闭启动窗口或按 `Control+C` 停止服务。

随仓库附带前端构建时，运行普通聊天无需安装 Node.js；飞猪机票查询另外需要 Node.js 18 或以上版本，家人设置提供安装与组件准备入口。服务凭据需由本人或家人配置，空配置不会生成模拟结果。干净设备的一键启动体验仍需进一步验收。

### 开发启动

需要 Python **3.12**、[uv](https://docs.astral.sh/uv/) 和 Node.js/npm：

```sh
git clone https://github.com/perry112926-ai/xiaorui.git
cd xiaorui

# 已有 .env 时保留原配置
[ -f .env ] || cp .env.example .env
uv sync --locked
npm --prefix frontend ci
npm --prefix frontend run build
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

默认只绑定本机，按单进程运行。修改前端后重新构建并刷新网页；修改后端代码或启动模式后重启服务。当前以 Mac 本地启动脚本交付，未提供 Docker 部署方案。

## 配置服务

所有凭据仅保存在本机 `.env`，不提交 GitHub。只需配置打算使用的服务；语音 Key 与文本模型 Key 不通用。

| 配置项 | 用途与获取入口 |
| --- | --- |
| `ARK_API_KEY`、`ARK_MODEL` | [火山方舟](https://console.volcengine.com/ark)文本模型 Key 与已开通的模型 ID／Endpoint ID |
| `ARK_BASE_URL` | 默认 `https://ark.cn-beijing.volces.com/api/v3` |
| `ARK_CONTEXT_WINDOW_TOKENS` | 本地上下文预算，默认 `64000`，须不超过所选模型支持长度 |
| `DOUBAO_SPEECH_API_KEY` | [豆包语音](https://console.volcengine.com/speech/service)新版 API Key，分别开通流式识别 2.0 与语音合成 2.0 |
| `DOUBAO_ASR_RESOURCE_ID` | 默认 `volc.seedasr.sauc.duration` |
| `DOUBAO_TTS_RESOURCE_ID`、`DOUBAO_TTS_VOICE` | 默认 `seed-tts-2.0`、`zh_female_vv_uranus_bigtts` |
| `AMAP_KEY` | [高德控制台](https://console.amap.com/dev/key/app)创建 **Web服务** 类型 Key，填入 `.env`；不是 Web端 JS API 类型 |
| `MCD_MCP_TOKEN` | [麦当劳 MCP](https://open.mcd.cn/mcp)登录并激活 Token |
| `LUCKIN_MCP_TOKEN` | [瑞幸开放平台](https://open.lkcoffee.com/mcp)获取 Token |
| `DIDI_MCP_KEY` | [滴滴 MCP](https://mcp.didichuxing.com/)激活 Key |
| `FLYAI_API_KEY` | [飞猪 AI](https://flyai.open.fliggy.com/)获取 Key；在家人设置保存、准备组件并检查公开航班查询 |

点击顶部助手头像／名字进入家人设置，可保存豆包、麦当劳、瑞幸、滴滴和飞猪 AI 凭据；已保存的密钥不会返回浏览器明文。**高德当前通过 `.env` 配置。** 缺少权限、Key 失效、接口限流或网络异常时如实报错，没有运行时 mock 回退。

飞猪完整准备流程见[飞猪配置](fliggy.md)。在家人设置的“飞猪 AI 机票”中，先保存 Key，再准备固定版本的官方组件，最后检查连接。检查只查询七天后北京至上海的公开航班，不创建订单或读取乘机人。保存配置不等于连通；组件缺失、网络异常与权限失败会分别提示。

## 交易与确认

仓库默认关闭真实交易，按平台独立控制：

```dotenv
MCD_ORDER_ENABLED=false
LUCKIN_ORDER_ENABLED=false
DIDI_ORDER_ENABLED=false
```

本人或家人明确开启所需服务后重启，例如设置 `DIDI_ORDER_ENABLED=true`。启动命令中的同名环境变量优先于 `.env`，不能仍覆盖成 `false`。开启开关不等于立即下单，也不代表已经付款。

执行流程为：**真实查询 → 核对具体方案 → 明确二次确认 → 再次核价／检查条件 → 宿主执行 → 查询实际结果。**

- 方案包含门店／实际接送点、餐品规格／车型、数量、地址和金额；通过当前卡片或“确认下单”“确认叫车”“确认取消”“确认新增地址”继续。
- “好的”、旧方案、模型生成的确认文字不能授权交易。更改内容后，旧确认失效；费用或实质内容变化需重新确认，超预算停止。
- 取消待确认方案只放弃本地方案，**不会取消已创建的真实订单**。滴滴订单卡片的“查看取消条件”只查询；费用未知或接口限流时，应到官方进行中订单及时办理。
- 写入超时或结果未知时先核查，不通过重复创建订单确认结果。付款、已取消和退款到账均以官方实际状态为准。
- 模型只能提案；写操作由宿主确认网关执行，不开放任意 MCP、Shell 或文件工具。

演示时可强制只读：

```sh
XIAORUI_READ_ONLY=1 uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

只读模式允许当前白名单中的麦当劳、高德和飞猪航班查询，禁止交易、地址新增及配置修改；恢复普通模式需移除此环境变量并重启。

## 试着对小瑞说

- **聊天与偏好**：“陪我聊聊天。”“请记住，我更喜欢热饮。”
- **路线**：“帮我查北京西站到国家博物馆怎么走。”核对起终点后，选择步行、驾车或公交地铁；公交可优先少走路或少换乘。
- **天气**：“北京现在天气怎么样？”回复会附高德官方报告时间。
- **机票**：“查一下11月13日北京到上海的直飞机票，1000元以内。”小瑞展示航班卡片和预订链接；请在飞猪核对乘机人、总价、行李和退改规则后确认付款。没有自动支付、出票或票务订单状态查询。
- **点餐**：“帮我点麦当劳送到家，35 元以内。”核对地址、门店、餐品、餐具及含费总额后再确认。
- **叫车**：“帮我打车回家。”先取得有效定位或上车地标，读取已确认的家庭地址，核对实际接送点和车型后再确认。

首次使用先由家人在“我的资料卡”核对家庭地址及联系人。重要资料不能被聊天自动覆盖；临时预算不自动变成永久偏好。浏览器定位与麦克风需要本人授权，内嵌浏览器受限时可在 Safari／Chrome 打开本地网页。

## 实现与数据

后端采用 **Python 3.12、FastAPI、固定版本 nanobot 0.4.0、官方 MCP Python SDK、httpx 和 SQLite**；前端采用 **React、TypeScript 和 Vite**。豆包负责模型推理、流式语音识别与合成，高德使用固定官方 REST 端点，麦当劳、瑞幸和滴滴使用官方 MCP；飞猪航班使用官方 FlyAI 签名 CLI 1.0.16。

Agent 运行时、个人资料、会话候选与交易台账分别管理。重要个人资料经过人工确认；交易台账绑定会话所有者、版本、有效期及确认凭据，防止重复提交。凭据与运行数据位于 `.env`、`.local-data/` 等本地忽略路径。

**本地部署不等于离线运行。** 文本、语音及外部查询会向相应服务发送完成任务所需的数据。当前面向可信本机的单用户使用，未实现公网多用户服务。

## 已验证与未完成

当前证据包括高德地点、路线与天气真实查询及多场景模型对话、三家 MCP 的真实查询与核价、麦当劳真实待支付订单及官方支付入口，以及本机滴滴真实发单后取得的司机接单状态。这些是分项证据，不代表所有场景已经端到端完成。

仍待完成：完整真人语音交易与配送到家验收、稳定的取消和退款流程、持续实时导航、后台主动通知、苹果提醒事项真实接入及干净环境部署验收。基础调度生命周期已接入，但没有可承诺按时触达的用户提醒功能；主动陪伴、内容分享与抖音推荐属于规划。

```sh
# 后端自动化测试
uv run python -m unittest discover -s tests -q

# 前端行为测试与构建
npm --prefix frontend ci
node --test frontend/tests/*.test.cjs
npm --prefix frontend run build

# 高德公开地标真实只读查询，需 AMAP_KEY
uv run python -m experiments.amap_probe
```

离线测试中的测试桩只用于程序验证，不进入生产服务。测试通过不能代替真实接口、真人语音或交易验收；真实交易测试必须确认具体方案，不能为演示擅自发单。

## 项目说明与文档

原始任务：

> 实现一套可本地部署的 Personal Agent 服务。语言、模型、调度框架、Skill 全部自选；核心要求是尽可能对接真实外部 API（如高德、麦当劳等），而非 mock 接口，最终交付可一键本地跑起来的版本，附带设计说明，以 GitHub 链接的形式给出

| 文档 | 内容 |
| --- | --- |
| [架构设计](../ARCHITECTURE.md) | 模块分工、数据流和执行边界 |
| [原始任务](original-task.md) | 面试任务原文 |
| [产品理念](product-identity.md) | 用户、定位与长期方向 |
| [路线图](roadmap.md) | 阶段目标与缺口 |
| [服务边界](services.md) | 生活服务及飞猪机票的实现与限制 |
| [高德接入](amap.md) | Key 配置、工具和真实联调记录 |
| [老人高德场景验收](acceptance/amap-elderly-scenarios.md) | 出行、周边、天气、能力边界与修复复测 |
| [定位说明](location.md) | 权限、坐标、精度与有效期 |
| [电话交互](phone-interaction.md) | 通话、聊天与卡片如何协作 |
| [验收清单](acceptance.md) | 验收标准、证据与复现 |

项目使用并保留依赖各自的开源许可证；引用上游代码时保留许可与版权。项目不代表高德、麦当劳、瑞幸、滴滴或其他平台的官方产品。
