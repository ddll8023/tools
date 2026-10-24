# Stirling-PDF

返回 [开源项目参考](README.md)。本文是外部项目的参考记录，不是本项目的模块文档。

## 基本信息

| 项 | 值 |
| --- | --- |
| 仓库 | `Stirling-Tools/Stirling-PDF` |
| 官网 | https://stirling.com |
| 文档 | https://docs.stirlingpdf.com |
| 定位 | 以 PDF 为中心的开源 PDF 平台：桌面客户端、浏览器 UI、自托管服务 + REST API |
| 主语言（GitHub 统计） | TypeScript |
| 默认分支 | `main` |
| 最新 Release | `v3.2.2`（2026-10-24 发布） |
| Star / Fork | 94,869 / 11,211 |
| 未关闭 Issue | 543 |
| 桌面形态 | Tauri（V2 起），Windows / macOS / Linux |
| 发布产物 | dmg、AppImage、deb、rpm、msi、setup.exe、`Stirling-PDF.jar`、`Stirling-PDF-server.jar`、`Stirling-PDF-with-login.jar` |

以上数值核实于 2026-10-24（GitHub REST API），仅为快照。

## 许可证

根目录 `LICENSE` 为 MIT（Copyright (c) 2025 Stirling PDF Inc.），但以下目录各自有独立 `LICENSE`，不受根 MIT 覆盖：

`app/proprietary/`、`app/saas/`、`engine/`、`frontend/src/editor/proprietary/`、`frontend/src/editor/desktop/`、`frontend/src/editor/saas/`、`frontend/src/editor/cloud/`、`frontend/src/processor/`

GitHub API 的 `license` 字段显示为 `NOASSERTION`，与根 `LICENSE` 的 MIT 不一致，原因是这些子目录的独立许可无法被统一识别。实际引用代码时必须按具体目录判断，不能只看根 `LICENSE`。

上述八个目录的 `LICENSE` 已逐份核实（2026-10-24），内容完全一致，均为 **Stirling PDF User License**（专有许可，非开源），要点：

| 条款 | 内容 |
| --- | --- |
| 生产使用 | 仅在有有效 Stirling PDF User License 订阅时允许；未经订阅不得用于生产、规模化或关键业务 |
| 试用与最小使用 | 可免订阅用于内部试用、评估或最小使用，但不得复制、分发、再许可、逆向工程，不得用于面向客户或商业场景 |
| 修改与衍生 | 仅可为开发或内部测试而修改；衍生作品不得部署到生产、不得分发或再许可，知识产权仍归 Stirling PDF |
| 禁止行为 | 未获付费许可时：不得用于生产、不得复制/合并/分发/再许可/销售、不得移除或改动许可与版权声明、不得绕过访问或授权限制 |
| 第三方组件 | 其中包含的第三方开源组件仍按其原始许可执行 |

结论：仓库是 MIT 与专有许可的混合体，PDF 处理主链路（`engine/`）与编辑器核心（`frontend/src/editor/*`）属于专有许可范围，**不能当作开源代码复用**。可复用的只有这些目录之外的 MIT 部分。

## 技术栈

| 层 | 组成 |
| --- | --- |
| 服务端 | Java / Spring Boot；PDFBox（核心读写）、JPDFium（合并/拆分/文本表格）、Tabula（表格提取）、qpdf + Ghostscript（压缩优化）、OCRmyPDF + Tesseract（OCR）、Calibre（电子书转换）、ImageMagick + OpenCV（图像处理）、WeasyPrint（HTML 转 PDF）、LibreOffice（Office 转换） |
| AI 引擎 | Python：FastAPI + Pydantic AI |
| Web 应用 | React + TypeScript + Vite；EmbedPDF / PDF.js（查看与标注）、pdf-lib（Cantoo fork，浏览器内编辑）、Mantine（组件库）、i18next（40+ 语言） |
| 桌面 | Tauri，打包 Java 后端 |

## 能力清单

官方工具页按工具选择器分组，约 50+ 项：

