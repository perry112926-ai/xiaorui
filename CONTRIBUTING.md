# 小瑞开发说明

## 本地开发

环境、凭据和启动命令见[部署与配置](docs/setup.md)。模块与对应测试见[开发地图](docs/development.md)，消息、语音和确认流程见[系统架构](ARCHITECTURE.md)。

后端使用 Python 3.12 和 `uv.lock`，前端通过 `npm --prefix frontend ci` 安装锁定依赖。前端修改后运行生产构建并同步仓库中的 `frontend/dist/`。

## 验证与提交

```sh
uv run --no-sync python -m unittest discover -s tests -q
node --test frontend/tests/*.test.cjs
npm --prefix frontend run build
git diff --check
```

功能修改运行相关测试并验证实际流程。文档修改检查链接、格式和命令。真实写入、付款、取消及其他对外操作需要具体授权。实验脚本按各自说明运行，公开报告使用虚构资料或公开地标。[验证与复现](docs/acceptance.md) · [项目协作规则](AGENTS.md)

问题反馈请附系统和浏览器、复现步骤、实际结果及去敏错误。凭据、本机资料、通话内容、订单号和支付链接保存在私有环境。

第三方依赖的许可随相应依赖提供。项目源码、插画或其他素材的复用与分发请先向对应权利人确认授权。
