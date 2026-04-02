---
name: cc-feishu-send-file
version: 1.0.0
description: |
  当你需要把本地图片或文件发送给飞书用户时使用。
  调用方式: cc-feishu-bridge send <文件路径> --config <config.yaml路径>
  示例: cc-feishu-bridge send screenshot.png --config /project/.cc-feishu-bridge/config.yaml
  支持图片: png, jpg, jpeg, gif, webp, bmp
  支持文件: pdf, doc, docx, xls, xlsx, zip, txt, csv 等
  config.yaml 路径为当前项目 .cc-feishu-bridge/ 目录下的配置文件
---

## 使用场景

- 你生成了图片（图表、截图、设计稿），需要发给用户
- 你生成了文件（报告、文档），需要发给用户
- 用户要求你把某个文件发到飞书

## 使用方式

```bash
cc-feishu-bridge send /path/to/file.png --config /path/to/.cc-feishu-bridge/config.yaml
```

一次可以发送多个文件：

```bash
cc-feishu-bridge send file1.png file2.pdf --config /path/to/.cc-feishu-bridge/config.yaml
```

## 注意事项

- 使用绝对路径，不要用相对路径
- config.yaml 为当前项目 .cc-feishu-bridge/ 目录下的配置文件
- 飞书对文件大小有限制，单个文件不超过 30MB
