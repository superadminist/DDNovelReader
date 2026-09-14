# 最近阅读默认封面改版验收

## 对照基准

- 用户参考图：`C:\Users\ADMINI~1\AppData\Local\Temp\codex-clipboard-cf01e601-fa2b-4a83-a2f8-f000b14886ce.png`
- 问题区域：最近阅读卡片的默认 `DD` 方形占位图。
- 保留内容：最近阅读标题、书名、章节、进度、格式标签和继续按钮。

## 实现结果

- 新增 4 张 768 × 1024 的竖版封面：靛蓝、鼠尾草绿、暖橙、夜色。
- 封面采用统一的纸张纹理和文学插画风格，不包含字母、文字、Logo 或水印。
- 卡片改为 3:4 比例，保留原有圆角、悬浮按钮和进度信息。
- 后端根据书籍 ID 做稳定分配，同一本书重启后封面不变；不同书籍可使用不同封面。
- 四张素材压缩后总计约 626 KB。

## 视觉对比

- 实现页面：Codex 应用内浏览器 `http://127.0.0.1:4173/`。
- 检查尺寸：窄视口双列，以及 1280 × 720 CSS 视口。
- 检查结果：封面完整填充、无拉伸、无文字污染；两列和四列布局下均保持清晰，书名与进度区域未被挤压。
- 视觉变化：移除重复的大号 `DD`，改为可区分且统一的竖版书封；阴影减轻，圆角和现有浅色界面保持一致。

## 运行验证

- Python 单元测试：116 项通过。
- 前端契约测试：30 项通过。
- Vite 生产构建：通过。
- Qt Stage 4：源码版、快速启动版、单文件版均通过；测试使用隔离书库数据。
- 桌面运行截图输出：
  - `C:\Users\Administrator\AppData\Local\Temp\ddnr-cover-redesign-stage4`
  - `C:\Users\Administrator\AppData\Local\Temp\ddnr-cover-redesign-onedir-stage4`
  - `C:\Users\Administrator\AppData\Local\Temp\ddnr-cover-redesign-onefile-stage4`

## 验收历史

1. 发现真实书籍统一返回 `covers/library.png`，造成重复方形 DD 封面。
2. 生成并压缩 4 张竖版封面，改为基于书籍 ID 的稳定分配。
3. 浏览器视觉检查通过；桌面三种运行形态通过 Stage 4 验收。

final result: passed
