# Playlist Fixer 完整使用說明（繁體中文）

Playlist Fixer 是一款用來修復檔案型播放清單的本機工具。

當音樂檔案仍然存在，但因為更換電腦、磁碟代號改變、資料夾搬移、格式轉換、跨裝置使用，或 Roon 匯出路徑與目前電腦不同而導致播放清單失效時，Playlist Fixer 會重新掃描你的音樂資料庫，找出正確檔案並建立新的播放清單。

> Playlist Fixer 不會修改音樂檔案本身，也不會覆蓋原始播放清單。

---

## 1. Playlist Fixer 能做什麼

Playlist Fixer 適合以下情況：

- 更換電腦後，舊播放清單中的路徑已不存在
- 磁碟代號改變，例如 `D:\Music` 變成 `E:\Music`
- 音樂資料夾被搬移或重新整理
- 音樂格式轉換，例如 FLAC 改成 ALAC、WAV、MP3 或其他格式
- 在電腦、Mac、手機或 DAP 之間搬移播放清單
- DAP 只能讀到部分歌曲，或整份播放清單無法使用
- Roon 匯出的 M3U 使用相對路徑，無法直接在另一台電腦使用
- Roon 匯出的 XLSX 來自另一台電腦，原始絕對路徑已完全不同
- 想檢查程式自動修復了哪些歌曲，並在必要時手動更正

Playlist Fixer 不適合：

- 下載不存在的音樂檔案
- 編輯音樂標籤或 metadata
- 管理 Spotify、Apple Music 等串流平台的線上播放清單
- 找回已經不在任何音樂資料夾中的檔案
- 在沒有足夠檔名、路徑或標籤資訊時保證百分之百自動配對

---

## 2. 支援格式

### 2.1 支援的播放清單

- `.m3u`
- `.m3u8`
- Roon 匯出的 `.m3u`
- Roon 匯出的 `.xlsx`

Roon XLSX 會使用其中的歌名、藝人、專輯、碟號、曲號及原始路徑等資料進行配對。

Roon M3U 可能使用這類相對路徑：

```text
../Artist/Album/1-02 Song.flac
```

Playlist Fixer 會解析其中的藝人、專輯、碟號、曲號與檔名，而不是單純把它當成目前電腦上的真實路徑。

### 2.2 支援的音樂檔案

常見有損格式：

- MP3
- AAC
- OGG Vorbis
- Opus
- MP4／M4A 音訊

無損與未壓縮格式：

- FLAC
- ALAC
- M4A
- WAV
- AIF
- AIFF
- AIFC
- APE
- WavPack（WV）

DSD：

- DSF
- DFF（盡力支援）

> 實際自動修復效果會依音樂檔案中可取得的標籤、檔名、時長與資料夾資訊而有所不同。  
> FLAC、MP3、M4A 等常見格式通常能提供較完整資訊；WAV、部分 AIFF、DSF、DFF、APE 或 WV 的標籤完整度可能因檔案而異。

---

## 3. 介面區域說明

### Music Roots

Music Roots 是 Playlist Fixer 已建立索引的音樂資料夾清單。

每個路徑前方都有核取方塊。

核取方塊控制：

> Repair 可以從哪些 Music Roots 尋找及使用音樂檔案。

這個範圍也適用於原播放清單中仍然存在的舊路徑。若舊路徑不在目前勾選的 Music Roots 中，Repair 不會直接保留該路徑，而會只在已勾選的範圍內重新尋找。

核取方塊不控制掃描，也不會刪除既有索引。

Music Roots 清單會依 Windows 使用者與電腦分開保存。重新啟動程式，或外接硬碟暫時未連接時，路徑仍會保留；只有使用 `Remove Selected` 或 `Clear All` 才會移除。

把程式資料夾搬到另一台電腦時，不會自動帶入上一台電腦的 Music Roots。程式資料夾內的舊索引也不會自行新增路徑到目前電腦的清單。

Music Roots 與下方歌曲清單之間的分隔線可以拖曳，用來調整路徑清單的顯示高度。

### Add Music Folders

新增一個或多個包含音樂檔案的資料夾。

每次會開啟 Windows 原生資料夾選擇視窗。選完一個資料夾後，可繼續加入其他資料夾；已存在的路徑不會重複新增。

Music Root 可能顯示以下狀態：

- `[Pending scan]`：剛加入，尚未建立索引
- `[Index missing]`：路徑仍存在，但索引資料遺失或尚未建立
- `[Unavailable]`：資料夾或外接硬碟目前不存在

