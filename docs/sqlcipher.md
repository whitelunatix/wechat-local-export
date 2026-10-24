# SQLCipher 4 解密

微信 4.x 的本地数据库是 SQLCipher 4 加密的 SQLite 文件。本文记录 `scripts/decrypt_db.py` 使用的参数和页格式，便于在新版本上排查兼容性问题。

## 参数

| 参数 | 值 |
|---|---|
| 页大小 | 4096 字节 |
| KDF | PBKDF2-HMAC-SHA512 |
| KDF 迭代次数 | 256000 |
| 原始密钥长度 | 32 字节 |
| 每库 salt | 文件前 16 字节 |
| 每页 IV | 16 字节 |
| 每页 HMAC | 64 字节（HMAC-SHA512） |
| 每页保留区 | 80 字节（16 IV + 64 HMAC，按 AES 块对齐） |

## 从 passphrase 到 raw key

Hook 捕获到的是 32 字节 passphrase。每个 `.db` 文件的前 16 字节是独立 salt，所以**同一个 passphrase 在不同库上会派生出不同的 raw key**：

```text
raw_key = PBKDF2-HMAC-SHA512(passphrase, salt, 256000, 32)
```

`raw_key` 直接作为 AES-256 的密钥，不再做一次 KDF。

## HMAC key

```text
mac_salt = salt XOR 0x3a          # 每个字节异或
mac_key  = PBKDF2-HMAC-SHA512(raw_key, mac_salt, 2, 32)
```

HMAC 使用 SHA-512，输入为：

```text
ciphertext || IV || page_number (4 字节小端)
```

第 1 页的布局特殊：前 16 字节是 salt，之后才是密文。

## 页布局

### 第 1 页

```text
offset 0                     16
       +---------------------+--------------------------+--------+--------+
       | salt (16)           | ciphertext (4000)        | IV (16)| HMAC(64)|
       +---------------------+--------------------------+--------+--------+
                             ^                          ^
                             |                          |
                     解密后写回 SQLite 头          AES-CBC 的 IV
```

解密后输出：

```text
"SQLite format 3\0" (16) || AES-CBC-decrypt(ciphertext, raw_key, IV) (4000) || IV || HMAC (80)
```

### 第 2 页及以后

```text
+--------------------------+--------+--------+
| ciphertext (4016)        | IV (16)| HMAC(64)|
+--------------------------+--------+--------+
```

解密后输出：

```text
AES-CBC-decrypt(ciphertext, raw_key, IV) (4016) || IV || HMAC (80)
```

保留区原样写回。SQLite 读取时按文件头里的 reserved-space 字节数忽略它，因此解密后的文件可以直接用 `sqlite3` 打开。

## 校验

每一页解密前都会校验 HMAC。这样做的原因：

- 密钥错误时，第一页就会失败，不会生成看似正常但内容损坏的库；
- 文件被截断、页大小变化或 KDF 参数变化时，能尽早发现；
- 批量处理时可以准确报告哪一个库失败。

错误示例：

```text
[-] message_0.db: HMAC verification failed on page 1
```

## 批量处理

```bash
python scripts/decrypt_db.py ^
  --dir "C:\Users\<you>\xwechat_files\<wxid>\db_storage" ^
  --key-file ".\out\db.key" ^
  --out-dir ".\out\decrypted"
```

行为：

- 递归查找 `.db`，跳过已经以 `.decrypted.db` 结尾的文件；
- 每个文件用自己的前 16 字节重新派生 raw key；
- 默认输出到源文件旁边；指定 `--out-dir` 时按相对路径镜像目录；
- 已存在的输出默认跳过，`--force` 覆盖；
- 单个文件失败不影响其他文件，最后输出成功/跳过/失败计数。

## 兼容性

以上是 SQLCipher 4 的默认参数，已在微信 **4.1.11.55** 上实测。微信后续版本如果修改页大小、KDF 迭代次数或保留区大小，需要同步调整 `scripts/decrypt_db.py` 顶部的常量，并用 `scripts/inspect_db.py` 验证解出的库结构。
