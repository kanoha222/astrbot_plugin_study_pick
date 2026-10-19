# 随机学习 v0.2.0（仅 HTTP 响应取数）

AstrBot `/学习` 插件。运行时不包含记录、图片占位 URL 或本地样例数据；标题、介绍所用元数据和图片链接全部来自配置页面的 HTTP 响应。

## 安装与配置

1. 使用交付的 v0.2.0 ZIP，或将插件文件放入 AstrBot 的 `data/plugins/astrbot_plugin_study_pick`。
2. 在 AstrBot 的 Python 环境安装 `requirements.txt` 并重载插件。
3. 在插件配置中填写必填的 `source_url`：管理员自有或有权使用的非露骨 HTML 数据页面的 HTTP(S) 地址。本项目不预填任何站点。
4. 发送 `/学习`；若 QQ 适配器要求 @ 或唤醒，沿用该适配器配置。

未填写地址会返回“请先在插件配置中填写 source_url”，不会返回测试记录。旧版遗留的 `source_mode=fixture` 会被忽略，不必手动删除旧配置后才可使用 HTTP。

目标版本为 AstrBot v4.28.0，使用通用 Star / AstrMessageEvent / plain_result 接口，不绑定具体 QQ 适配器。尚未进行真实 AstrBot 运行时加载或 QQ 实机测试。

## 每次命令的数据流

`source_url → GET → HTML → script#lucky-data → JSON.videos → 本地筛选 → 随机选择 → 标题、介绍、图片文本链接`

- 默认 `cache_ttl_seconds=0`，每次命令重新请求页面；可配置 1—3600 秒，仅缓存曾成功获取的响应记录。
- 没有内置数据、占位图或本地数据回退。请求、解析或筛选失败均明确报错；缓存刷新失败时也不返回过期缓存。
- `scope`、`year` 由插件配置控制，在本地筛选，不从地址查询参数自动推导，也不自动添加查询参数。
- 同会话可避免连续重复；只有一条候选时允许重复。历史最多 512 个会话，重载清空。
- 只返回图片文本链接，不下载或发送图片组件。

## 请求与响应约定

- 发送 GET，无请求体。显式头为 `User-Agent: Mozilla/5.0`、`Accept: text/html`。
- 不发送 Cookie，不执行 JavaScript，不上报统计，不跟随重定向。自动添加的常规 Host、压缩协商等由 aiohttp 处理。
- 响应须为 HTTP 200，Content-Type 为 `text/html` 或 `application/xhtml+xml`；支持分块传输。
- 默认 HTTP 总超时 15 秒，最大响应 3 MiB。403、重定向、非 HTML、超时、无效编码等返回失败。
- HTML 须包含唯一 `script#lucky-data`，内容为 JSON 对象，`videos` 为对象或数组。
- 每条有效记录需有非空 `title` 和绝对 HTTP(S) `coverUrl`；图片链接不允许内嵌账号密码。
- 其余读取字段为 `videoId`、`code`、`scope`、`year`、`releaseDate`、`durationMinutes`、`score`、`categories`、可选 `description`。
- `videoId` 缺失时回退为对象键/数组下标；重复 ID 保留第一条有效记录。
- 未提供 `description` 时，“介绍”由响应中的编号、日期、时长、评分、标签拼接，不编造内容简介。
- `years`、`pools`、`initialVideo` 可保留，但抽取不依赖它们；`actorLinks` 与未知字段不输出、不访问。

## 配置

| 配置 | 默认值 | 含义 |
|---|---|---|
| source_url | 空，必填 | HTML 数据页面地址；只接受不含账号密码的 HTTP(S) 地址 |
| scope | all | all 或与响应记录 scope 精确匹配的分类 |
| year | 0 | 0 表示全部，或具体年份 |
| avoid_repeat | true | 同会话避免连续重复 |
| timeout_seconds | 15 | 总超时 1—60 秒 |
| cache_ttl_seconds | 0 | 0—3600 秒；默认每次请求 |

不要配置含凭证/令牌的 URL；数据源设置仅管理员可改。若数据服务器位于另一台机器或容器，应使用 AstrBot 所在运行环境可达的地址。

## 开发与验证

仓库中的 tests 为独立自动测试，含中性测试夹具和 loopback HTTP 服务器；它们不会被插件运行时读取，也不包含在 v0.2.0 安装 ZIP 中。

完整源码下运行：

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

HTTP 端到端测试实际走本机 GET，再验证消息内容随响应变更，不访问外部内容站点。自动测试不等于 QQ 实机通过。

## 仓库与许可证

本项目独立编写，MIT 许可证，没有复制参考插件的 AGPL-3.0 代码。
公开仓库为 https://github.com/kanoha222/astrbot_plugin_study_pick 。可从仓库或交付的 v0.2.0 ZIP 安装；安装后仍须配置 source_url。自动测试不代表 QQ 实机测试已完成。

官方接口依据：
- https://github.com/AstrBotDevs/AstrBot/blob/v4.28.0/astrbot/core/star/base.py
- https://github.com/AstrBotDevs/AstrBot/blob/v4.28.0/astrbot/core/platform/astr_message_event.py
- https://github.com/AstrBotDevs/AstrBot/blob/v4.28.0/docs/zh/dev/star/guides/plugin-config.md