剛加入、尚未掃描的資料夾會顯示：

```text
[Pending scan]
```

### Scan New Folders

只掃描新加入、仍標記為 `[Pending scan]` 的資料夾。

已建立索引的舊資料夾不會重新掃描，因此新增少量音樂時，不需要重新掃描整個大型音樂庫。

### Rescan Selected

重新掃描目前反白選取的既有 Music Root。

適合以下情況：

- 該資料夾新增了很多歌曲
- 刪除或搬移了歌曲
- 標籤或檔名被修改
- 想重新建立該資料夾的索引

其他 Music Roots 不受影響。

### Remove Selected

從 Music Roots 清單及索引中移除目前選取的路徑。

取消核取方塊不等於刪除；只有使用 Remove Selected 才會真正移除。

### Import Playlist(s)

匯入要修復的播放清單。

目前建議一次處理一份播放清單，完成並儲存後再匯入下一份，避免混淆不同歌單的暫存狀態。

### Repair (Safe)

分析目前播放清單，並嘗試為每一首歌曲尋找正確檔案。

第一次執行 Repair 時會直接開始。若同一份歌單已經執行過 Repair，再次按下 `Repair (Safe)` 時會先要求確認。

確認重新 Repair 後，程式會清除本次尚未儲存的 Repair 結果與 `✓` 手動修改，並依目前勾選的 Music Roots 從頭重新分析。已經儲存到磁碟的舊輸出檔不會被刪除。

Repair 不會直接覆蓋原歌單，也不會在未儲存時正式寫入修復進度。

### View：Unresolved／Resolved

- **Unresolved**：尚未 Repair、候選不明確、找不到檔案，或已手動修正但尚未 Save 的歌曲
- **Resolved**：已保留、已自動修復，或已正式儲存手動選擇的歌曲

Unresolved 會將 Ambiguous 與 Failed 顯示在同一張表格中：

- `△`：Ambiguous，找到可能候選，但需要人工確認
- `✕`：Failed，沒有找到可靠候選，需要使用 Browse 手動尋找
- `✓`：已手動修正，但尚未 Save

預設會先顯示 `△`，再顯示 `✕`。按下 Apply 後，歌曲會在原本的位置改為 `✓`，不會立即移到 Resolved；按下 Save 後才正式移動。

Resolved 不只是完成清單，也是一個檢查區。若程式自動選錯，仍可在此重新指定正確檔案。Resolved 中的手動修改在 Save 前也會暫時顯示 `✓`。

### Candidates

顯示目前歌曲可能對應的候選檔案。

### Browse

當程式找不到可靠候選時，可自行選擇正確音樂檔。

### Apply

套用目前選擇。

在 Unresolved 中按下 Apply 後，該列會在原本位置顯示 `✓`，但不會立即移到 Resolved。

在 Resolved 中重新修改後，該列也會暫時顯示 `✓`。

這些內容在按下 Save 之前仍屬於本次工作階段的暫存狀態。

### Save Fixed Playlist

建立修復後的播放清單，並保存目前進度。

---

## 4. Music Roots 的正確使用方式

### 4.1 第一次建立音樂索引

1. 按下 `Add Music Folders`
2. 選擇包含音樂檔案的資料夾
3. 需要時繼續加入其他資料夾
4. 新路徑會顯示 `[Pending scan]`
5. 按下 `Scan New Folders`
6. 掃描成功後，該路徑會成為正式 Music Root

新加入的路徑會保存於 Music Roots 清單中。即使資料夾暫時不存在、外接硬碟尚未連接、無法讀取，或掃描結果為 0，路徑也不會自動消失。

若路徑存在但索引資料遺失，會顯示 `[Index missing]`；若路徑本身目前無法存取，會顯示 `[Unavailable]`。

### 4.2 之後新增另一個音樂資料夾

例如原本已有：

```text
C:\Music
D:\Lossless
```

後來新增：

```text
E:\New Music
```

只需要：

1. Add Music Folders
2. 選擇 `E:\New Music`
3. 按 `Scan New Folders`

程式只會掃描新資料夾，不會重新掃描原本的 `C:\Music` 與 `D:\Lossless`。

### 4.3 更新既有音樂資料夾

若 `C:\Music` 的內容發生變化：

1. 在 Music Roots 清單中反白 `C:\Music`
2. 按 `Rescan Selected`
3. 確認重新掃描

只有該資料夾會更新。

