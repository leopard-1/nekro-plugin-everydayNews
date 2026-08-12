# nekro-plugin-everydayNews 每日新闻推送插件
该项目思路借鉴于 [EverydayNews V2](https://github.com/RavelloH/EverydayNews?tab=readme-ov-file)
### 概述
Nekro-plugin-everydayNews是可以通过GET请求来获取新闻内容的插件

### 功能：
- 获取最新的当日新闻
- 根据关键词搜索新闻
- 搜索指定日期的新闻
- 向指定群聊定时发送新闻
- 以图片形式发送新闻（待实现）

### 配置项：
- EverydayNews API 地址：默认且建议选为https://news.ravelloh.top  ，可另选为https://ravelloh.github.io/EverydayNews (国内访问可能不佳)
- 关键词搜索天数：关键词搜索时，从最新日期向前扫描的天数 默认30d
- 关键词搜索结果数：关键词搜索最多返回多少条新闻
- 请求超时秒数：访问 EverydayNews API 的超时时间，如果频繁超时请检查连通性或加长超时时间
- 显示来源链接：开启后在文本末尾显示 EverydayNews 来源地址，如不需要可手动关闭
- 启用每日定时推送：启用后定时推送配置才会生效
- 每日推送时间：每日推送新闻的时间，格式为HH:MM，如17:00,8:00
- 每日推送时区：用于读取系统当前日期和计算每日推送时间的 IANA 时区，例如 Asia/Shanghai
- 每日推送目标群聊：用于指定推送的目标群聊，例如 onebot_v11-group_123456789（可到频道管理查看，group为群聊，private为私聊）

### 指令
/daily_news_sync_schedule 会显示“下次推送触发时间”
/daily_news_push_now 可立刻推送一次新闻（测试定时推送用）

----------------------------------------------------------------
该项目遵循 MIT许可证
