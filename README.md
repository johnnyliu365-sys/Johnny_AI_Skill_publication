A local-first control plane for structured, traceable and safer AI-assisted software development with Codex and Claude Code.
## 它會對你的 repository 做什麼、不做什麼

**Router 是 metadata-only 的控制平面。** 政策來源文字以型別化 metadata 進入一個暫時
作用域，不被儲存、不被回放、不被回傳——把它指向一個 repository，不等於把那個
repository 的內容交給治理它的平面。

**派工回應只由一個活的 pending descriptor 產生**，且必須綁定已審閱的票、其 handoff
receipt、commit 與具名的實作負責人。偽造、重放、缺失或不相符的 descriptor 產生的
不是降級的回應，而是沒有回應、沒有能力。

交付階段停在 `POC`，直到被核准的產出與變更紀錄另行說明。`MVP` 與 `COMMERCIAL` 是
profile 控制的階段，兩者都不是 plugin 可以自己從「進度看起來不錯」推斷出來的
active product objective。

## 安裝前先確認

先確認電腦有：

* Git：`git --version`
* Python 3.11：`py -3.11 --version`
* 如果要用 Level 1，還需要先安裝 Claude Code

## 安裝時最容易踩的坑

**不要在任何 Git repository 裡執行安裝。**

很多人會直接把安裝檔丟進自己的專案資料夾再雙擊，但這樣安裝器會直接擋掉：

`INSTALL_BLOCKED_INSIDE_REPOSITORY`

請另外找一個普通資料夾，例如下載資料夾或桌面上的暫存資料夾。

## Level 1：只安裝 Claude Code Plugin

在終端機執行（raw descriptor 只提供 marketplace metadata；plugin source 由 descriptor
指向獨立的 publication repository）：

```bash
claude plugin marketplace add https://raw.githubusercontent.com/johnnyliu365-sys/Johnny_AI_Skill/main/.claude-plugin/marketplace.json
claude plugin install johnny-ai-skill@johnny-ai-skill --scope user
```

更新或移除 user-scope plugin：

```bash
claude plugin update johnny-ai-skill@johnny-ai-skill --scope user
claude plugin uninstall johnny-ai-skill@johnny-ai-skill --scope user
claude plugin marketplace remove johnny-ai-skill
```

Publication repository 的建立、promotion、pin 與 release readback 是 owner-controlled
release operation；使用者安裝不會替 owner 建立 repository 或移動 release refs。

完成後重新開啟 Claude Code session，或輸入：

```text
/reload-plugins
```

## Level 2：安裝完整 Router Runtime

1. 把 `johnny-install.cmd` 和 release 的 zip 下載到**同一個資料夾**
2. 確認這個資料夾**不是 Git repository**
3. 雙擊 `johnny-install.cmd`
4. 安裝器會先檢查 zip 的 SHA-256
5. 驗證通過後會顯示要安裝的內容
6. 確認沒問題後，手動輸入：

```text
INSTALL
```

才會正式開始安裝。

## 確認有沒有裝成功

執行：

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\JohnnyRouter\launcher\johnny-router.ps1" status
```

看到：

```json
"status": "OK"
```

就代表安裝完成。

## 常見錯誤

| 錯誤代碼                                | 怎麼處理                                |
| ----------------------------------- | ----------------------------------- |
| `INSTALL_BLOCKED_INSIDE_REPOSITORY` | 換到不是 Git repo 的資料夾再執行               |
| `PYTHON_311_UNAVAILABLE`            | 安裝 Python 3.11                      |
| `GIT_UNAVAILABLE`                   | 安裝 Git                              |
| `BUNDLE_NOT_FOUND`                  | 確認 zip 和 `johnny-install.cmd` 放在同一層 |
| `DIGEST_MISMATCH`                   | 檔案可能不完整，重新下載                        |
| `USER_DECLINED`                     | 需要手動輸入 `INSTALL`                    |
| `VENV_ALREADY_PRESENT`              | 已經安裝過，先 uninstall 再重裝               |
