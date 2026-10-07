---
description: (projectize) 為當前 session 命名主題，轉成 ~/cc-projects 下的正式專案
disable-model-invocation: true
---

# /projectize

把當前 session 轉成 `~/cc-projects/<英文主題名>` 專案。全程用繁體中文與用戶溝通。

## 0. 定位腳本並取得 context

```sh
S=$(command ls -d ~/.claude/plugins/cache/*/projectize/*/scripts/projectize.py 2>/dev/null | command sort -V | command tail -1)
python3 "$S" context
```

找不到腳本就告知用戶 projectize plugin 未安裝並停止。之後的步驟都用同一個 `$S` 絕對路徑。

## 1. 中文主題

根據本 session 的對話內容，用 AskUserQuestion 提供 4 個中文主題名稱建議（精簡、能看出主題，2–8 字）。
用戶可能選 Other 自己輸入。

## 2. 英文目錄名

針對選定的中文主題，用 AskUserQuestion 提供 4 個英文目錄名建議：

- 小寫英數 + `-`（kebab-case），2–4 個單字為佳
- 不可與 context 中的 `existing_projects` 重名
- 若明顯屬於既有的分類目錄（例如 `job-seeking`），可提供 `分類/名稱` 形式（最多一層 `/`）

每個選項的 description 寫出完整目標路徑 `~/cc-projects/<名稱>`。

## 3. 確認要搬的檔案

`touched_files` 是本 session 用 Write/Edit 動過、位於當前目錄底下的檔案（相對路徑）。

- 清單為空：告知只會搬 session 資料，直接進下一步
- 清單非空：先列出清單，再用 AskUserQuestion 詢問「全部搬移 / 都不搬，只搬 session / 我要調整」；選調整就依用戶指示增減（只能從清單中挑）
- `is_git_repo` 為 true 時提醒：搬走的檔案會在原 repo 中變成刪除狀態

## 4. 執行

先用 `--dry-run` 檢查：

```sh
python3 "$S" run --name <英文名> --files <檔案1> <檔案2> ... --dry-run
```

沒問題後，**在同一則回覆中**先輸出一段總結（新專案路徑、搬了哪些檔案、CC 將自動結束、接續指令會印在終端機並複製到剪貼簿），再執行正式指令：

```sh
python3 "$S" run --name <英文名> --files <檔案1> <檔案2> ...
```

不搬檔案時省略 `--files`。正式執行成功後約 1.5 秒 CC 會自動結束，背景程序接著遷移 session 資料。

若回傳 `ok: false`，把 error 告訴用戶，不要自行重試其他名稱。
