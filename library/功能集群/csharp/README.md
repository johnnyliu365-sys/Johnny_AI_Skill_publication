# C# 其他功能集群

此目錄保存與 Unity 無關的純 C# 領域規則能力。遊戲 UI、場景、資產與建置流程不屬於此目錄的範圍。

## 責任

- 建立 `card_rules_engine/`，以 record、enum 與明確動作驗證實作通用回合制規則。
- 建立 `camouflage_state/`，以純狀態機處理套色、匹配、衰退與捕獲結果。

## 來源追溯

參考 PoliticsCardGame 的純規則核心與 CamouflageHideSeek 的 `CamouflageState`；僅重建可獨立驗證的邏輯。

## 禁止用途

- 不得修改或搬移任何 來源專案B 的 C#、Unity 場景、資產、套件、專案設定或建置產物。
- 不得引入 Unity `MonoBehaviour`、輸入、畫面、網路或遊戲題材資料。
- 不得將遊戲內資源、分數或狀態表示為金流、帳本或使用者權限。