| 分组 | 能力 |
| --- | --- |
| 快捷区 | PDF 文本编辑器、页面编辑器（PDF Multi Tool）、合并、对比、压缩、转换、OCR / 清理扫描件、打码 |
| 签名 | 证书签名、RFC 3161 时间戳、手写/打字/图片签名 |
| 文档安全 | 加密码、加水印、加图章、脱敏清理（Sanitize）、扁平化、解锁表单、改权限 |
| 校验 | 查看完整 PDF 信息（版本/字体/页面尺寸/权限/元数据）、验证数字签名 |
| 文档审阅 | 阅读与批注、改元数据、编辑书签目录 |
| 页面排版 | 裁剪、旋转、自动纠偏旋转、拆分、重排页面、改页面尺寸/缩放、加页码、多页合一、小册子拼版、合并为单长页、管理附件、创建 PDF 作品集 |
| 提取 | 提取页面、提取图片 |
| 移除 | 删除页面、删空白页、删标注、删图片、移除密码、移除证书签名 |
| 自动化 | 表单自动识别、无代码流水线（Automate）、按标题自动重命名 |
| 通用编辑 | 添加文本、添加图片、标注、表单编辑器 |
| 高级格式 | 调整颜色/对比度、修复损坏 PDF、检测并切分扫描照片、PDF 叠加、颜色替换与反相 |
| 开发者 | 显示 PDF 内 JavaScript、REST API、文件夹自动扫描、SSO、气隙部署 |
| AI | AI 助手（不在工具列表中，通过工作区按钮打开） |

转换矩阵（Convert 工具）：

- 转 PDF：Office（DOCX/DOC/ODT/XLSX/XLS/ODS/PPTX/PPT/ODP/TXT/RTF）、图片（JPG/JPEG/PNG/GIF/BMP/TIFF/WEBP/SVG）、Web 与文本（HTML、Markdown）、邮件（EML/MSG）、电子书（EPUB/MOBI/AZW3/FB2）、漫画（CBZ/CBR）
- 从 PDF 转出：Office（DOCX/ODT/PPTX/ODP/XLSX/CSV）、文本（TXT/RTF/Markdown）、图片（PNG/JPG/GIF/TIFF/BMP/WEBP）、Web（HTML/XML）、标准（PDF/A、PDF/X、PDF/UA）、电子书与漫画（EPUB/AZW3/CBZ/CBR）

## 与本项目的对照

本项目当前 12 个工具（见 [工具目录](../modules/tool-catalog.md)）与 Stirling-PDF 的对照结果：实质重合 4 项、部分重合 3 项、无对应 5 项。

### 实质重合（同一功能）

| 本项目工具 | Stirling 对应 | 关键差异 |
| --- | --- | --- |
| PDF 转 Markdown | Convert：PDF → Markdown | 本项目有 PyMuPDF 标准 + MinerU 深度双引擎、进度轮询与左右对照预览；Stirling 为单次转换，无深度解析档位 |
| PDF 转 Word | Convert：PDF → DOCX | 本项目用 pdf2docx 并检测文字层、给出人工校对告警；Stirling 走 LibreOffice 链路，官方提示扫描件需先跑 OCR |
| Word 转 PDF | Convert：DOCX/DOC → PDF | 双方都依赖 LibreOffice；Stirling 覆盖 ODT/XLSX/PPTX/RTF/TXT 等更多格式 |
| Markdown 转 PDF | Convert：Markdown → PDF | 本项目在 Electron 隐藏窗口内前端渲染 + `printToPDF`，公式/SVG/中文可离线；Stirling 走服务端渲染 |

### 部分重合

| 本项目工具 | Stirling 对应 | 差异 |
| --- | --- | --- |
| EPUB 转 Markdown | Convert：EPUB → PDF | 目标格式不同；Stirling 用 Calibre，覆盖 MOBI/AZW3/FB2/CBZ/CBR，本项目只处理 EPUB 且输出 Markdown + 图片 ZIP |
| 图片格式转换 | Convert：图片 ↔ PDF | Stirling 只做图片进 PDF、PDF 出图片（可调 DPI/色彩），没有图片转图片；本项目做 PNG/JPEG/WebP/BMP/GIF/TIFF 互转、TIFF 多页与动图拆分 |
| 局域网投送 | Mobile Scanner（手机扫码上传） | 本项目是双向投送 + 隔离区确认，支持任意文件；Stirling 只做手机拍照上传进服务器并转 PDF |

### 无对应

| 本项目工具 | 说明 |
| --- | --- |
| Markdown 转 Word | Stirling 非 PDF 输入只能转成 PDF，无 Markdown → DOCX 路径 |
| 思维导图 | 无 |
| 证件照 | 无 |
| 文本/文件转二维码 | Stirling 的二维码仅作为手机配对入口，不对外提供生成能力 |
| 有线传输（MTP） | 无设备侧能力 |

