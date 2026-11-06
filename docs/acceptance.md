# 验证与复现

## 本机检查

在已安装依赖的仓库中运行：

```sh
uv run --no-sync python -m unittest discover -s tests -q
node --test frontend/tests/*.test.cjs
npm --prefix frontend run build
```

启动后查看 `http://127.0.0.1:8000/api/health`，再在网页发送一条文字。点击「我的资料卡」检查填写、保存和刷新。配置语音后拨打电话，在通话中发送一条文字，挂断后刷新并核对通话时长记录。

## 已记录的服务验证

| 场景 | 验证记录 |
| --- | --- |
| 高德 | 公开地标的地点、路线和天气查询。[接口结果](acceptance/amap-elderly-2026-11-05.json) |
| 麦当劳、瑞幸、滴滴 | 真实服务查询、候选、方案与重新核价。[接口结果](acceptance/services-live-2026-11-05.json) |
| 麦当劳餐品卡片 | 真实菜单及核价数据、选择与确认路径。[卡片验证](acceptance/mcd-food-cards-2026-11-05.json) |
| 飞猪 | 家人设置、连接检查、公开航班与预订链接。[验证记录](acceptance/fliggy-family-2026-11-06.json) |
| 文字与语音 | 消息接收、事件流、模型输出和渐进播报。[文字记录](acceptance/text-delivery-live-2026-11-05.json) · [语音记录](acceptance/voice-latency-live-2026-11-05.json) |
| 资料与记忆 | 持久化、偏好纠正、忘记和跨会话召回。[评估结果](evaluations/personal-agent-2026-11-06/results.md) |

接口结果是记录日期的快照。演示查询可使用公开地标。对实际订单、叫车、取消或新增配送地址，按展示的具体方案单独核对并确认。