### 4.4 選擇 Repair 搜尋範圍

例如你同時有：

```text
☑ C:\PC Music
☐ D:\DAP Music
```

Repair 只會從 `C:\PC Music` 尋找及使用檔案。

`D:\DAP Music` 仍保留在索引中，只是本次 Repair 不會使用它。即使原播放清單中的某個 `D:\DAP Music` 路徑目前仍存在，只要該 Music Root 沒有勾選，Repair 也不會直接保留那個路徑。

若勾選的 Music Root 顯示 `[Index missing]` 或 `[Unavailable]`，Repair 會先提示，避免使用者誤以為該路徑已可正常搜尋。

這可以避免：

- 修復電腦歌單時誤選到 DAP 檔案
- 修復 DAP 歌單時誤選到電腦版本
- 同一首歌曲在不同裝置中有多份副本而造成混淆

---

## 5. 匯入播放清單

按下 `Import Playlist(s)` 後，選擇：

- M3U
- M3U8
- Roon M3U
- Roon XLSX

匯入成功後，歌單中的歌曲會立即顯示在 Unresolved。

尚未執行 Repair 時，每一首會標記：

```text
[NOT REPAIRED]
```

這只代表尚未分析，不代表歌曲有問題。

### 一般 M3U／M3U8

Playlist Fixer 會使用可取得的資訊，例如：

- 原始路徑
- `#EXTINF`
- 歌名
- 藝人
- 檔名
- 時長
- 音樂標籤
- 資料夾結構

### Roon XLSX

Roon XLSX 可包含：

- Album Artist
- Track Artist
- Album
- Disc number
- Track number
- Title
- External ID
- Path

即使 XLSX 來自另一台電腦、原始磁碟代號和資料夾結構不同，Playlist Fixer 仍會嘗試使用 metadata 與目前音樂索引進行配對。

Roon XLSX 修復後會輸出為標準 M3U。輸出時會利用 XLSX 中可靠的 Track Artist、Album Artist 與 Title 建立 `#EXTINF`，避免修復後的歌單只剩路徑而失去一般 M3U 所需的歌曲資訊。若無法取得時長，會使用 `-1`；一般播放器仍可正常讀取。

### Roon M3U

Roon M3U 常見特徵包括：

- 相對路徑
- `/` 分隔符號
- 沒有 `#EXTINF`
- 檔名包含碟號與曲號
- Roon 重新整理過的資料夾名稱

Playlist Fixer 會先拆解 Roon 路徑，再進行配對。

---

## 6. 執行 Repair

按下 `Repair (Safe)` 後，Playlist Fixer 會依序嘗試：

1. 原始路徑是否仍然有效
2. 路徑尾端或資料夾結構是否相符
3. 檔名與時長是否相符
4. 歌名、藝人、專輯是否相符
5. 碟號與曲號是否相符
6. Roon XLSX metadata 是否能對應本機標籤
7. Roon M3U 的路徑結構是否能對應本機索引
8. 多項資訊的綜合信心評分

為避免修錯，程式不會只因歌名相同就強行自動選擇。

若兩個候選太接近，會保留在 Ambiguous，交由使用者確認。

---

## 7. Repair 狀態說明

Repair 後，歌曲可能出現以下狀態：

### Kept original

原始路徑目前仍然有效，而且位於已勾選的 Music Roots 範圍內，因此不需要修改。

### Auto repaired

程式找到高信心且明顯唯一的候選，已自動重新連結。

### Manual selection

使用者已自行選擇正確檔案。

### Ambiguous（`△`）

找到一個或多個合理候選，但無法安全判斷哪一個正確，需要使用者確認。

### Failed（`✕`）

沒有找到足夠可靠的候選，需要使用 Browse 手動尋找正確檔案。

### Manually fixed, not saved（`✓`）

使用者已經套用手動選擇，但尚未 Save。這是暫存狀態。

---

## 8. Unresolved 與 Resolved

### Unresolved

包含：

- 尚未 Repair 的歌曲
- `△` Ambiguous
- `✕` Failed
- 尚未套用選擇的歌曲
- 已手動修正但尚未 Save 的 `✓` 歌曲

Ambiguous 與 Failed 會顯示在同一張表格中，預設以 `△` 為優先，再顯示 `✕`。

按下 Apply 後，歌曲會留在原本位置並改為 `✓`，避免清單跳動。按下 Save 後，`✓` 歌曲才會正式移到 Resolved。

### Resolved

