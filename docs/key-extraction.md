# 密钥获取（Hook DLL）

> 仅用于**本人账号、已获授权**的本地数据导出。不要对他人账号、他人设备或未经授权的数据使用。

## 仓库提供什么

本仓库提供密钥捕获的**调用层**：[`scripts/hook_key.py`](../scripts/hook_key.py)。它负责：

1. 找到持有 `message_0.db` 的 `Weixin.exe` 进程；
2. 加载一个由使用者自行提供的 Hook DLL；
3. 调用 DLL 的 `InitializeHook(pid)` 注入；
4. 轮询 `PollKeyData`，拿到数据库 passphrase；
5. 把 64 位十六进制密钥写入指定文件（或输出到 stdout）。

**仓库不包含 Hook DLL 本身，也不包含任何真实密钥。** DLL 需要按目标微信版本自行编译或从可信来源取得；不同版本的函数偏移、签名和注入时机都可能变化。

## DLL 接口

`hook_key.py` 只依赖下面这组导出，DLL 可以是 C/C++、Rust 或其他语言实现：

| 导出 | 签名 | 说明 |
|---|---|---|
| `InitializeHook` | `bool InitializeHook(uint32_t pid)` | 在目标进程安装 Hook，成功返回 true |
| `PollKeyData` | `bool PollKeyData(char *buf, int cap)` | 有密钥时写入缓冲区并返回 true |
| `GetStatusMessage` | `bool GetStatusMessage(char *buf, int cap, int *level)` | 取出内部日志，便于排查 |
| `CleanupHook` | `bool CleanupHook()` | 卸载 Hook、释放资源 |
| `GetLastErrorMsg` | `const char *GetLastErrorMsg()` | 返回最近一次错误文本 |

Hook 的目标是微信在打开数据库时调用的密钥设置函数（`SetDBKey` 一类）。捕获到的值就是 SQLCipher 的 32 字节 passphrase，通常以 64 位十六进制字符串表示。

## 使用

```bash
python scripts/hook_key.py ^
  --dll "C:\path\to\your_key_hook.dll" ^
  --process Weixin.exe ^
  --marker message_0.db ^
  --out ".\out\db.key"
```

捕获期间在微信里切换或打开一个聊天窗口，触发数据库密钥设置。成功后会看到：

```text
[+] target process: Weixin.exe (pid=...)
[+] loading: C:\path\to\your_key_hook.dll
[+] hook installed; open or switch a chat to trigger a database key operation
[+] key written to .\out\db.key
```

`--timeout` 默认 120 秒。若一直超时，通常是 DLL 与微信版本不匹配，或注入到了子进程而不是真正持有数据库的主进程。

## 密钥格式与保管

- 捕获值是 32 字节原始密钥的十六进制表示，共 64 个字符。
- `decrypt_db.py` 会从这个值出发，按每个数据库自己的 salt 派生 raw key。
- 密钥等同于数据库明文访问权限：不要提交到 Git、不要发到聊天工具、不要写进截图。
- `--out` 建议放在仓库外，或使用已被 `.gitignore` 忽略的 `*.key` / `*key*.txt`。
- 导出完成后删除密钥文件；需要再次导出时重新捕获。

## 验证密钥是否正确

```bash
python scripts/decrypt_db.py ^
  --db "C:\path\to\message_0.db" ^
  --key-file ".\out\db.key" ^
  --out ".\out\message_0.decrypted.db"
```

如果密钥错误，脚本会在第一页的 HMAC 校验处失败，而不会写出一个损坏的数据库：

```text
[-] ...: HMAC verification failed on page 1
```

## 版本敏感性

本项目在微信 **4.1.11.55（Windows 10 x64，2026-08）** 上实测。微信升级后：

- Hook DLL 的偏移/签名可能失效，需要重新适配；
- 数据库可能改用不同的页大小、KDF 迭代次数或 HMAC 参数；
- 先运行 `scripts/inspect_db.py` 和 `scripts/decrypt_db.py` 验证，再批量处理。

详见 [version-compatibility.md](version-compatibility.md)。
