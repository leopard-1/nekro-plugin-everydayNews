# nekro-plugin-everydayNews 每日新闻推送插件
该项目思路借鉴于 [EverydayNews V2](https://github.com/RavelloH/EverydayNews?tab=readme-ov-file)
### 概述
Nekro-plugin-everydayNews是可以通过GET请求来获取新闻内容的插件

### 功能：
- 获取最新的当日新闻
- 根据关键词搜索新闻
- 搜索指定日期的新闻
- 以图片形式发送新闻（待实现）

### 配置项：
- EverydayNews API 地址：默认且建议选为https://news.ravelloh.top，可另选为https://ravelloh.github.io/EverydayNews(国内访问可能不佳)
- 关键词搜索天数：关键词搜索时，从最新日期向前扫描的天数 默认30d
- 关键词搜索结果数：关键词搜索最多返回多少条新闻
- 请求超时秒数：访问 EverydayNews API 的超时时间，如果频繁超时请检查连通性或加长超时时间
- 显示来源链接：开启后在文本末尾显示 EverydayNews 来源地址，如不需要可手动关闭

----------------------------------------------------------------
该项目遵循 MIT许可证
