# 思维导图

模块标识：`mindmap`。返回 [项目结构](../项目结构文档.md)。

## 职责与入口

负责把 Markdown 大纲转成可编辑的本地思维导图，并支持导入 Markdown / XMind、导出 Markdown / XMind / SVG / PNG。整条能力完全在前端运行，不经过后端，也不写入除用户导出文件以外的磁盘位置。

内核位于 `frontend/src/features/mindmap/`，页面位于 `frontend/src/views/tools/MindMap.vue`，路由 `/tools/mindmap`。

不负责 Markdown 转 PDF/Word 的排版输出（见 [Markdown 转 PDF](markdown-to-pdf.md)、[Markdown 转 Word](markdown-to-word.md)）。

## 专属文件

### 页面

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `frontend/src/views/tools/MindMap.vue` | 导入校验（`.md`/`.markdown`/`.xmind`、10MB）、拖拽与选择、导出格式分发、PNG 倍率对话框、错误提示 |
| `frontend/tests/mindmap.spec.ts` | 公式预览回归用例 |

### 组件层

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `frontend/src/features/mindmap/components/MindMap.vue` | 工作区组合：`MindMapTextEditor` + `MindMapViewer`，对外暴露 `getData()` 等方法 |
| `frontend/src/features/mindmap/components/MindMapViewer.vue` | 维护布局、视口交互、历史快照、上下文菜单与导出状态（最大单文件） |
| `frontend/src/features/mindmap/components/MindMapCanvas.vue` | 渲染连线、节点与拖拽反馈 |
| `frontend/src/features/mindmap/components/MindMapNode.vue` | 单节点渲染 |
| `frontend/src/features/mindmap/components/MindMapTextEditor.vue` | Markdown 大纲编辑区 |
| `frontend/src/features/mindmap/components/MindMapContextMenu.vue` | 节点右键操作 |
| `frontend/src/features/mindmap/components/editor-utils.ts` | 编辑器光标与选区工具 |
| `frontend/src/features/mindmap/components/safe-svg.ts` | SVG 片段白名单处理 |
| `frontend/src/features/mindmap/components/index.ts` | 组件统一导出 |

### 内核层

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `frontend/src/features/mindmap/core/index.ts` | 内核唯一公开入口，重导出类型、解析、布局、操作与导出工具 |
| `frontend/src/features/mindmap/core/types.ts` | `MindMapData`、`LayoutNode`、`Edge`、`CrossLink`、`ThemeMode`、`ToolbarConfig` 等 |
| `frontend/src/features/mindmap/core/plugins/types.ts` | `MindMapPlugin`、`ParseContext`、`LayoutContext`、`ParsedLineResult` |
| `frontend/src/features/mindmap/core/plugins/runner.ts` | 按 `allPlugins` 顺序执行解析插件 |
| `frontend/src/features/mindmap/core/plugins/index.ts` | `allPlugins` 与七个插件的统一导出 |
| `frontend/src/features/mindmap/core/plugins/front-matter.ts` | YAML front matter 解析 |
| `frontend/src/features/mindmap/core/plugins/dotted-line.ts` | 虚线关系标记 |
| `frontend/src/features/mindmap/core/plugins/folding.ts` | 节点折叠标记 |
| `frontend/src/features/mindmap/core/plugins/multi-line.ts` | 多行节点文本 |
| `frontend/src/features/mindmap/core/plugins/tags.ts` | `#标签` 解析 |
| `frontend/src/features/mindmap/core/plugins/cross-link.ts` | 跨节点引用 |
| `frontend/src/features/mindmap/core/plugins/latex.ts` | LaTeX 公式标记 |
| `frontend/src/features/mindmap/core/utils/markdown.ts` | `parseMarkdownList`、`parseMarkdownMultiRoot`、`parseMarkdownWithFrontMatter`、`toMarkdownList`、`toMarkdownMultiRoot` |
| `frontend/src/features/mindmap/core/utils/xmind.ts` | `parseXMindFile`、`exportMindMapToXMind`、`XMindFormatError` |
| `frontend/src/features/mindmap/core/utils/layout.ts` | `layoutMindMap`、`layoutMultiRoot`、`computeEdgePath` |
| `frontend/src/features/mindmap/core/utils/tree-ops.ts` | 增删改移节点、子树查找、ID 重生成、左右侧切换 |
| `frontend/src/features/mindmap/core/utils/history.ts` | 快照克隆、比较与入栈 |
| `frontend/src/features/mindmap/core/utils/export.ts` | `buildExportSVG`、`buildExportSVGForPNG`、`exportToPNG`、`exportPreparedPNG` |
| `frontend/src/features/mindmap/core/utils/inline-markdown.ts`、`frontend/src/features/mindmap/core/utils/content-layout.ts` | 行内 Markdown 解析与文本测量 |
| `frontend/src/features/mindmap/core/utils/theme.ts` | 主题、分支色、CSS 变量与导出样式 |
| `frontend/src/features/mindmap/core/utils/import.ts`、`frontend/src/features/mindmap/core/utils/input.ts` | 导入数据校验与初始输入解析 |
| `frontend/src/features/mindmap/core/utils/tag-filter.ts`、`frontend/src/features/mindmap/core/utils/highlight.ts`、`frontend/src/features/mindmap/core/utils/i18n.ts`、`frontend/src/features/mindmap/core/utils/formula.ts` | 标签过滤、文本高亮、文案、公式桥接 |
| `frontend/src/features/mindmap/styles/mindmap.css` | 导图样式 |

