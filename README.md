# wechat-local-export

微信 4.x 本地数据导出与结构化处理工具。面向**本人账号、已获授权**的本地备份场景：捕获数据库密钥 → 批量解密 SQLCipher 4 数据库 → 导出消息、语音并离线转写。

> **适配版本：微信 4.1.11.55（Windows 10 x64，2026-08 实测）。**
> 微信升级后数据库表名、字段和媒体格式可能变化，使用前请先运行 `scripts/inspect_db.py` 校验结构。

## 功能

- 通过外部 Hook DLL 捕获微信数据库 passphrase（仓库提供调用层，DLL 需自备）
- 按每个库文件头 salt 派生 raw key，批量解密 SQLCipher 4 数据库
- 批量发现 `Msg_<md5>` 消息表，导出为 JSONL / CSV
- 按会话、时间范围、条数过滤
- 从 `media_0.decrypted.db` 的 `VoiceInfo` 表批量提取语音
- SILK V3 → PCM → WAV（24 kHz 单声道 16-bit）
- faster-whisper 离线转写，输出带时间戳的文本
- 数据库结构巡检：表名、列名、行数

## 边界

本仓库包含密钥捕获的**调用层**、SQLCipher 4 解密实现和导出/转写工具，但**不包含**：

- 任何第三方 Hook DLL、EXE 或二进制文件
- 任何真实密钥、聊天记录、语音、图片、模型权重或训练数据
- 第三方 clone 仓库的代码

Hook DLL 需要按目标微信版本自行编译或从可信来源取得；本仓库只定义调用接口，不打包、不分发 DLL。请仅用于**本人账号、已获授权**的本地数据；不要用于他人账号或未经授权的数据。

## 目录

```text
scripts/
  hook_key.py             # 通过外部 Hook DLL 捕获数据库密钥
  decrypt_db.py           # SQLCipher 4 单库/批量解密
  inspect_db.py           # 查看数据库表、列、行数
  export_messages.py      # 导出消息为 JSONL / CSV
  export_voices.py        # 提取语音并转 WAV
  transcribe_voices.py    # faster-whisper 离线转写
docs/
  key-extraction.md       # Hook 接口、密钥格式与版本敏感性
  sqlcipher.md            # SQLCipher 4 参数与页格式
  schema.md               # 4.1.11.55 常见表结构
  version-compatibility.md# 版本适配与时间敏感性说明
```

## 环境

- Python 3.10+
- 密钥捕获仅支持 Windows（需要 Hook `Weixin.exe`）；解密与导出可跨平台
- 依赖：`pycryptodome`、`psutil`、`pilk`、`faster-whisper`、`zstandard`（可选，用于解压部分消息内容）

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

## 快速开始

### 1. 捕获数据库密钥

需要自行准备与微信版本匹配的 Hook DLL。仓库不附带 DLL，也不附带任何密钥。

```bash
python scripts/hook_key.py ^
  --dll "C:\path\to\your_key_hook.dll" ^
  --process Weixin.exe ^
  --out ".\out\db.key"
```

捕获期间在微信中切换或打开聊天窗口。接口、密钥格式与版本注意事项见 [docs/key-extraction.md](docs/key-extraction.md)。

### 2. 批量解密

```bash
python scripts/decrypt_db.py ^
  --dir "C:\Users\<you>\xwechat_files\<wxid>\db_storage" ^
  --key-file ".\out\db.key" ^
  --out-dir ".\out\decrypted"
```

每个 `.db` 用自己的文件头 salt 派生 raw key；默认跳过已存在的 `.decrypted.db`，`--force` 可覆盖。参数与页格式见 [docs/sqlcipher.md](docs/sqlcipher.md)。

### 3. 检查数据库结构

```bash
python scripts/inspect_db.py --db "C:\path\to\message_0.decrypted.db"
```

输出示例：

```text
message_0.decrypted.db
  Name2Id                  rows=...
  Msg_<md5>                rows=...
```

### 4. 导出消息

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

### 5. 导出语音

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

### 6. 离线转写

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
| 4.1.11.55 | 实测 | Hook 捕获密钥、SQLCipher 4 解密、消息/媒体库导出与 SILK V3 转写可用 |
| 4.1.8 | 未实测 | 表结构可能不同，先运行 `inspect_db.py` |
| 4.0.x | 未实测 | 表结构可能不同 |

**时间敏感性：** 微信 4.1.x 的数据库结构和媒体格式会随版本变化。本项目记录的是 2026-08 在 4.1.11.55 上的适配结果；升级微信后请重新校验。

## 安全与合规

- 仅处理本人账号的数据，或已取得明确授权的数据。
- 不要导出、传播或训练他人聊天记录、语音和图片。
- 密钥等同于数据库明文访问权限：不要提交到 Git、不要发到聊天工具、不要写进截图；导出完成后删除密钥文件。
- 仓库不附带 Hook DLL；DLL 需要按目标微信版本自行编译或从可信来源取得。
- 使用前请确认符合当地法律、微信软件许可协议和所在组织的规定。

## 第三方依赖

| 依赖 | 用途 |
|---|---|
| [pycryptodome](https://www.pycryptodome.org/) | AES-256-CBC 解密 |
| [psutil](https://github.com/giampaolo/psutil) | 定位 `Weixin.exe` 进程 |
| [pilk](https://pypi.org/project/pilk/) | SILK V3 解码 |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | 离线语音转写 |
| [zstandard](https://github.com/facebook/zstd) | 可选，解压 zstd 消息内容 |

依赖项版权与许可证归各自上游项目所有，本项目不打包其源码。Hook DLL 不属于本仓库的依赖，也不随仓库分发。

## English

A toolkit for your own authorized WeChat 4.x local backup: capture the database passphrase through an external hook DLL you supply, decrypt SQLCipher 4 databases with per-file salts and PBKDF2-HMAC-SHA512, then export message tables to JSONL/CSV, extract `VoiceInfo` blobs to WAV, and transcribe offline with faster-whisper. Tested on WeChat `4.1.11.55` (Windows x64, 2026-08). The repository contains the hook client, the decryption implementation, and the export tools, but no hook DLL, no keys, no chats, and no third-party binaries or personal data.

## License

MIT