### Stirling 有、本项目完全没有

| 类别 | 能力 |
| --- | --- |
| 页面操作 | 合并、拆分、重排/删除页面、旋转、自动纠偏、裁剪、改页面尺寸、加页码、多页合一、小册子拼版、单长页、提取页面、插入空白页 |
| 内容编辑 | PDF 文本编辑器、添加文本/图片/图章、标注批注、阅读器、改元数据、编辑书签 |
| 安全 | 加/移除密码、改权限、打码、证书签名、时间戳、电子签名、脱敏清理、扁平化、解锁表单、移除证书签名 |
| 识别与修复 | OCR（OCRmyPDF + Tesseract）、修复损坏 PDF、检测并切分扫描照片、提取/删除图片、去除标注、删空白页 |
| 格式与标准 | PDF/A、PDF/X、PDF/UA、PDF ↔ HTML/XML/Office 全套、PostScript/EPS/PCL/XPS（仅 API） |
| 自动化 | 无代码流水线、表单自动识别与填写、按标题自动重命名、文件夹扫描 |
| 平台能力 | 自托管服务 + REST API + MCP、SSO/审计、40+ 语言、Docker/桌面/K8s 多形态部署 |

### 桌面形态对比

| 维度 | 本项目 | Stirling-PDF |
| --- | --- | --- |
| 桌面外壳 | Electron + TypeScript 主进程 | Tauri（V2 起）+ 打包 Java 后端 |
| 前端 | Vue 3 + TS + Pinia + Tailwind | React + TS + Mantine + Tailwind + PDF.js |
| 后端 | Python FastAPI，全部 POST，无数据库 | Java / Spring Boot + PDFBox + LibreOffice + OCRmyPDF |
| 定位 | 本地离线工具集合，PDF 只是其中一部分 | 以 PDF 为中心的全平台产品，开源 + 商业版 |

重合的技术底座是 LibreOffice 与第三方 PDF 解析引擎；差异在于 Stirling 围绕 PDF 做深（页面、安全、OCR、编辑），本项目围绕「多格式互转 + 本地隐私」横向铺开。

## 可借鉴方向

借鉴仅指功能方向与产品形态，不参考其专有目录（`engine/`、`app/proprietary/`、`frontend/src/editor/*` 等，见「许可证」节）的实现代码；需要技术方案时改用下方依赖自身的开源项目文档（PyMuPDF、Ghostscript、OCRmyPDF 等）。

| 方向 | 可行性 | 说明 |
| --- | --- | --- |
| 页面操作类（合并、拆分、重排、旋转、加页码） | 高 | 现有 PyMuPDF 依赖即可实现，不需要新增外部组件，与本项目 PDF 工具链一致 |
| PDF 转图片 / 图片转 PDF | 高 | 现有 Pillow 与 PyMuPDF 可覆盖，与「图片格式转换」模块相邻，可复用任务目录与下载实现 |
| 提取图片 / 删除空白页 / 去标注 | 高 | 同上，属 PyMuPDF 能力范围内的轻量操作 |
| OCR | 中 | 需新增 OCRmyPDF + Tesseract 外部依赖与语言包，桌面端打包体积与安装流程成本明显；本项目已有 MinerU 深度解析，需先评估两者定位是否重叠 |
| PDF/A 转换 | 中 | 依赖 Ghostscript，需确认打包与许可成本 |
| 无代码流水线 | 低 | 需要任务编排、前后端状态机与产物传递设计，属独立产品级功能 |
| 表单填写、证书签名、打码 | 低 | 涉及交互式编辑 UI 与安全语义，与当前「单次转换」的模块形态差异大 |

## 信息来源

- 官方工具总览：https://docs.stirlingpdf.com/Tools/
- 转换能力：https://docs.stirlingpdf.com/Tools/Guides/Convert/
- OCR 能力：https://docs.stirlingpdf.com/Tools/Guides/OCR/
- 开源组件与技术栈：https://docs.stirlingpdf.com/Developers/Technologies/
- 仓库与许可证：https://github.com/Stirling-Tools/Stirling-PDF （`LICENSE`、根目录结构）
- 版本与仓库统计：GitHub REST API（`/repos/Stirling-Tools/Stirling-PDF`、`/releases/latest`），核实于 2026-10-24

本项目侧的事实依据：`docs/项目结构文档.md`、`docs/modules/`、`backend/src/toolbox_backend/modules/tool_catalog/service.py`。
