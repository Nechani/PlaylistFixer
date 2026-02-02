1. 什麼是 Playlist Fixer？

Playlist Fixer 是一款用來修復損壞播放清單檔案
（.m3u / .m3u8）的工具，
適用於 音樂檔仍然存在，但路徑、格式或使用裝置已改變 的情況。

本工具 不會修改任何音樂檔案本身。
它只會重新掃描現有的音樂檔案，
並將播放清單中的錯誤參照重新連結到正確的檔案。

Playlist Fixer 適合你，如果你有以下情況：

更換電腦（Windows ↔ macOS）

重新整理、搬移音樂資料夾

轉換音樂格式（FLAC → ALAC / WAV 等）

在不同裝置之間移轉播放清單

使用 DAP（數位音樂播放器）卻漏歌或讀不到播放清單

播放器（Roon、Foobar、DAP 等）無法正確讀取播放清單

Playlist Fixer 不適合以下用途：

下載遺失的音樂檔案

編輯音樂標籤或中繼資料

管理串流平台播放清單
（Spotify / Apple Music 線上播放清單）

2. 常見使用情境

Playlist Fixer 可在許多實際情況中派上用場：

💻 電腦更換

換新電腦後，舊播放清單中的路徑已不存在

音樂資料夾結構改變

🔄 音樂格式轉換

原播放清單指向 .flac

實際檔案已轉為 .alac、.wav 等格式

🎧 DAP 播放清單修復

DAP 無法正確讀取播放清單

歌曲遺失或只讀到一部分

使用電腦的音樂庫 修復 DAP 的播放清單

或將 DAP 匯出的播放清單修復後在電腦上使用

🔁 跨裝置播放清單復原

修復在 DAP 建立的播放清單，轉回電腦使用

修復電腦播放清單，讓 DAP 能正常讀取

3. 使用前準備
支援的播放清單格式

.m3u

.m3u8

支援的音樂檔案格式

Playlist Fixer 僅能修復 實際存在的音樂檔案。

支援格式包含：

常見有損格式
.mp3, .aac, .ogg, .opus

無損格式
.flac, .wav, .aif, .aiff, .ape, .wv

Apple 容器
.m4a, .alac

DSD 格式
.dsf, .dff（盡力支援）

⚠️ 若音樂檔案在任何音樂資料夾中都不存在，將無法修復。

4. 操作流程（逐步說明）
Step 1 – 新增音樂資料夾

點擊 「Add Music Folder」，
選擇一個或多個包含音樂檔案的資料夾。

這些資料夾將用來建立搜尋索引。

Step 2 – 掃描／重建索引

點擊 「Scan / Rebuild Index」。

此步驟會掃描所有音樂檔案，
建立可搜尋的索引資料。

※ 除非你更動了音樂資料夾，否則不需要重複執行。

Step 3 – 匯入播放清單

點擊 「Import Playlist(s)」，
並選擇 一個 .m3u 或 .m3u8 播放清單檔案。

Playlist Fixer 一次只能修復一個播放清單。
請完成修復並儲存後，再匯入下一個。

Step 4 – 修復（安全模式）

點擊 「Repair (Safe)」。

系統會分析播放清單內容，並分類為：

Kept – 已正確，無需處理

Repaired (Auto) – 已自動修復

Ambiguous – 找到多個可能結果

Failed – 找不到對應檔案

詳細分析結果會輸出至 reports/ 資料夾。

Step 5 – 處理未解決項目

使用 View 選擇器：

Unresolved – 尚需處理的項目

Resolved – 已自動或手動修復的項目（檢查用）

Ambiguous（多重可能）

選取一列

從候選清單中選擇正確檔案

點擊 Apply

Failed（未找到）

選取一列

點擊 Browse

手動選擇正確的音樂檔案

點擊 Apply

所有 Apply 的修復結果，
在儲存前都只會保留在記憶體中。

Step 6 – 儲存修復後的播放清單

點擊 「Save Fixed Playlist」。

此步驟將會：

產生新的播放清單檔案
fixed_*_selected.m3u

儲存你所有的手動修復選擇

將已修復項目從 Unresolved 中移除

⚠️ 只有這個步驟會實際寫入檔案。

5. 報告與輸出檔案說明

所有修復相關檔案都會存放在 reports/ 資料夾。

重要檔案說明

repair_report_*.csv
播放清單每一列的詳細分析結果

fixed_*_selected.m3u
修復完成的最終播放清單

selections_*.json
手動修復的選擇記錄（用於復原或檢查）

⚠️ 若刪除這些檔案，修復進度將會遺失。

6. 發生問題時

若遇到問題並需要協助，請準備以下資料：

請提供

原始播放清單檔案（.m3u / .m3u8）

對應的 repair_report_*.csv

selections_*.json（若存在）

請勿提供

整個音樂資料庫

大型音樂檔案

請一併說明

你原本預期的結果

實際發生的狀況

使用的作業系統（Windows / macOS）

7. 作者與聯絡方式

作者： Ne
GitHub： https://github.com/Nechani

問題回報 / 意見回饋： plfixne@gmail.com

支持開發： https://ko-fi.com/nechani

如果這個工具幫你節省了時間，
或成功救回你的播放清單，
歡迎請我喝杯咖啡 ☕

✔ 最後說明

Playlist Fixer 的設計核心是：

安全（不進行破壞性操作）

透明（所有結果都有 CSV 紀錄）

可復原（手動選擇會被保存）

它只為了一件事而存在：

保護你多年累積下來的播放清單。