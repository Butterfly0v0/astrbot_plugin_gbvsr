# astrbot_plugin_gbvsr

AstrBot 插件：查询 [puddle.farm](https://puddle.farm/gbvsr/) 上的 GBVSR 玩家段位，并回复一张带立绘和网站天空背景的资料卡。

指令都以 `gbvsr` 开头，不会占用「查询」「帮助」「绑定」或 `TOP8`。

## 安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/Butterfly0v0/astrbot_plugin_gbvsr.git
```

重载插件。依赖见 `requirements.txt`（`aiohttp`、`pillow`）。

## 用法

群聊里需要 @ 机器人。

| 指令 | 说明 |
|------|------|
| `gbvsr <玩家名或ID>` | 查询玩家 |
| `gbvsr <玩家名或ID> <角色名>` | 查询该玩家的指定角色 |
| `gbvsr` | 查询已绑定的玩家 |
| `gbvsr绑定 <玩家名或ID>` | 绑定玩家 |
| `gbvsr解绑` | 解除绑定 |
| `gbvsr帮助` | 查看说明 |

角色名可以用简中、常见别称或英文，例如 `伊德`、`希斯`、`Id`。段位显示为大师、白银大师、黄金大师、宗师；S++ 及以下仍按网站原文显示。

## 配置

| 配置项 | 说明 |
|--------|------|
| `request_timeout_sec` | 访问 puddle.farm 的超时，默认 20 秒 |
| `cache_sec` | 同一玩家的缓存时间，默认 60 秒 |
| `cooldown_sec` | 每个用户的查询间隔，默认 5 秒。帮助和解绑不受限 |
| `max_results` | 重名时最多列出几位玩家，默认 5 |
