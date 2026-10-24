# 版本适配与时间敏感性

## 实测版本

| 项目 | 值 |
|---|---|
| 微信版本 | **4.1.11.55** |
| 平台 | Windows 10 x64 |
| 实测时间 | 2026-08-04 |
| 数据库 | SQLCipher 4；`db_storage/message/message_*.db`、`media_0.db` |
| 密钥捕获 | Hook `Weixin.exe` 的数据库密钥设置函数；passphrase 为 32 字节（64 hex） |
| 解密参数 | PBKDF2-HMAC-SHA512、256000 次、4096 字节页、每页 80 字节保留区 |
| 语音格式 | SILK V3（`#!SILK_V3`） |
| 消息导出 | `Msg_<md5(user_name)>` 表；`Name2Id` 映射 |
| 语音导出 | `VoiceInfo.voice_data` → `pilk` → WAV |
| 转写 | faster-whisper `small`，CPU `int8` |

## 兼容性矩阵

| 微信版本 | 状态 | 说明 |
|---|---|---|
| 4.1.11.55 | ✅ 实测 | 密钥 Hook、SQLCipher 4 解密、消息/语音导出与转写流程可用 |
| 4.1.8 | ⚠️ 未实测 | 第三方工具曾支持该版本；表结构可能不同 |
| 4.0.x | ⚠️ 未实测 | 表结构可能不同 |
| 更早 3.x | ❌ 不适用 | 数据库与媒体格式差异较大 |

## 时间敏感性

微信 4.1.x 的数据库表名、字段、消息压缩方式和媒体格式会随版本更新。**本项目的适配结论只对 4.1.11.55 负责**；升级微信后可能出现：

- `Name2Id` / `Msg_*` 表名或列名变化
- `message_content` 压缩方式变化
- `VoiceInfo` 表结构或语音编码变化
- 图片/表情缓存格式变化

升级后的处理顺序：

1. 用 `scripts/hook_key.py` 捕获密钥，再用 `scripts/decrypt_db.py` 解一个库；HMAC 校验通过才说明页格式与 KDF 参数仍然匹配。
2. 运行 `scripts/inspect_db.py`，确认表和列。
3. 先用 `--limit 20` 小批量验证 `export_messages.py`。
4. 再用 `--limit 5` 验证 `export_voices.py` 与 `transcribe_voices.py`。
5. 确认输出字段和音频可读后，再全量导出。

## 不在本项目范围

- Hook DLL、任何第三方 DLL、EXE 或二进制文件
- 内存扫描脚本（本项目只提供 Hook 调用层）
- 图片 V2 解密、表情缓存解密
- 发送消息、UI 自动化、实时监控
- 任何真实密钥、聊天数据、语音、模型权重或训练集

本项目只处理使用者通过**本人账号、已授权**方式准备的本地数据。密钥捕获需要使用者自行提供与微信版本匹配的 Hook DLL；请勿用于他人账号或未经授权的数据。
