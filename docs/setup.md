# 部署与配置：先跑通本机，再逐项启用服务

[返回首页](../README.md) · [文档导航](README.md) · [开发地图](development.md)

本文适用于当前React／FastAPI主线。默认可信本机、单用户、单进程；没有Docker、手机原生客户端或公网登录交付。Mac启动器存在，干净Mac仍需验收。不要将其他分支的Flutter或Linux启动脚本当成此版本入口。

## 环境与启动

| 场景 | 需要什么 |
|---|---|
| Mac使用仓库预构建页面 | Git或源码压缩包、联网环境、浏览器；预先安装 uv，启动器准备 Python 3.12 |
| 从源码开发 | Python3.12、uv、Node.js/npm；以`uv.lock`和`frontend/package-lock.json`为准 |
| 真实聊天／语音／服务 | 对应提供方已开通的凭据、权限与额度；不是ChatGPT登录即可通用 |

先安装 uv（例如 `brew install uv`），再在 Mac 双击根目录[`启动.command`](../启动.command)。首次准备依赖可能较慢，观察终端输出；它监听127.0.0.1:8000，打开本机浏览器，关闭前台终端或Control+C停止。已有`.env`不覆盖；已有`frontend/dist/index.html`时不会自动重建前端，修改网页源码后必须主动构建。

开发者在新目录执行：

```sh
git clone https://github.com/perry112926-ai/xiaorui.git
cd xiaorui
umask 077
[ -e .env ] || cp .env.example .env
chmod 600 .env
uv sync --locked --python 3.12
npm --prefix frontend ci
npm --prefix frontend run build
```

使用本机编辑器填写`.env`，不要输出文件全文、把Key放命令参数或上传聊天。随后前台启动：

