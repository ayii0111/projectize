# projectize

Claude Code 指令 `/projectize`：替當前 session 命名主題，轉成 `~/cc-projects/<主題>` 下的正式專案。

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ayii0111/projectize/main/install.sh | bash
```

安裝後在 CC 執行 `/reload-plugins` 套用。

## Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/ayii0111/projectize/main/uninstall.sh | bash
```

## Usage

在任意目錄開 CC session，聊到主題成形後輸入 `/projectize`：

1. 挑中文主題名（4 個建議或自訂）
2. 挑英文目錄名（kebab-case，可用 `分類/名稱`）
3. 確認要一起搬走的檔案（本 session 用 Write/Edit 動過、位於當前目錄底下者）
4. CC 自動結束，背景完成遷移，終端機印出接續指令並複製到剪貼簿：

```sh
cd ~/cc-projects/<名稱> && claude --resume <session-id>
```

## 遷移範圍

| 項目 | 處理方式 |
|---|---|
| 本 session 動過的檔案 | 搬移（保留相對路徑），原處變空的目錄會刪掉 |
| `~/.claude/projects/<舊>/<sid>.jsonl`、`<sid>/` | 搬移，並把紀錄中的 `cwd` 改成新路徑 |
| `~/.claude/projects/<舊>/memory/` | 複製（原專案保留） |
| `~/.claude/history.jsonl` | 只改本 session 那幾行的 `project` |
| 原目錄的其他 session | 不動 |

遷移前會備份 session 檔與 `history.jsonl` 到 `~/.claude/projectize/backups/`，log 在 `~/.claude/projectize/projectize.log`。

## 限制

- 用 Bash 產生的檔案偵測不到，需要的話請自行搬移
- 在新目錄第一次 resume 時，CC 會詢問是否信任該資料夾
- `/rewind` 的檔案快照仍指向舊路徑，對搬走的檔案無效

## 安裝原理

- 腳本採 plugin 安裝（`scripts/projectize.py`）
- 指令檔 `command-template/projectize.md` 由 install.sh 複製到 `~/.claude/commands/`，避免指令顯示成「projectize:projectize」
- session 進行中 CC 會持續寫入 `.jsonl`，所以遷移交給背景程序：先結束 CC，等程序退出後才搬
