# 飞猪 AI 机票接入

小瑞可调用 `fliggy_search_flights` 查询实时航班，比较搜索报价，并给出官方预订链接。用户需在飞猪核对乘机人、总价、税费、行李和退改规则后付款。本接入不自动创建订单、支付或出票，也不能核验链接打开后的订单状态。

## 配置

1. 准备 Node.js 18 或以上版本。
2. 在本机 `.env` 中配置 `FLYAI_API_KEY`，不要在对话中发送密钥。
3. 下载并展开官方 CLI 1.0.16 到被忽略的本机目录：

```sh
mkdir -p .local-data/flyai/cli
curl -fL https://registry.npmjs.org/@fly-ai/flyai-cli/-/flyai-cli-1.0.16.tgz -o /tmp/flyai-cli-1.0.16.tgz
tar -xzf /tmp/flyai-cli-1.0.16.tgz --strip-components=1 -C .local-data/flyai/cli
```

后端使用官方 CLI 的签名协议，密钥只放在子进程环境中。仅允许固定的 `search-flight` 子命令与受验证参数，不接受模型提供的命令、服务地址或任意工具名。CLI 保留自身的设备标识行为；文档与协议以官方版本为准。

重启服务后可说：“查一下11月13日北京到上海的直飞机票，1000元以内。”缺少日期或城市时应先补充信息。搜索报价随库存变化，不能当成含税成交价。

## 验证

```sh
.venv/bin/python -m unittest tests.test_fliggy
```

2026-11-06：使用用户提供的凭据，通过官方 CLI 和小瑞适配器验证北京至上海示例航班搜索；返回航班、报价与 `router.feizhu.com` 预订链接。直接请求 MCP 返回 401，官方签名 CLI 请求成功。未创建订单、付款或出票；预订链接后的结算流程未验收。

官方资料：[开放能力](https://flyai.open.fliggy.com/docs)、[FlyAI 官方仓库](https://github.com/alibaba-flyai/flyai-skill)。