```sh
env MCD_ORDER_ENABLED=false LUCKIN_ORDER_ENABLED=false DIDI_ORDER_ENABLED=false \
  uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开[http://127.0.0.1:8000](http://127.0.0.1:8000)。同一端口只跑一个服务。Mac可用`lsof -nP -iTCP:8000 -sTCP:LISTEN`检查占用；先识别进程，不盲杀其他应用。

上述三个订单开关禁用订单创建／取消路径，**不能禁止单独确认的麦当劳地址新增**。仅需只读演示时另启动以下模式；先停旧进程：

```sh
XIAORUI_READ_ONLY=1 uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000
```

该模式的允许集以[`app/read_only.py`](../app/read_only.py)为准，目前为部分麦当劳、高德及飞猪航班查询；记忆写入、资料修改、配置修改、地址和交易均拒绝，不是全部平台查询都开放。退出只读模式需移除该变量并重启。

## 配置按功能分开

值仅填写本机[`.env.example`](../.env.example)对应的`.env`，不要修改模板提交真实Key。只配置要用的服务，缺配置如实报错，不返回模拟数据。

| 字段 | 用途／默认 | 获取与核对 |
|---|---|---|
| `ARK_API_KEY` | 豆包文本模型Key | [火山方舟](https://console.volcengine.com/ark) |
| `ARK_MODEL` | 已开通模型ID或Endpoint ID，无通用默认值 | 按该账号控制台调用示例填写 |
| `ARK_BASE_URL` | `https://ark.cn-beijing.volces.com/api/v3` | 当前内置家人设置限制官方目标，不作为任意模型代理 |
| `ARK_CONTEXT_WINDOW_TOKENS` | `64000`上下文预算 | 不超过实际模型支持长度，非记忆条数 |
| `DOUBAO_SPEECH_API_KEY` | 豆包语音新版API Key | [语音控制台](https://console.volcengine.com/speech/service)，与文本Key不同 |
| `DOUBAO_ASR_RESOURCE_ID` | `volc.seedasr.sauc.duration` | 开通流式识别2.0 |
| `DOUBAO_TTS_RESOURCE_ID` | `seed-tts-2.0` | 开通语音合成2.0 |
| `DOUBAO_TTS_VOICE` | `zh_female_vv_uranus_bigtts` | 核对账号权限和实际音色 |
| `AMAP_KEY` | 高德Web服务Key | [高德控制台](https://console.amap.com/dev/key/app)，不是JS API Key |
| `MCD_MCP_TOKEN` | 麦当劳Token | [官方MCP](https://open.mcd.cn/mcp)登录激活 |
| `LUCKIN_MCP_TOKEN` | 瑞幸Token | [官方MCP](https://open.lkcoffee.com/mcp) |
| `DIDI_MCP_KEY` | 滴滴Key | [官方MCP](https://mcp.didichuxing.com/)，核实实际查询与发单权限 |
| `FLYAI_API_KEY` | 飞猪 AI 机票 Key | Node.js 18 或以上版本；在家人设置保存 Key、准备固定版本组件并检查公开航班查询，详见[飞猪配置](fliggy.md) |
| `LIFE_SERVICES_TRUST_ENV` | 默认`true`，沿用环境代理 | `false`仅让三家MCP直连，不改变模型／语音代理或自动重试交易 |
| `*_ORDER_ENABLED` | 三平台分别默认`false` | 只有明确审阅具体业务风险后才启用，每笔仍需确认 |

页面顶部头像／名字内的家人设置支持豆包、麦当劳、瑞幸、滴滴和飞猪；Key读取掩码化，空白保留、明确清除。高德当前只能编辑`.env`配置。系统环境变量优先于`.env`；特别检查启动命令中的覆盖值。配置变更后重启可确保全部启动期设置重新加载。

家人设置是界面用途，不是独立管理员认证。昵称头像只改变当前浏览器外观，不修改资料卡中的本人信息或Agent正式身份。

## 按层验收，不一次打开所有能力

1. **页面与状态**：访问`GET /api/health`，核对`ok`、只读模式和配置标记。字段只说明配置存在，不证明接口可用。
2. **文字**：配置Ark后问候一次，查看真实结果与错误。缺权限／额度时先修配置。
3. **记忆**：资料卡保存后刷新读取；普通偏好明确保存、修改、忘记；重启再查，详见[记忆验收](memory.md#如何复现已有保证)。
4. **一个真实查询**：使用公开地标或指定城市查询。保留来源和时间，不将测试地点存为家。飞猪可用设置页的“检查连接”查询公开航班，预订由用户在飞猪完成。
5. **语音**：授权麦克风，短句、慢停顿、连续两轮、插话、取消、挂断和断网；分别记录真实出声及失败恢复。电话纯文本与重播入口目前有缺口，见[电话交互](phone-interaction.md)。
6. **交易**：最后单独验收，审阅具体地址、金额、内容和扣款风险；查询成功不能授权下单或取消。

现有自动化和真实接口证据见[acceptance](acceptance.md)。不要批量运行`experiments/`；部分脚本会调用付费或交易接口。

## 常见问题

| 现象 | 先检查什么 |
|---|---|
| 页面503或旧样式 | `frontend/dist/`是否存在；重新构建；是否启动了另一目录／旧进程 |
| 模型未接通 | `ARK_API_KEY`与`ARK_MODEL`各自存在，账号模型权限和额度；`SetLimitExceeded`不一定充值就能解除 |
| 语音未接通 | 语音Key、ASR／TTS资源各自权限；浏览器麦克风、AudioWorklet和播放限制 |
| 定位失败 | 明确授权与安全浏览器上下文；改用地标；不能猜当前位置或扩大监听绕过 |
| 配置不能保存 | 是否强制只读；有无错误类型；环境变量是否覆盖`.env` |
| 飞猪组件未就绪 | 检查 Node.js、Key 和组件状态；安装 Node.js 后重启小瑞，再准备组件并检查连接 |
| 查询超时 | 凭据权限、官方限流、网络与代理；不要以重发订单诊断网络 |
| 已停止但任务仍继续 | 停播／挂断关闭本地音频，不撤销已接收任务或真实订单；核查台账与官方状态 |
| 换浏览器找不到原聊天 | owner cookie变化；资料是单用户共享，但会话不会自动跨浏览器识别 |
| 手机打不开localhost | localhost是手机自己，不是Mac；当前没有安全远程HTTPS入口，不能靠0.0.0.0或通配CORS修复 |

## 数据备份与访问边界

本机私有数据包括`.env`、`.local-data/`下的资料、对话、图片、订单和调度记录。结构见[架构存储表](../ARCHITECTURE.md#4-资料会话任务与交易是不同的持久状态)。

- 先停服务，再做SQLite及相关文件的一致快照；保存代码commit和依赖锁，备份到用户控制的私有／加密位置。
- 启动器可能在`.local-data/`保存工具与Python缓存，整个目录可能较大；不把`.venv`、node_modules或旧机原生缓存当跨系统安装包。
- 恢复到隔离目录，先核对版本和数据兼容性，不覆盖运行中数据库。恢复历史订单记录不意味着可以重放操作。
- 当前未提供应用级数据库加密、完整数据删除／导出、用户角色或公网登录。忘记事实是召回隔离，非销毁所有记录。
- 默认保持127.0.0.1监听、精确Host／Origin与单进程。Tailscale、反向代理或内网可达不自动补足应用身份授权；远程部署必须另行设计与验收，不直接暴露设置页。

## 更新与回退

更新前检查`git status`，保留未完成改动、私有备份与当前commit。干净主线才使用`git pull --ff-only`；有分叉时先审查，不强推／reset。重新安装锁定依赖、构建、查看[CHANGELOG](../CHANGELOG.md)配置与存储变化，再重启。

失败时停服务，在独立目录／worktree检查已知良好commit，并核对数据库兼容性；不要删除私有数据“恢复默认”，不要为了回退重复创建、支付或取消订单。