包含：

- Kept original
- Auto repaired
- 已正式儲存的 Manual selection

Resolved 仍可以重新修改。修改後會暫時顯示 `✓`，Save 後記號消失。

例如自動配對到錯誤版本：

- Live 版與錄音室版混淆
- Remaster 與原版混淆
- 同名歌曲
- 同一首歌的不同專輯版本
- 不同格式或不同取樣率版本

可以在 Resolved 選取該歌曲，重新選擇候選或 Browse 正確檔案，再按 Apply。

---

## 9. 手動處理 Ambiguous

1. 在 Unresolved 中選取帶有 `△` 的 Ambiguous 項目
2. 查看 Candidates
3. 選擇正確檔案
4. 按下 Apply
5. 該歌曲會留在原本位置，狀態改為 `✓`
6. 按下 `Save Fixed Playlist` 後，才正式移至 Resolved

請特別檢查：

- 藝人
- 專輯
- 曲名
- 曲號
- Live／Remaster／Deluxe 等版本差異
- 檔案所在 Music Root

---

## 10. 手動處理 Failed

1. 在 Unresolved 中選取帶有 `✕` 的 Failed 項目
2. 按下 Browse
3. 手動尋找並選擇正確音樂檔
4. 按下 Apply
5. 該歌曲會留在原本位置，狀態改為 `✓`
6. 按下 `Save Fixed Playlist` 後，才正式移至 Resolved

若音樂檔案實際上不存在，則無法修復。

---

## 11. 暫存狀態與正式進度

這是 Playlist Fixer 的重要安全設計。

### Repair 只是暫存分析

按下 Repair 後：

- 自動修復結果會顯示
- Ambiguous 會標記為 `△`
- Failed 會標記為 `✕`
- 手動 Apply 後會標記為 `✓`
- `✓` 會保留在原本位置
- 但尚未形成正式進度

若在沒有 Save 的情況下離開該歌單，再重新匯入原始歌單，程式會把它視為未正式修復。

若再次執行 Repair 並確認重新掃描，目前畫面會進入一套新的暫存結果；舊的已儲存進度不會混入新的 Unresolved／Resolved 顯示。只有再次 Save 後，新的結果才成為目前正式進度。

### Save 才會建立正式進度

按下 `Save Fixed Playlist` 後：

- 產生新的修復播放清單
- 保存 Repair 報告
- 保存手動選擇
- 保存尚未完成的修復進度
- Unresolved 中的 `✓` 項目正式移到 Resolved
- Resolved 中未儲存的 `✓` 記號消失
- 下次可以繼續處理

### 原始歌單與修復歌單分開記錄

例如：

```text
1.m3u
fixed_1_selected.m3u
```

兩者不會因名稱相近而共用狀態。

- 開啟原始 `1.m3u`：視為原始未修復歌單
- 開啟已儲存的 `fixed_1_selected.m3u`：讀取正式修復進度

---

## 12. 儲存修復後的播放清單

按下 `Save Fixed Playlist` 後，程式會建立：

```text
fixed_*_selected.m3u
```

原始播放清單不會被覆蓋。

Roon XLSX 修復後也會輸出為 M3U。

即使歌單尚未全部修完，也可以先 Save。下次重新開啟已儲存的修復歌單後，可繼續處理剩餘項目。

---

## 13. 報告與進度檔案

Playlist Fixer 會建立修復報告與進度資料，例如：

### repair_report_*.csv

記錄每一首歌曲的分析與配對結果。

可能包含：

- 原始歌曲資訊
- 狀態
- 選定路徑
- 候選資訊
- 配對理由
- Roon metadata 配對分數

### selections_*.json

保存手動選擇。

### 修復進度資料

保存已正式儲存的處理狀態，讓未完成的長歌單可以在下次繼續。

### fixed_*_selected.m3u

最終輸出的修復播放清單。

> 不要任意刪除報告或進度檔案，否則已保存的處理進度可能遺失。

---

## 14. 常見問題

### 為什麼 Add Music Folders 後還顯示 Pending scan？

因為尚未建立索引。按下 `Scan New Folders` 後，掃描成功才會成為正式 Music Root。

### Scan New Folders 會重新掃描所有歌曲嗎？

不會。它只掃描新加入、仍為 Pending 的資料夾。

### 什麼時候需要 Rescan Selected？

既有資料夾內容、檔名、標籤或歌曲數量發生變化時。

### 取消 Music Root 的勾選會刪除資料嗎？

