# 模型選注修正設計（Model Value Repair）

- **狀態：提案（未實作、未核准）**
- 日期：2026-10-16
- 範圍：`app/ml/*`、`app/config.py`。**不含**前端。**不含**帳本邏輯（`app/services/ledger.py` 的 `place_bets` 不需改動，理由見 §4）。
- 前置：本檔所有數字皆來自 2026-10-16 的樣本外後測，重現方式見附錄 A。

## 1. 問題陳述

現行選注規則 `model_prob − 去水市場機率 > ml_value_edge_threshold (0.02)`（`app/ml/predict.py:99–102`）
在**樣本外**（2023-04-27 ~ 2026-10-14，5,833 場）於**所有**測試配置下皆為負期望值。

根本原因有三，皆已用實測確認為**首要**：

1. **isotonic 校準層在破壞機率**（`app/ml/models.py:99 _fit_isotonic_multiclass` → `:160`）。
   實測：讓 logloss 由 **0.96990 → 0.98355**（**+0.0137**）。
2. **模型對市場的邊際資訊很小**（約 **40%** 係數佔比），**最多只能打平市場**。
3. **晉升閘門只看 Brier**（`app/ml/registry.py:48 gate_passes`），
   而 Brier 對 tails（長賠率和局）不敏感 → **系統性地偏好對投注更差的配置**。

> 補充更正：`place_bets`（`app/services/ledger.py:286–292`）**已經**在執行價上以
> `kelly_fraction(p, odds) > 0`（等價 `p × odds > 1`）過濾，因此**並非**忽略 vig；
> 真正的問題是**沒有安全邊際**（在損益兩平點上即下注）。

## 2. 證據（2026-10-16 樣本外後測）

### 2.1 技能（eval n=5,833；base rates H 43.61% / D 25.34% / A 31.05%）

| 配置 | Logloss | Brier |
|---|---|---|
| 部署現況（IsotonicRegression ×3） | 0.98355 | 0.57545 |
| 原始 LightGBM softmax | 0.96990 | 0.57579 |
| 溫度縮放 T=1.023（於 calibration 擬合） | 0.97013 | 0.57593 |
| **市場（去水）** | **0.96402** | **0.57305** |
| stacker（僅市場） | 0.96403 | 0.57302 |
| stacker（僅模型） | 0.96597 | 0.57382 |
| **stacker（模型＋市場）** | 0.96422 | **0.57290** |
| blend w=0.20（於 calibration 選出） | 0.96426 | 0.57302 |

係數佔比（stacker 模型＋市場）：**模型 39.9% / 市場 60.1%** → 模型有邊際訊號，但不足以勝過市場。

### 2.2 訓練/校準/評估切分與 market prior 覆蓋

| 分割 | 筆數 | 有 prior | 無 prior |
|---|---|---|---|
| train | 20,416 | 16,760（82.1%） | 3,656 |
| calibration | 2,916 | 2,916（100%） | 0 |
| eval | 5,833 | 5,818（99.7%） | 15 |

→ **推翻**「market 特徵 56% 缺失稀釋樹結構」的假設：缺失幾乎不在 train/eval 的評估面上。

### 2.3 和局校準（依模型的和局機率分格）

| 分格 | n | 模型 | 市場 | 實際 |
|---|---|---|---|---|
| [0.16,0.18) | 854 | 0.1738 | 0.1892 | **0.1780** |
| [0.30,0.40) | 1165 | 0.3206 | 0.2966 | **0.2815** |

→ 中段模型較準；**高段模型高估 +3.9pp**（市場較準）。全體平均和局機率 0.2504 vs 實際 0.2534 → **無全局和局偏差**。

### 2.4 經濟性（flat 1u；訊號 = devig(B365 open)；規則 edge > 0.02）

