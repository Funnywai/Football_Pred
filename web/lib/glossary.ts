// Plain-language Traditional Chinese (Taiwan) explanations for every term the dashboard
// exposes. Each entry answers three questions: what the term is, what a good reading looks
// like, and what a bad reading looks like. The copy is deliberately short so it fits in the
// compact TermTip popover without turning into a paragraph.

export interface GlossaryEntry {
  label: string;
  what: string;
  good: string;
  bad: string;
}

export const GLOSSARY = {
  edge: {
    label: "Edge（優勢）",
    what: "模型機率 − 去水市場機率。",
    good: "正值代表模型認為市場低估；+2% 以上才算 candidate（但小樣本不可信）。",
    bad: "0 或負值代表沒有優勢；越大不代表一定贏。",
  },
  signal: {
    label: "Signal（訊號價）",
    what: "開賽前 48 小時的市場價，是模型決策的參考價，不是預測結果。",
    good: "與 execution 比較可看執行品質。",
    bad: "不能當成盈利指標。",
  },
  execution: {
    label: "Execution（執行價）",
    what: "實際下注拿到的賠率（開賽前最後一筆 HKJC HAD）。",
    good: "back bet 越高越好。",
    bad: "越低越差；比 signal 低代表價格走反。",
  },
  delta_abs: {
    label: "Δ abs（絕對差）",
    what: "execution − signal 的絕對差。",
    good: "正值（綠色）代表拿到更好的價。",
    bad: "負值（紅色）代表對我們不利。",
  },
  delta_pct: {
    label: "Δ %（百分比差）",
    what: "execution − signal 的百分比差。",
    good: "正值（綠色）代表拿到更好的價。",
    bad: "負值（紅色）代表對我們不利。",
  },
  prob: {
    label: "Prob（模型機率）",
    what: "模型預測機率。",
    good: "校準良好且與市場有差距才有用。",
    bad: "不是保證；單場結果是隨機的。",
  },
  implied_prob: {
    label: "Implied（隱含機率）",
    what: "去水後的市場隱含機率（不是 1/賠率）。",
    good: "與 prob 比較可看 edge。",
    bad: "含抽水時不可直接比較。",
  },
  fair_odds: {
    label: "Fair odds（公平賠率）",
    what: "1 / 模型機率，理論公平賠率。",
    good: "用來檢查市場價是否高於公平價。",
    bad: "不是可下注價。",
  },
  market_odds: {
    label: "Market odds（市場賠率）",
    what: "實際可下注賠率。",
    good: "越高越好。",
    bad: "越低越差；NULL = 沒有市場先驗，不能下注。",
  },
  recommended_fraction: {
    label: "Recommended fraction（建議比例）",
    what: "半凱利建議下注比例。",
    good: "越大代表模型優勢越大。",
    bad: "不代表一定贏；過大可能是模型過度自信。",
  },
  stake: {
    label: "Stake（注碼）",
    what: "實際注碼（HKD）。",
    good: "控制在 bankroll 的固定比例。",
    bad: "過大增加破產風險。",
  },
  payout: {
    label: "Payout（派彩）",
    what: "派彩金額。",
    good: "正數。",
    bad: "負數；單場波動很大。",
  },
  profit: {
    label: "Profit（淨利）",
    what: "淨利（派彩 − 注碼）。",
    good: "正數。",
    bad: "負數；單場波動很大。",
  },
  status: {
    label: "Status（狀態）",
    what: "注單狀態：won / lost / push。",
    good: "won。",
    bad: "lost；push 是退本金。",
  },
  model: {
    label: "Model（模型版本）",
    what: "模型版本（champion / challenger）。",
    good: "看 champion 的表現。",
    bad: "challenger 的數字不能當現行表現。",
  },
  clv_mean_edge: {
    label: "CLV mean edge（平均 CLV 優勢）",
    what: "模型機率 − 收盤去水機率（只算已選注）。",
    good: "正值且樣本大。",
    bad: "接近 0 或負值；clv_mean_edge 在全部 outcome 上結構性接近 0，不能單獨看。",
  },
  clv_fraction: {
    label: "CLV fraction（打敗收盤比例）",
    what: "打敗收盤的比例。",
    good: "≥52–53% 且 95% CI 排除 50%。",
    bad: "≤50% 或 CI 包含 50% = 沒有證據。",
  },
  clv_n: {
    label: "CLV n（觀察值數量）",
    what: "CLV 觀察值數量（不是注數）。",
    good: "200–500 才算初步可信，1000+ 更強。",
    bad: "<100 幾乎是雜訊。",
  },
  brier: {
    label: "Brier（Brier score）",
    what: "機率預測的均方誤差，越低越好。",
    good: "低於市場 baseline。",
    bad: "高於市場 baseline 代表模型更差。",
  },
  logloss: {
    label: "Log loss（對數損失）",
    what: "對數損失，越低越好。",
    good: "低於市場 baseline。",
    bad: "高於市場 baseline。",
  },
  roi: {
    label: "ROI（投資報酬率）",
    what: "已結算淨利 / 已結算注碼。",
    good: "正值且樣本大。",
    bad: "負值；短期 ROI 是雜訊。",
  },
  yield_pct: {
    label: "Yield（收益率）",
    what: "淨利 / 總注碼。",
    good: "正值。",
    bad: "負值。",
  },
  bankroll: {
    label: "Bankroll（本金）",
    what: "初始本金 + 已實現利潤 − 未結算注碼。",
    good: "穩定上升。",
    bad: "下降或波動過大。",
  },
  open_stakes: {
    label: "Open stakes（未結算注碼）",
    what: "尚未結算的注碼。",
    good: "佔 bankroll 比例可控。",
    bad: "過高代表暴露風險。",
  },
  win_rate: {
    label: "Win rate（勝率）",
    what: "已結算注單的勝率。",
    good: "高，但要配合賠率看。",
    bad: "低；高勝率也可能虧錢（低賠率）。",
  },
  kelly_multiplier: {
    label: "Kelly multiplier（凱利乘數）",
    what: "凱利比例乘數。",
    good: "保守（例如 0.5）。",
    bad: "過高會放大回撤。",
  },
  bets: {
    label: "Bets（注單數）",
    what: "已下注的注單總數。",
    good: "樣本越大越可信。",
    bad: "樣本太小不能判斷表現。",
  },
  settled: {
    label: "Settled（已結算）",
    what: "已結算的注單數。",
    good: "越多越能反映真實表現。",
    bad: "未結算的注單不計入 ROI。",
  },
  ingest: {
    label: "INGEST（資料匯入）",
    what: "抓取賽程、賠率與結果，寫入資料庫。",
    good: "最新資料時間持續更新。",
    bad: "資料過期或抓取失敗，後續階段會用到舊資料。",
  },
  features: {
    label: "FEATURES（特徵）",
    what: "把原始資料整理成模型可用的特徵。",
    good: "特徵時間新鮮且完整。",
    bad: "特徵過期或缺漏，預測品質會下降。",
  },
  predict: {
    label: "PREDICT（預測）",
    what: "用 champion 模型產生機率與 edge。",
    good: "預測持續更新且模型版本正確。",
    bad: "預測失敗或過期，投注決策會失去依據。",
  },
  bet: {
    label: "BET（下注）",
    what: "依模型建議與資金規則建立注單。",
    good: "注碼符合 bankroll 比例。",
    bad: "注碼過大或重複下注，風險會放大。",
  },
  settle: {
    label: "SETTLE（結算）",
    what: "依比賽結果結算注單與損益。",
    good: "結算及時且結果正確。",
    bad: "延遲結算會讓 bankroll 與 ROI 暫時失真。",
  },
  retrain: {
    label: "RETRAIN（重新訓練）",
    what: "用新資料重新訓練並評估模型。",
    good: "challenger 通過驗證後才晉升 champion。",
    bad: "未驗證就上線，可能讓模型表現變差。",
  },
} as const satisfies Record<string, GlossaryEntry>;

export type GlossaryKey = keyof typeof GLOSSARY;
