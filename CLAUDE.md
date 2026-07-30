# 依赖下载问题记录

## Electron 运行时下载失败

### 现象

执行 Electron 启动命令时出现：

```text
Downloading Electron binary...
TypeError: fetch failed
Error: Electron failed to install correctly.
```

即使 `npm install` 成功，`node_modules/electron` 也可能只有 npm 包文件，缺少以下运行时文件：

```text
node_modules/electron/dist/
node_modules/electron/path.txt
```

此时执行 `npx electron --version` 可能临时下载 Electron，失败后使用 `~/.npm/_npx/...` 下的临时包，而不是项目本地包。

### 环境与版本

- 系统：macOS Apple Silicon
- 架构：`darwin arm64`
- Node.js：`v26.5.0`
- Electron：`43.2.0`
- 项目目录：`/Users/mima1234/Desktop/code/tools`

### 处理方式

1. 进入项目目录，跳过 npm 安装脚本安装 Electron 包：

```bash
cd /Users/mima1234/Desktop/code/tools
npm install --ignore-scripts electron@43.2.0
```

2. 下载 macOS Apple Silicon 对应的 Electron 运行时。优先使用 npmmirror：

```bash
curl -fL --retry 3 \
  -o /tmp/electron-v43.2.0-darwin-arm64.zip \
  https://npmmirror.com/mirrors/electron/43.2.0/electron-v43.2.0-darwin-arm64.zip
```

镜像失败时使用官方地址：

```bash
curl -fL --retry 3 \
  -o /tmp/electron-v43.2.0-darwin-arm64.zip \
  https://github.com/electron/electron/releases/download/v43.2.0/electron-v43.2.0-darwin-arm64.zip
```

3. 解压到本地 Electron 包，并写入可执行文件路径：

```bash
rm -rf node_modules/electron/dist
mkdir -p node_modules/electron/dist
unzip -q -o \
  /tmp/electron-v43.2.0-darwin-arm64.zip \
  -d node_modules/electron/dist
printf 'Electron.app/Contents/MacOS/Electron' > node_modules/electron/path.txt
```

4. 验证安装：

```bash
./node_modules/.bin/electron --version
```

预期输出：

```text
v43.2.0
```

验证通过后启动项目：

```bash
npm run dev
```

### 注意事项

- 当前 macOS Apple Silicon 必须下载 `darwin-arm64`，不要下载 `darwin-x64`。
- `ELECTRON_MIRROR` 是 Electron 下载镜像的正确环境变量；`npm_config_electron_mirror` 不是当前 Electron 下载器使用的变量。
- npm registry（例如 `https://registry.npmmirror.com`）只负责 Electron npm 包下载，Electron 运行时仍需单独下载。
- 使用 `npm install --ignore-scripts` 后不会自动下载 Electron 运行时，必须手动完成上述下载和解压步骤。
- `npx electron` 在本地包缺失时可能安装临时包；优先使用 `./node_modules/.bin/electron` 验证项目本地安装。
