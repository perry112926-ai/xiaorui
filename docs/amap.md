# 高德地图接入

使用官方 REST API，无额外 SDK。当前六个 `amap_` 工具支持本轮授权定位逆地理编码、地点搜索、地理编码、周边距离搜索、步行／驾车／公交地铁路线及实时天气／未来几天预报。服务地址固定为 `https://restapi.amap.com`，不接受模型传任意 URL，失败不使用 mock 回退。该能力没有创建订单或支付权限。

在[高德控制台](https://console.amap.com/dev/key/app)创建应用，添加「Web服务」类型 Key，填入项目 `.env` 的 `AMAP_KEY=`。不要使用 JS API 类型 Key，不要提交或在聊天发送 Key。Key 仅后端读取并对 HTTP 日志脱敏。官方服务的额度和权限以控制台为准；服务拒绝时不声称查询成功。

示例：说“查一下北京西站到国贸怎么走”，小瑞搜索起终点，请用户确认候选后查询路线。地点可用 `amap_geocode` 解析明确地址；路线只使用当前会话查到的高德坐标。返回米、秒、最多三条路线与关键道路指引，以及官方地图路线链接。公交默认优先少走路，可选少换乘；使用实际返回的线路与站点，途经站数加一为乘坐站数。文字搜索可能模糊匹配，附近查询使用真实中心点和直线距离；不能将直线距离当步行距离。不宣称实时跟随导航、偏航重算或滴滴已叫车。地图路线链接不含 Key，但含所选地点，用户点击后会交给高德地图。

天气示例：“北京今天天气怎么样？”先取得城市 adcode，再读取官方天气与 reporttime。当前不使用 IP 定位，不猜用户位置，不把地理编码或测试地标记作家。

官方资料：[地点搜索](https://lbs.amap.com/api/webservice/guide/api/search)、[地理编码](https://lbs.amap.com/api/webservice/guide/api/georegeo)、[路线规划](https://lbs.amap.com/api/webservice/guide/api/newroute)、[天气](https://lbs.amap.com/api/webservice/guide/api/weatherinfo)。

验证覆盖公开地标搜索、地理编码、路线和天气。样本使用北京西站等公开地点。[验证记录](acceptance/amap-elderly-2026-11-05.json)