| 配置 | exec=OPEN（極早鳥） | exec=CLOSE（≈實盤 HKJC 48h） |
|---|---|---|
| 現況 isotonic \| D | −2.45%（n=1726） | **−3.86%（n=1726）** |
| 現況 isotonic \| ALL | −0.72% | −2.97% |
| 原始 LightGBM \| D | −5.90% | −7.90% |
| 原始 LightGBM \| ALL | −3.81% | −6.38% |
| **blend w=0.20 \| D** | **+6.79%（n=691）** | −0.69% |
| **blend w=0.20 \| ALL** | **+4.30%（n=3079）** | −3.40% |
| blend + vig-aware（p×price>1.03）\| D | +3.92%（n=506） | +4.19%（n=26） |
| blend + vig-aware \| ALL | +5.95%（n=1728） | +1.01%（n=75） |

規則觸發的長賠率和局（close 6.0–7.5，n=118）：實際和局 **12.7%**、模型 17.8%、市場 14.2%、
平均賠率 6.70、打平點 14.9% → **flat ROI −16.3%**。

**統計顯著性**：flat ROI 的標準誤粗估 n=3079 → ±3.6pp、n=1728 → ±4.8pp、n=691 → ±9.1pp
→ **無一達到顯著（t ≈ 1.2）**。

## 3. 目標與非目標

- **目標**：停止確定的虧損；讓量測變誠實（CLV 可量）。
- **非目標**：不追求打敗 B365 收盤價（零售資料粒度下不現實）。
- **預期上限**：修好後為「打平到小賺，且統計上不顯著」。

## 4. 改動設計（C1–C6）

| # | 位置 | 內容 |
|---|---|---|
| C1 | `app/ml/models.py:160`（`train_1x2`）／`:99`（`_fit_isotonic_multiclass`） | isotonic → **溫度縮放**（單參數 T，於 calibration 擬合）；或直接停用校準 |
| C2 | `app/ml/predict.py`（`build_prediction_rows`） | 新增 **blend**（logit 空間，§5.1），結果寫入 `Prediction.prob` |
| C3 | `app/ml/predict.py:99–102`（`_rows_for`） | edge／fraction 改用 blended prob；新增 **buffer** 條件（§5.3） |
| C4 | `app/ml/registry.py:48`（`gate_passes`） | Brier-only → **多指標**（§6） |
| C5 | `app/config.py` | 新增 `ml_blend_weight`（float，預設 0.20）、`ml_exec_edge_buffer`（float，預設 0.03） |
| C6 | `app/ml/jobs.py:98,131` | gate 評估納入 **ECE** 與**經濟回測**（CLV 已由 `clv_metrics` 提供，但冠軍目前為 `null`） |

**為何 `place_bets` 不需改動**：該函式已以 `prediction.prob` 在**執行價**重算
`kelly_fraction`（`ledger.py:286`），故只要 C2/C3 讓 `Prediction.prob` 變成 blended prob，
帳本即自動採用新機率。改動面積因此維持在 `app/ml/*` 與 `app/config.py`。

## 5. 公式

### 5.1 Blend（logit 空間）

```
ℓ_model = log(p_model)            # 3-vector [H, D, A]
ℓ_prior = log(p_prior_devig)      # 來自 MarketPrior.had_probs
ℓ_blend = w · ℓ_model + (1 − w) · ℓ_prior
p_blend = softmax(ℓ_blend)        # 需重新 normalize
```

- 選 logit 空間而非機率空間：機率空間的線性混合在 3-class simplex 上不對稱；
  logit 混合等價於幾何平均（兩個獨立證據的對數合成）。
- `prior` 缺失時：`w = 1`（純模型）。

### 5.2 `w` 的估法（**不得在 eval 上調**）

1. 在 **calibration 窗**（2,916 筆）以**最小化 logloss** 掃 `w ∈ [0,1]`（step 0.05）。
2. 已測最優 **w ≈ 0.20**（cal logloss 0.97937）。
3. **加嚴**：於 calibration 內做 walk-forward（前半選 `w`、後半驗證），確認非單窗偶然。
4. eval 只允許看一次。

### 5.3 安全邊際

`is_value` 呼叫點新增第二條件：

