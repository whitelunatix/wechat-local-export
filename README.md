# wechat-local-export

微信 4.x 本地数据导出与结构化处理工具。面向**本人账号、已获授权**的本地备份场景，从已解密的 SQLite 数据库开始，批量导出消息、语音和转写文本。

> **适配版本：微信 4.1.11.55（Windows 10 x64，2026-08 实测）。**
> 微信升级后数据库表名、字段和媒体格式可能变化，使用前请先运行 `scripts/inspect_db.py` 校验结构。

## 功能

- 批量发现 `Msg_<md5>` 消息表，导出为 JSONL / CSV
- 按会话、时间范围、条数过滤
- 从 `media_0.decrypted.db` 的 `VoiceInfo` 表批量提取语音
- SILK V3 → PCM → WAV（24 kHz 单声道 16-bit）
- faster-whisper 离线转写，输出带时间戳的文本
- 数据库结构巡检：表名、列名、行数

## 边界

本项目**不包含**以下内容，也不会随仓库分发：

- 微信数据库密钥提取、内存扫描或进程 Hook
- 任何第三方 DLL、EXE 或二进制文件
- 任何聊天记录、语音、图片、模型权重或训练数据
- 第三方 clone 仓库的代码

输入数据库需要由使用者通过**本人账号、已授权**的方式准备为 `.decrypted.db`。请勿用于他人账号或未经授权的数据。

## 目录

```text
scripts/
  inspect_db.py           # 查看数据库表、列、行数
  export_messages.py      # 导出消息为 JSONL / CSV
  export_voices.py        # 提取语音并转 WAV
  transcribe_voices.py    # faster-whisper 离线转写
docs/
  schema.md               # 4.1.11.55 常见表结构
  version-compatibility.md# 版本适配与时间敏感性说明
```

## 环境

- Python 3.10+
- Windows / Linux / macOS
- 依赖：`pilk`、`faster-whisper`、`zstandard`（可选，用于解压部分消息内容）

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

## 快速开始

### 1. 检查数据库结构

```bash
python scripts/inspect_db.py --db "C:\path\to\message_0.decrypted.db"
```

输出示例：

```text
message_0.decrypted.db
  Name2Id                  rows=...
  Msg_<md5>                rows=...
```

### 2. 导出消息

```bash
python scripts/export_messages.py ^
  --db "C:\path\to\message_0.decrypted.db" ^
  --out ".\out\messages.jsonl" ^
  --format jsonl
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--db` | 已解密的 `message_*.decrypted.db` |
| `--out` | 输出文件；`jsonl` 或 `csv` |
| `--format` | `jsonl`（默认）或 `csv` |
| `--session` | 只导出指定会话的 `user_name`；不填则全部 |
| `--since` | 起始日期，格式 `YYYY-MM-DD` |
| `--limit` | 最多导出的消息条数（全局） |
| `--decompress` | 尝试解压 zstd 压缩的 `message_content` |

输出字段：

```json
{"session":"<user_name>","create_time":1700000000,"datetime":"2023-11-15 06:13:20","local_id":123,"sender":"<user_name>","type":1,"content":"..."}
```

### 3. 导出语音

```bash
python scripts/export_voices.py ^
  --db "C:\path\to\media_0.decrypted.db" ^
  --out ".\out\voices" ^
  --chat all
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--db` | 已解密的 `media_0.decrypted.db` |
| `--out` | WAV 输出目录 |
| `--chat` | `all` 或指定会话 `user_name` |
| `--limit` | 最多提取条数 |
| `--keep-silk` | 保留中间 `.silk` 文件 |
| `--anonymize` | manifest 中的会话名替换为 SHA-256 前 12 位 |

输出：

- `voice_00001_<timestamp>.wav`
- `manifest.jsonl`：`index`、`session`、`create_time`、`local_id`、`duration`、`wav`

### 4. 离线转写

```bash
python scripts/transcribe_voices.py ^
  --wav-dir ".\out\voices" ^
  --out ".\out\transcripts" ^
  --model small ^
  --language zh
```

默认使用 CPU + `int8`，首次运行会下载 Whisper 模型。输出每个 WAV 对应的 `.txt`，格式为：

```text
[0.0-2.4s] 第一段文本
[2.4-5.1s] 第二段文本
```

## 版本适配

详见 [docs/version-compatibility.md](docs/version-compatibility.md)。

| 微信版本 | 状态 | 说明 |
|---|---|---|
| 4.1.11.55 | 实测 | 消息库、媒体库、SILK V3 语音导出与转写可用 |
| 4.1.8 | 未实测 | 表结构可能不同，先运行 `inspect_db.py` |
| 4.0.x | 未实测 | 表结构可能不同 |

**时间敏感性：** 微信 4.1.x 的数据库结构和媒体格式会随版本变化。本项目记录的是 2026-08 在 4.1.11.55 上的适配结果；升级微信后请重新校验。

## 安全与合规

- 仅处理本人账号的数据，或已取得明确授权的数据。
- 不要导出、传播或训练他人聊天记录、语音和图片。
- 本项目不提供密钥提取或 Hook 能力；输入数据库的获取方式由使用者自行负责。
- 使用前请确认符合当地法律、微信软件许可协议和所在组织的规定。

## 第三方依赖

| 依赖 | 用途 |
|---|---|
| [pilk](https://pypi.org/project/pilk/) | SILK V3 解码 |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | 离线语音转写 |
| [zstandard](https://github.com/facebook/zstd) | 可选，解压 zstd 消息内容 |

依赖项版权与许可证归各自上游项目所有，本项目不打包其源码。

## English

A small toolkit for exporting **your own authorized** WeChat 4.x local backup: message tables to JSONL/CSV, `VoiceInfo` blobs to WAV, and offline transcription with faster-whisper. Tested on WeChat `4.1.11.55` (Windows x64, 2026-08). It starts from an already-decrypted SQLite database and does **not** include key extraction, process hooking, third-party binaries, or any personal data.

## License

MIT