不會。只會讓 Repair 暫時不使用該音樂庫，也不會保留該範圍內的原始路徑。

### 為什麼原播放清單中的路徑明明存在，Repair 還是改用其他位置？

因為該原始路徑不在目前勾選的 Music Roots 中。Repair 只會使用勾選範圍內的檔案。

### 為什麼外接硬碟未連接時，Music Roots 路徑仍然存在？

Music Roots 清單會依目前 Windows 使用者與電腦分開保存。外接硬碟暫時離線不會刪除設定；只有使用 `Remove Selected` 或 `Clear All` 才會移除。

### 把程式搬到另一台電腦時，為什麼不會顯示上一台電腦的 Music Roots？

Music Roots 是每台電腦各自保存的設定。程式資料夾裡的索引只用來判斷目前已設定路徑的索引狀態，不會自動把上一台電腦的路徑加入目前清單。

### 為什麼匯入後所有歌曲都在 Unresolved？

因為尚未 Repair。這時狀態是 `Not repaired`，不代表歌曲修復失敗。

### 為什麼有些歌曲沒有自動修復？

可能原因：

- 有多個接近候選
- 標籤不足
- 同名歌曲太多
- Live／Remaster 等版本難以區分
- 原始歌單資訊太少
- 音樂檔案不在任何已建立索引的 Music Root 中
- 正確 Music Root 沒有勾選為 Repair 範圍

### 可以修復另一台電腦匯出的 Roon XLSX 嗎？

可以。Playlist Fixer 會使用 Roon XLSX 的 metadata，而不只依賴原始絕對路徑。

但若音樂標籤缺失、歌曲版本太多或資料差異太大，仍可能需要人工確認。

### 為什麼 Apply 後歌曲沒有立刻移到 Resolved？

因為 Apply 只代表已套用暫存修改。歌曲會顯示 `✓` 並留在原本位置，按下 Save 後才正式移到 Resolved。

### 為什麼再次按 Repair (Safe) 會跳出確認？

再次 Repair 會清除本次尚未儲存的自動結果與 `✓` 手動修改，並使用目前勾選的 Music Roots 從頭重新分析，因此程式會先要求確認。已經儲存的舊輸出檔不會被刪除。

### 為什麼 Repair 後重新開啟又顯示未修復？

因為尚未 Save。Repair 結果在 Save 前只是暫存。

### 可以修到一半先儲存嗎？

可以。Save 後，下次可從已儲存的修復歌單繼續。

### Playlist Fixer 會修改原始音樂檔嗎？

不會。

### Playlist Fixer 會覆蓋原始播放清單嗎？

不會。它會建立新的 `fixed_*_selected.m3u`。

### 是否需要網路？

不需要。所有掃描與修復都在本機執行。

---

## 15. 問題回報

若遇到問題，請提供：

- Playlist Fixer 版本
- 作業系統版本
- 原始播放清單
- Roon XLSX 或 Roon M3U（若問題與 Roon 有關）
- 對應的 repair report
- selections 檔案（若存在）
- 問題畫面截圖
- 問題發生在 Import、Repair、Apply 或 Save 哪一階段
- 預期結果
- 實際結果
- 當時哪些 Music Roots 有勾選

不需要提供：

- 整個音樂資料庫
- 大量音樂檔
- 私人音樂內容

必要時可提供少量、可公開的測試檔案與對應歌單。

---

## 16. 安全與隱私

Playlist Fixer：

- 不修改音樂檔案
- 不覆蓋原始播放清單
- 不會下載或上傳音樂
- 不需要網路
- 所有處理都在本機完成
- 無廣告
- 無付費牆

---

## 17. 使用建議

首次使用或處理重要歌單時，建議：

1. 保留原始播放清單備份
2. 先用較小的測試歌單確認 Music Roots
3. Repair 後檢查 Unresolved 與 Resolved
4. 優先處理 `△` Ambiguous，再處理需要手動尋找的 `✕` Failed
5. 對 Ambiguous 不要只看檔名
6. 儲存前確認 `✓` 項目
7. Save 後先在播放器中測試新歌單
8. 確認無誤後再處理大型歌單

---

Playlist Fixer 的設計核心是：

- 安全：不進行破壞性操作
- 透明：修復結果可檢查
- 可復原：手動選擇與進度可保存
- 跨環境：處理換電腦、換路徑、換格式與不同裝置

它只為了一件事而存在：

> 保護你多年累積下來的播放清單。