## 公共与跨模块引用

路径书写：`backend/`、`frontend/`、`electron/` 开头的为仓库根相对路径；本节省略前缀的后端路径默认在 `backend/src/toolbox_backend/` 下，省略前缀的前端路径默认在 `frontend/src/` 下。

| 所属模块／公共记录 | 文件与使用范围 | 本模块为何引用 |
| --- | --- | --- |
| [公共记录](shared.md) `frontend-shared-ui` | `components/common` 的 `BaseSelect`/`SelectOption` | 导出格式与 PNG 倍率选择 |
| [公共记录](shared.md) `frontend-shared-ui` | `utils/math/engine.ts` 的 `initFormulaEngine`、`requireFormula`（经 `core/utils/formula.ts` 再导出） | 公式节点渲染 |
| [公共记录](shared.md) `frontend-desktop-contract` | `frontend/src/types/tool.ts` | 仅用于工具配置类型，无运行时依赖 |
| [工具目录](tool-catalog.md) | `_TOOLS` 中 `mindmap` 条目 | 页面入口 |

本模块不调用 `api/client.ts` 或任何后端接口。

## 关键调用链

### 输入与解析

1. `MindMap.vue` 的 `openFile` 校验扩展名与 10MB 上限，`getImportSource` 区分 Markdown 与 XMind。
2. Markdown 路径调 `MindMap` 组件的导入方法；XMind 路径调 `parseXMindFile`（`core/utils/xmind.ts`）。
3. 内核解析：`parseMarkdownWithFrontMatter` 先取 front matter → `runner.ts` 依次执行 `allPlugins` → `parseMarkdownMultiRoot` 生成 `MindMapData[]`。
4. `normalizeData` 补齐字段与 ID，`layoutMultiRoot` 计算节点位置与连线。

### 编辑

1. `MindMapTextEditor` 文本变化 → 重新解析 → `layoutMultiRoot`。
2. 画布交互（拖拽、右键菜单）→ `tree-ops` 的 `moveNodeMulti`/`addChildMulti` 等 → 更新数据 → 重算布局。
3. 每次结构性变更前 `pushHistorySnapshot` 记录快照，撤销/重做由 `history.ts` 比较快照实现。

### 导出

1. `MindMap.vue` 选择格式后调用 `MindMapViewer` 暴露的导出方法。
2. Markdown：`toMarkdownMultiRoot`。
3. XMind：`exportMindMapToXMind` 生成 XMind 结构。
4. SVG：`buildExportSVG` 用 `generateExportStyles` 内联主题样式。
5. PNG：`openPngExportDialog` 选择 2x/3x/4x → `exportPreparedPNG`/`exportToPNG` 先 `buildExportSVGForPNG` 再栅格化并触发本地下载。

## 状态与数据所有者

| 状态／资源 | 所有者 | 副本或消费者 | 生命周期／持久化 |
| --- | --- | --- | --- |
| 导图数据 | `MindMapViewer.vue` 内部状态（经 `normalizeData` 规范化） | 画布、编辑器、导出 | 内存；不持久化，刷新即丢失 |
| 历史快照 | `core/utils/history.ts` 的栈 | `MindMapViewer` 撤销/重做 | 内存 |
| Markdown 源文本 | `MindMap.vue` 的 `markdown` | 编辑器与解析入口 | 内存，初始为 `DEFAULT_MARKDOWN` |
| 导出文件 | 用户下载 | — | 由浏览器下载机制写盘 |

## 生命周期与约束

- 导入只接受 `.md`、`.markdown`、`.xmind`，且不超过 10MB；空 Markdown 直接拒绝。
- 公式引擎与 PDF 工具共用 `utils/math/engine.ts`，本模块通过 `core/utils/formula.ts` 二次封装，不直接依赖路径。
- 导出 SVG 内联样式，PNG 由 SVG 栅格化生成，不依赖后端渲染。
- 内核通过 `core/index.ts` 统一导出，页面只从该入口引入，不深入 `core/utils/*`。

## 当前覆盖边界

- `MindMapViewer.vue` 超过 1300 行，同时承担布局、视口、历史与导出状态；本文按职责登记，不展开其内部函数级结构。
- XMind 格式兼容范围由 `core/utils/xmind.ts` 的解析实现决定，未覆盖所有第三方导出变体。
