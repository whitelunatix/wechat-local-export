# 微信 4.1.11.55 本地数据库结构（节选）

> 仅记录本项目用到的表结构，不包含任何账号、联系人或聊天内容。

## 数据库位置

```text
<WeChat data root>/
  db_storage/
    message/
      message_0.db
      message_1.db
      ...
    message/
      media_0.db
    ...
```

解密后的文件通常命名为 `*.decrypted.db`。

## 消息库

### `Name2Id`

```sql
CREATE TABLE Name2Id (
  rowid     INTEGER PRIMARY KEY,
  user_name TEXT
);
```

`user_name` 是会话/联系人的内部标识（如 `wxid_...` 或群 ID）。消息表名与 `user_name` 的 MD5 对应：

```text
Msg_<md5(user_name)>
```

例如，脚本先用 `Name2Id` 建立 `md5 -> user_name` 映射，再扫描所有 `Msg_*` 表。

### `Msg_<md5>`

不同版本字段可能略有差异。本项目动态读取列名，常见列包括：

| 列 | 说明 |
|---|---|
| `create_time` | Unix 时间戳 |
| `local_id` | 会话内本地序号 |
| `sender_username` | 发送者标识 |
| `message_content` | 文本或压缩后的消息内容 |
| `type` | 消息类型 |
| `is_sender` | 是否本人发送 |
| `server_id` | 服务端消息 ID |
| `sort_seq` | 排序序号 |

部分 `message_content` 可能是 zstd 压缩数据。`export_messages.py --decompress` 会在 zstd 魔数 `28 b5 2f fd` 出现时尝试解压。

## 媒体库

### `VoiceInfo`

```sql
CREATE TABLE VoiceInfo (
  chat_name_id INTEGER,
  create_time  INTEGER,
  local_id     INTEGER,
  svr_id       INTEGER,
  voice_data   BLOB
);
```

`voice_data` 是 SILK V3 数据，文件头为 `#!SILK_V3`。使用 `pilk` 解码为 PCM，再按 24 kHz、单声道、16-bit 写入 WAV。

## 版本差异

`PRAGMA table_info(...)` 是判断字段是否存在的最可靠方式。脚本不会假设所有版本列名完全一致；如果某个版本缺少 `message_content` 或 `voice_data`，脚本会跳过对应表并输出提示。

微信升级后建议先运行：

```bash
python scripts/inspect_db.py --db "path\to\message_0.decrypted.db"
```

确认表名和列名后再执行导出。