```
edge = p_blend − prior_devig  >  ml_value_edge_threshold   (既有)
AND  p_blend × market_odds    >  1.0 + ml_exec_edge_buffer (新增；buffer 建議 0.03)
```

## 6. Gate 新規則（`gate_passes`）

現況只比 `brier`。改為**全部條件皆須成立**：

| 指標 | 要求 |
|---|---|
| `logloss` | challenger < champion（**同一 eval 窗重算**，`jobs.py:98 _fresh_champion_metrics` 已備） |
| `brier` | challenger ≤ champion（保留現有 margin） |
| `ECE`（新） | challenger ≤ champion（10 分格） |
| `clv_mean_edge` | challenger ≥ champion **且 > 0** |
| 經濟回測（新） | 於 eval 上在**可執行價** ROI ≥ 0 |

理由：Brier 被熱門主導、對 tails 不敏感，已實測會選出對投注更差的配置。

## 7. 紙上驗證計畫與通過關卡

1. 維持 `LEDGER_ENABLE=false`（只停帳本；`ml_predict` 照常運作）。
2. 用真實 upcoming 預測累積紀錄：`p_blend`、當時市場價、實際結果。
3. **通過關卡（才可重開帳本）**：
   - 樣本 ≥ **200–500** 筆；
   - **CLV mean edge > 0**（主要 KPI；小樣本 ROI 為雜訊，SE ±4–9pp）；
   - 在**含 vig 的實際價格**下 ROI ≥ 0。
4. **停止規則**：200–500 筆後 CLV ≤ 0 → 結論「此資料粒度打不敗市場」，改為只做 CLV 監控。

## 8. 測試計畫

- **blend**：`w=0` → 等於 prior；`w=1` → 等於模型；中間 → 幾何平均；prior 缺失 → `w=1`。
- **buffer**：`p × odds ≤ 1.03` 必須被擋下。
- **校準**：溫度縮放的 logloss 不劣於 isotonic（或停用）。
- **gate**：ECE／CLV／ROI 各自能獨立擋下 challenger。
- **回歸鎖定**：`tests/test_ledger.py` 的 stake 與執行價行為不變。

## 9. 風險與限制

- `w=0.20` 以 calibration 選出，但最終 **ROI 不顯著**（t ≈ 1.2）→ 預期最好「打平到小賺」。
- 後測使用 B365 open/close，**與實盤 HKJC 價格不同** → 數字為方向性。
- **不可將修正版視為「會賺錢」**：其作用是**停止確定虧損**＋**讓量測誠實**。
- B365 的 `open` 是數週前初盤，實盤在 48h 前下注，故 **exec=CLOSE 欄較貼近實盤**（仍為負）。

## 10. 執行順序

1. **C5 ＋ C1**（設定＋校準；風險最小）
2. **C2 ＋ C3**（blend ＋ buffer；主要效果）
3. **C4 ＋ C6**（gate ＋ CLV；治理）
4. 紙上驗證（§7）

## 附錄 A：重現方式

後測以唯讀方式在 app 容器內執行（腳本經 stdin，未落地、未改 repo）：

```
echo <base64 的 python 腳本> | base64 -d | docker exec -i worldcup-app-1 python -
```

使用的程式入口（全部重用 app 自身）：
`app.ml.dataset.build_dataset`、`app.ml.jobs._fresh_champion_metrics`、
`app.ml.models.{load_artifact,predict_proba,evaluate_1x2}`、`app.ml.features.FEATURE_COLUMNS`、
`app.ml.registry.get_champion`、`app.services.ledger.ledger_update`（**未呼叫**）、
賠率來源 `odds_snapshots`（`source='football_data'`, `odds_type='HAD'`, payload `odds.B365.{open,close}`）。

## 附錄 B：已更正的先前錯誤結論

1. 「此注 −12.2%、市場完美校準」→ 論證誤用**混合 5 大聯賽 pooled** 基準率（已更正方法）。
2. 「模型系統性偏向和局」→ **錯**：全體平均和局機率 0.2504 vs 實際 0.2534。
3. 「冠軍 `n:0` 故 Brier 不可信」→ **錯**：儲存的 0.57539 與樣本外實測 0.57545 幾乎相同 → Brier 為真，`n` 僅為記錄 bug。
4. 「移除 isotonic 是最高 ROI 修法」→ **錯**：它是 logloss 修法；實測原始輸出 ROI **更差**。
5. 「規則完全忽略 vig」→ **錯**：`place_bets` 已在執行價做 `kelly > 0`；真問題是**缺安全邊際**。

## 附錄 C：實作後修正與驗收發現（2026-10-16）

### C.1 `clv_mean_edge > 0` 是**不可能的條件** → 已移除（實作期間發現）
`clv_metrics` 對**每個 outcome** 取平均 edge；任何歸一化預測器對歸一化去水收盤，
每場 `Σmodel_prob = 1`、`Σclosing_prob = 1` → **每場 edge 總和恆為 0** → 平均恆為 0。
線上挑戰者的實際值 `clv_mean_edge = −1.9e-18` 即為明證。`> 0` 會**永遠擋掉所有晉升**、凍結註冊表。

**修正**：CLV 僅要求「不劣於冠軍」（含 `CLV_TOLERANCE = 1e-12` 浮點容差）；
「打敗收盤」的意圖改由 `roi >= 0`（真實逐注模擬）承擔。

### C.2 障礙盤凍結風險 → 已修正
`gate_passes` 原設計「任一側缺指標即 fail closed」，但**障礙盤從不產生** ece/clv/roi →
會**永久凍結障礙盤晉升**（原本 Brier-only 時可晉升）。**修正**：
- **強制**（缺 → fail closed）：`logloss`、`brier`
- **絕對**（挑戰者一有就套用）：`roi >= 0`
- **比較型**（僅當**兩側都有**才比較）：`ece`、`clv_mean_edge`

### C.3 驗收（真資料，新碼經唯讀 throwaway 容器執行）
| 項目 | 結果 |
|---|---|
| 現有冠軍 artifact | `temperature=None`（legacy isotonic）→ 走後向相容路徑 ✓ |
| `predict_proba`（legacy） | logloss 0.98355 ✓（與修正前一致 → 相容性成立 ✓） |
| blend w=0.20（在 isotonic 之上） | logloss **0.96562** / brier **0.57307** ✓（與離線預測 0.96426/0.57302 吻合 ✓）|
| `economic_backtest`（blend） | roi **+10.51%**、n_bets **239**（原規則 5294 注 ✗ → 砍 95% ✓）；roi 為**去水公平價**基準（會高估 ✓）|
| ece | blend 0.0141 ／ temperature-only **0.0082** |

### C.4 ⚠️ 未解：Brier 條件會擋掉本次修正（**需用戶決策**）
溫度模型 logloss **更好**（0.9701 vs 0.9836）但 Brier **略差**（0.5758 vs 0.57545）→
保留的 `brier < champion.brier − margin` 會**擋下溫度挑戰者**，使 isotonic 冠軍永久留任 ✗。
- **無需改碼的解法**：`ML_CHAMPION_MARGIN` 設 **−0.001**（需 < −0.00034）即可放行 ✓
- **建議的長期解**：將 Brier 降為「只記錄、不把關」——理由：本專案已**實測** Brier 會系統性選出
  對投注更差的配置（isotonic：Brier 較好、logloss 與和局尾部較差）。

### C.5 測試與 gate 狀態
- `uv run pytest -q` → **267 passed, 2 deselected** ✓；`uv run ruff check .` → **All checks passed** ✓
- 已移除實作期間為繞過 C.1 而加的 `clv_metrics` monkeypatch，整合測試回復誠實 ✓
- 已知非決定性 teardown 警告：`Event loop is closed`（全套 ~6 次出現 1 次 ✗、單檔與 tracemalloc 執行皆不出現 ✓、**不影響任何測試** ✓）
