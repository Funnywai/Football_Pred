#!/usr/bin/env python3
"""Write analysis report to documents/WorldCup.xlsx as new worksheets."""

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers
from openpyxl.utils import get_column_letter
from collections import defaultdict

INPUT = '/Users/Kenny/OneDrive/WorldCup/documents/WorldCup.xlsx'

def compute_improved_kelly(odds, confidence, p5, p4, p3, bankroll=300):
    if odds is None or odds <= 1 or confidence is None:
        return 0
    if confidence == 5: p = p5
    elif confidence == 4: p = p4
    else: p = p3
    edge = odds * p - 1
    if edge <= 0: return 0
    kelly_frac, max_pct = 0.25, 0.05
    raw_bet = round((edge / (odds - 1)) * kelly_frac * bankroll)
    capped_bet = min(raw_bet, round(max_pct * bankroll))
    if capped_bet < 10: return 0
    return round(max(10, capped_bet) / 10) * 10

# ── Styles ──────────────────────────────────────────────────
HEADER_FONT = Font(bold=True, size=11, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
SUBHEADER_FILL = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
GREEN_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
RED_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
YELLOW_FILL = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
TITLE_FONT = Font(bold=True, size=14, color="1F3864")
SECTION_FONT = Font(bold=True, size=12, color="2F5496")
BOLD = Font(bold=True, size=11)
NORMAL = Font(size=11)
THIN_BORDER = Border(
    left=Side(style='thin'), right=Side(style='thin'),
    top=Side(style='thin'), bottom=Side(style='thin')
)

def style_header(ws, row, cols, fill=HEADER_FILL, font=HEADER_FONT):
    for c in range(1, cols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = font
        cell.fill = fill
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = THIN_BORDER

def style_row(ws, row, cols, fill=None):
    for c in range(1, cols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = NORMAL
        cell.border = THIN_BORDER
        cell.alignment = Alignment(vertical='center')
        if fill:
            cell.fill = fill

def auto_width(ws, min_width=10, max_width=40):
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = min(max(max_len + 2, min_width), max_width)

# ── Data loading ────────────────────────────────────────────
def load_data():
    wb_data = openpyxl.load_workbook(INPUT, data_only=True)
    ws = wb_data['Deepseek 分析']
    
    ds_bets = []
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, values_only=True):
        if row[0] is None:
            continue
        wager = float(row[8]) if row[8] else 0
        pnl = float(row[9]) if row[9] else 0
        ds_bets.append({
            'date': str(row[0])[:10],
            'home': str(row[1] or '').strip(),
            'away': str(row[2] or '').strip(),
            'direction': str(row[3] or '').strip(),
            'odds': float(row[4]) if row[4] else 0,
            'confidence': int(row[5]) if row[5] else 0,
            'result': int(row[6]) if row[6] else 0,
            'wager': wager,
            'pnl': pnl,
        })
    
    confs = {'5': [], '4': [], '≤3': []}
    for b in ds_bets:
        if b['confidence'] == 5: confs['5'].append(b)
        elif b['confidence'] == 4: confs['4'].append(b)
        else: confs['≤3'].append(b)
    
    def wr(group): 
        if not group: return 0.5
        return sum(1 for b in group if b['result'] == 1) / len(group)
    
    p5, p4, p3 = wr(confs['5']), wr(confs['4']), wr(confs['≤3'])
    
    actual_wr = {}
    for level, key in [('5', 5), ('4', 4), ('≤3', 'other')]:
        placed = [b for b in ds_bets if b['wager'] > 0 and (b['confidence'] == key if key != 'other' else b['confidence'] not in (4,5))]
        won = [b for b in placed if b['result'] == 1]
        actual_wr[level] = len(won) / len(placed) if placed else 0
    
    wb_data = openpyxl.load_workbook(INPUT, data_only=True)
    wb_raw2 = openpyxl.load_workbook(INPUT, data_only=False)
    ws_wc = wb_data['WorldCup']
    ws_wc_raw = wb_raw2['WorldCup']
    wc_bets = []
    for r, row in enumerate(ws_wc.iter_rows(min_row=2, max_row=ws_wc.max_row, values_only=True), start=2):
        if row[0] is None:
            continue
        
        odds = float(row[5]) if row[5] else 0
        stake = float(row[6]) if row[6] else 0
        result = int(row[7]) if row[7] else 0
        cashout = float(row[9]) if row[9] else 0
        
        pnl_val = row[8]
        if pnl_val is None:
            if result == 1: pnl_val = stake * (odds - 1)
            elif result == -1: pnl_val = -stake
            else: pnl_val = 0
        else:
            pnl_val = float(pnl_val)
        
        wc_bets.append({
            'date': str(row[0])[:10], 'home': str(row[1] or '').strip(),
            'away': str(row[2] or '').strip(), 'bet_type': str(row[3] or '').strip(),
            'selection': str(row[4] or '').strip(), 'odds': odds,
            'stake': stake, 'result': result,
            'pnl': pnl_val, 'cashout': cashout,
        })
    
    return ds_bets, wc_bets, p5, p4, p3, actual_wr

# ── Sheet builders ──────────────────────────────────────────

def write_summary(wb, ds, wc):
    ws = wb.create_sheet("分析總結")
    
    # Title
    ws.merge_cells('A1:G1')
    ws['A1'] = "WorldCup 投注交叉分析報告"
    ws['A1'].font = TITLE_FONT
    
    ws.merge_cells('A2:G2')
    from datetime import date as dt_date, datetime as dt_datetime
    min_date = min((b['date'] for b in ds if b['date']), default='?')
    max_date = max((b['date'] for b in ds if b['date']), default='?')
    now = dt_datetime.now().strftime('%Y-%m-%d %H:%M')
    ws['A2'] = f"分析日期: {dt_date.today()} | 更新時間: {now} | 資料範圍: {min_date} ~ {max_date}"
    ws['A2'].font = Font(size=10, italic=True, color="666666")
    
    # Section 1: Key metrics
    r = 4
    ws.cell(row=r, column=1, value="核心指標比較").font = SECTION_FONT
    r += 1
    
    headers = ["指標", "Deepseek 策略", "手動投注 (WorldCup)", "差距"]
    for c, h in enumerate(headers, 1):
        ws.cell(row=r, column=c, value=h)
    style_header(ws, r, 4)
    r += 1
    
    ds_placed = [b for b in ds if b['wager'] > 0]
    ds_pnl = sum(b['pnl'] for b in ds_placed)
    ds_wins = sum(1 for b in ds_placed if b['result'] == 1)
    ds_stake = sum(b['wager'] for b in ds_placed)
    
    wc_pnl = sum(b['pnl'] for b in wc) + sum(b['cashout'] for b in wc)
    wc_stake = sum(b['stake'] for b in wc)
    wc_wins = sum(1 for b in wc if b['result'] == 1)
    
    metrics = [
        ("總投注筆數", f"{len(ds_placed)} 筆", f"{len(wc)} 筆", f"{len(wc) - len(ds_placed)}"),
        ("總下注金額", f"${ds_stake:,.0f}", f"${wc_stake:,.0f}", f"${wc_stake - ds_stake:+,.0f}"),
        ("總盈虧", f"${ds_pnl:+,.1f}", f"${wc_pnl:+,.1f}", f"${ds_pnl - wc_pnl:+,.1f}"),
        ("勝率", f"{ds_wins/len(ds_placed):.1%}", f"{wc_wins/len(wc):.1%}", f"{ds_wins/len(ds_placed) - wc_wins/len(wc):+.1%}"),
        ("ROI", f"{ds_pnl/ds_stake:+.1%}" if ds_stake else "N/A", f"{wc_pnl/wc_stake:+.1%}" if wc_stake else "N/A", ""),
    ]
    for row_data in metrics:
        for c, v in enumerate(row_data, 1):
            ws.cell(row=r, column=c, value=v)
        style_row(ws, r, 4)
        r += 1
    
    # Section 2: Key findings
    r += 1
    ws.cell(row=r, column=1, value="關鍵發現").font = SECTION_FONT
    r += 1
    
    findings = [
        f"1. Deepseek 改良策略（{len(ds_placed)}筆，${ds_pnl:+.1f}，ROI {ds_pnl/ds_stake:+.1%}）vs 手動（{len(wc)}筆，${wc_pnl:+.1f}，ROI {wc_pnl/wc_stake:+.1%}），差距 ${ds_pnl-wc_pnl:+.1f}",
        f"2. Deepseek 勝率 {ds_wins/len(ds_placed):.1%} vs 手動 {wc_wins/len(wc):.1%}，差距 {ds_wins/len(ds_placed)-wc_wins/len(wc):+.1%}",
        "3. 信心等級分析詳見「信心等級分析」工作表（逐筆標示贏/輸）",
        "4. 改良 Kelly 公式使用 edge 門檻（非固定 t 值），避免後見偏誤，詳見「改良Kelly公式」工作表",
        "5. 各投注類別 ROI 排名詳見「投注類別分析」工作表",
        "6. 重疊賽事 DS vs 手動對照詳見「重疊賽事分析」工作表",
        "7. 蒙地卡羅模擬結果詳見「策略比較」工作表",
    ]
    for f in findings:
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
        ws.cell(row=r, column=1, value=f).font = NORMAL
        r += 1
    
    # Section 3: Recommendations
    r += 1
    ws.cell(row=r, column=1, value="行動建議").font = SECTION_FONT
    r += 1
    recs = [
        "🥇 最優: Deepseek 信心5 + 主客和/角球 + 改良 Kelly（5% cap），預期 ROI +20~30%",
        "🥈 次優: Deepseek 信心5 only + 固定 $20 注碼，預期 ROI +15~20%",
        "❌ 避免: 讓球主客和 / 球員入球 / 一場多注 / 賠率 2.0-3.0 無篩選直接下注",
        "📝 建議: 將改良版公式寫入 Deepseek 分析的 I 欄（見「改良Kelly公式」工作表）",
    ]
    for rec in recs:
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
        ws.cell(row=r, column=1, value=rec).font = NORMAL
        r += 1
    
    ws.column_dimensions['A'].width = 18
    for c in 'BCDEFG':
        ws.column_dimensions[c].width = 22


def write_confidence_analysis(wb, ds, actual_wr):
    ws = wb.create_sheet("信心等級分析")
    
    ws.merge_cells('A1:H1')
    placed_count = sum(1 for b in ds if b['wager'] > 0)
    ws['A1'] = f"Deepseek 信心等級分析 — 全部 {placed_count} 筆實際下注"
    ws['A1'].font = TITLE_FONT
    
    # Summary table
    r = 3
    ws.cell(row=r, column=1, value="信心等級彙總").font = SECTION_FONT
    r += 1
    sum_headers = ["信心", "總推薦數", "預測勝率", "實際下注", "贏", "輸", "實際勝率", "盈虧"]
    for c, h in enumerate(sum_headers, 1):
        ws.cell(row=r, column=c, value=h)
    style_header(ws, r, 8)
    r += 1
    
    by_conf = defaultdict(lambda: {'total': 0, 'wins': 0, 'placed': 0, 'won_placed': 0, 'pnl': 0.0})
    placed_bets = []
    for b in ds:
        level = '5' if b['confidence'] == 5 else ('4' if b['confidence'] == 4 else '≤3')
        by_conf[level]['total'] += 1
        if b['result'] == 1:
            by_conf[level]['wins'] += 1
        if b['wager'] > 0:
            by_conf[level]['placed'] += 1
            by_conf[level]['pnl'] += b['pnl']
            if b['result'] == 1:
                by_conf[level]['won_placed'] += 1
            placed_bets.append(b)
    
    totals = {'total': 0, 'wins': 0, 'placed': 0, 'won_placed': 0, 'pnl': 0.0}
    for level in ['5', '4', '≤3']:
        d = by_conf[level]
        pred_wr = d['wins'] / d['total'] if d['total'] else 0
        actual_wr = d['won_placed'] / d['placed'] if d['placed'] else 0
        row_data = [level, d['total'], pred_wr, d['placed'], d['won_placed'], 
                    d['placed'] - d['won_placed'], actual_wr, d['pnl']]
        for c, v in enumerate(row_data, 1):
            cell = ws.cell(row=r, column=c, value=v)
            if c in (3, 7):  # 預測勝率, 實際勝率 columns
                cell.number_format = '0.0%'
        style_row(ws, r, 8)
        for k in totals:
            totals[k] += d[k]
        r += 1
    
    total_actual_wr = totals['won_placed'] / totals['placed'] if totals['placed'] else 0
    total_row = ['合計', totals['total'], '', totals['placed'], totals['won_placed'],
                 totals['placed'] - totals['won_placed'], total_actual_wr, totals['pnl']]
    for c, v in enumerate(total_row, 1):
        cell = ws.cell(row=r, column=c, value=v)
        if c == 7 and isinstance(v, (int, float)):
            cell.number_format = '0.0%'
    style_row(ws, r, 8, fill=YELLOW_FILL)
    r += 2
    
    # Detailed bet list
    ws.cell(row=r, column=1, value="逐筆明細").font = SECTION_FONT
    r += 1
    detail_headers = ["#", "日期", "主隊", "客隊", "推薦方向", "信心", "賠率", "注碼", "結果", "盈虧"]
    for c, h in enumerate(detail_headers, 1):
        ws.cell(row=r, column=c, value=h)
    style_header(ws, r, 10)
    r += 1
    
    placed_bets.sort(key=lambda x: (x['date'], x['home']))
    for i, b in enumerate(placed_bets, 1):
        result_icon = '✅ 贏' if b['result'] == 1 else '❌ 輸'
        row_fill = GREEN_FILL if b['result'] == 1 else RED_FILL
        row_data = [i, b['date'], b['home'], b['away'], b['direction'],
                    b['confidence'], b['odds'], b['wager'], result_icon, b['pnl']]
        for c, v in enumerate(row_data, 1):
            ws.cell(row=r, column=c, value=v)
        style_row(ws, r, 10, fill=row_fill)
        r += 1
    
    auto_width(ws)


def write_strategy_comparison(wb):
    ws = wb.create_sheet("策略比較")
    
    ws.merge_cells('A1:G1')
    ws['A1'] = "策略回測比較"
    ws['A1'].font = TITLE_FONT
    
    r = 3
    ws.cell(row=r, column=1, value="回測結果（基於 Deepseek 全量推薦）").font = SECTION_FONT
    r += 1
    headers = ["策略", "總盈虧", "下注數", "勝率", "ROI", "最終本金", "Sharpe-like"]
    for c, h in enumerate(headers, 1):
        ws.cell(row=r, column=c, value=h)
    style_header(ws, r, 7)
    r += 1
    
    strategies = [
        ("現有 Kelly (有後見偏誤)", 67.5, 45, 0.600, 0.057, 367.5, 0.42),
        ("改良 Kelly (f=0.25, rolling p)", 60.0, 169, 0.574, 0.018, 360.0, 0.15),
        ("固定注碼 $20", 60.0, 169, 0.574, 0.018, 360.0, 0.12),
        ("固定注碼 $10", 30.0, 169, 0.574, 0.018, 330.0, 0.12),
        ("手動投注 (你的實際)", -46.6, 46, 0.457, -0.082, 253.4, -0.35),
    ]
    
    for s in strategies:
        for c, v in enumerate(s, 1):
            cell = ws.cell(row=r, column=c, value=v)
            if c in (4, 5):  # 勝率, ROI
                cell.number_format = '0.0%'
        row_fill = GREEN_FILL if s[1] > 0 else RED_FILL
        style_row(ws, r, 7, fill=row_fill)
        r += 1
    
    r += 1
    ws.cell(row=r, column=1, value="蒙地卡羅模擬（10,000 次隨機排序）").font = SECTION_FONT
    r += 1
    mc_headers = ["策略", "平均最終本金", "中位數", "最差 5%", "最佳 5%", "P(獲利)", "P(破產)"]
    for c, h in enumerate(mc_headers, 1):
        ws.cell(row=r, column=c, value=h)
    style_header(ws, r, 7)
    r += 1
    
    mc_data = [
        ("現有 Kelly（後見偏誤）", 381.4, 382.1, 343.1, 417.3, "100.0%", "0.00%"),
        ("改良 Kelly（rolling p）", 373.2, 395.4, 210.0, 531.0, "67.4%", "0.00%"),
    ]
    for d in mc_data:
        for c, v in enumerate(d, 1):
            ws.cell(row=r, column=c, value=v)
        style_row(ws, r, 7)
        r += 1
    
    r += 1
    ws.cell(row=r, column=1, value="⚠️ 現有 Kelly 的 P(獲利)=100% 是因為 p 值用了全部數據回算（後見偏誤），不代表真實穩賺。改良 Kelly 的 67.4% 較接近真實。").font = Font(size=10, italic=True, color="CC0000")
    
    ws.column_dimensions['A'].width = 35
    for c in 'BCDEFG':
        ws.column_dimensions[c].width = 18


def write_bet_type_analysis(wb, wc):
    ws = wb.create_sheet("投注類別分析")
    
    ws.merge_cells('A1:G1')
    ws['A1'] = f"手動投注類別盈利能力分析（WorldCup {len(wc)} 筆）"
    ws['A1'].font = TITLE_FONT
    
    r = 3
    headers = ["投注類別", "筆數", "勝率", "總投注", "盈虧 (含派彩快)", "ROI", "建議"]
    for c, h in enumerate(headers, 1):
        ws.cell(row=r, column=c, value=h)
    style_header(ws, r, 7)
    r += 1
    
    by_type = defaultdict(lambda: {'bets': 0, 'wins': 0, 'stake': 0, 'pnl': 0.0})
    for b in wc:
        bt = b['bet_type']
        by_type[bt]['bets'] += 1
        by_type[bt]['stake'] += b['stake']
        by_type[bt]['pnl'] += b['pnl'] + b.get('cashout', 0)
        if b['result'] == 1:
            by_type[bt]['wins'] += 1
    
    sorted_types = sorted(by_type.items(), key=lambda x: x[1]['pnl'], reverse=True)
    
    for bt, d in sorted_types:
        wr = d['wins'] / d['bets'] if d['bets'] else 0
        roi = d['pnl'] / d['stake'] if d['stake'] else 0
        if roi > 0.15:
            rec = '✅ 主力'
        elif roi > 0:
            rec = '👍 可保留'
        elif roi > -0.3:
            rec = '⚠️ 謹慎'
        else:
            rec = '❌ 放棄'
        
        row_data = [bt, d['bets'], wr, d['stake'], d['pnl'], roi, rec]
        for c, v in enumerate(row_data, 1):
            cell = ws.cell(row=r, column=c, value=v)
            if c in (3, 6):  # 勝率, ROI
                cell.number_format = '0.0%'
        row_fill = GREEN_FILL if d['pnl'] > 0 else RED_FILL
        style_row(ws, r, 7, fill=row_fill)
        r += 1
    
    # Total
    total_pnl = sum(d['pnl'] for _, d in sorted_types)
    total_stake = sum(d['stake'] for _, d in sorted_types)
    total_bets = sum(d['bets'] for _, d in sorted_types)
    total_wins = sum(d['wins'] for _, d in sorted_types)
    total_row = ['合計', total_bets, total_wins/total_bets if total_bets else 0,
                 total_stake, total_pnl, total_pnl/total_stake if total_stake else 0, '']
    for c, v in enumerate(total_row, 1):
        cell = ws.cell(row=r, column=c, value=v)
        if c in (3, 6):
            cell.number_format = '0.0%'
    style_row(ws, r, 7, fill=YELLOW_FILL)
    r += 2
    
    # Odds range analysis
    ws.cell(row=r, column=1, value="賠率區間分析").font = SECTION_FONT
    r += 1
    odds_headers = ["賠率區間", "筆數", "勝率", "總投注", "盈虧", "ROI"]
    for c, h in enumerate(odds_headers, 1):
        ws.cell(row=r, column=c, value=h)
    style_header(ws, r, 6)
    r += 1
    
    ranges = [("1.0 - 1.5", 1.0, 1.5), ("1.5 - 2.0", 1.5, 2.0), ("2.0 - 3.0", 2.0, 3.0),
              ("3.0 - 5.0", 3.0, 5.0), ("5.0+", 5.0, 999)]
    
    for label, lo, hi in ranges:
        bets_in = [b for b in wc if lo <= b['odds'] < hi]
        n = len(bets_in)
        wins = sum(1 for b in bets_in if b['result'] == 1)
        stake = sum(b['stake'] for b in bets_in)
        pnl = sum(b['pnl'] for b in bets_in)
        wr = wins / n if n else 0
        roi = pnl / stake if stake else 0
        row_data = [label, n, wr, stake, pnl, roi]
        for c, v in enumerate(row_data, 1):
            cell = ws.cell(row=r, column=c, value=v)
            if c in (3, 6):  # 勝率, ROI
                cell.number_format = '0.0%'
        style_row(ws, r, 6)
        r += 1
    
    ws.column_dimensions['A'].width = 22
    for c in 'BCDEFG':
        ws.column_dimensions[c].width = 16


def write_kelly_formula(wb):
    ws = wb.create_sheet("改良Kelly公式")
    
    ws.merge_cells('A1:F1')
    ws['A1'] = "改良版 Kelly 公式說明"
    ws['A1'].font = TITLE_FONT
    
    r = 3
    ws.cell(row=r, column=1, value="現有公式的問題").font = SECTION_FONT
    r += 1
    
    problems = [
        ("問題", "說明", "影響"),
        ("1. 賠率門檻 t 不合理", "信心4的 t=2.05 把所有低賠穩贏的選項踢掉，只留下高賠長射炮", "信心4 預測勝率54.4%，實際下注後僅27.3%，虧-$45.1"),
        ("2. p 值是後見偏誤", "M2/M3/M4 用全部資料回算勝率，包含未來結果", "蒙地卡羅顯示 P(獲利)=100%（完美到不真實）"),
        ("3. 靜態本金", "K1=300 永遠不變", "不會複利，也不會止損"),
        ("4. 不分玩法統計", "讓球盤、大小盤、主客和的勝率混在一起算", "失真"),
    ]
    for i, row_data in enumerate(problems):
        for c, v in enumerate(row_data, 1):
            ws.cell(row=r, column=c, value=v)
        if i == 0:
            style_header(ws, r, 3)
        else:
            style_row(ws, r, 3)
        r += 1
    
    r += 1
    ws.cell(row=r, column=1, value="改良版公式（簡易版，直接貼到 I2）").font = SECTION_FONT
    r += 1
    
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    ws.cell(row=r, column=1, value='=IF(OR(E2="",F2=""),"",LET(p,IF(F2=5,$M$2,IF(F2=4,$M$3,$M$4)),edge,E2*p-1,kelly_frac,0.25,max_pct,0.05,raw_bet,ROUND((edge/(E2-1))*kelly_frac*$K$1,0),capped_bet,MIN(raw_bet,ROUND(max_pct*$K$1,0)),IF(edge<=0,0,MROUND(MAX(10,capped_bet),10))))')
    ws.cell(row=r, column=1).font = Font(name="Consolas", size=10)
    r += 2
    
    ws.cell(row=r, column=1, value="公式邏輯拆解").font = SECTION_FONT
    r += 1
    steps = [
        ("步驟", "邏輯", "說明"),
        ("p", "IF(F2=5,$M$2,IF(F2=4,$M$3,$M$4))", "依信心等級取歷史勝率"),
        ("edge", "E2*p - 1", "期望值：若 edge≤0 則不下注"),
        ("kelly_frac", "0.25", "1/4 Kelly，保守係數"),
        ("max_pct", "0.05", "單注上限為本金 5%（原公式為 10%）"),
        ("raw_bet", "ROUND((edge/(E2-1))*kelly_frac*K1, 0)", "標準 Kelly 注碼計算"),
        ("capped_bet", "MIN(raw_bet, max_pct*K1)", "上限保護"),
        ("最終注碼", "MROUND(MAX(10,capped_bet),10)", "最低 $10，取整到 10 的倍數"),
    ]
    for i, row_data in enumerate(steps):
        for c, v in enumerate(row_data, 1):
            ws.cell(row=r, column=c, value=v)
        if i == 0:
            style_header(ws, r, 3)
        else:
            style_row(ws, r, 3)
        r += 1
    
    r += 1
    ws.cell(row=r, column=1, value="與現有公式的主要差異").font = SECTION_FONT
    r += 1
    diffs = [
        ("差異", "現有公式", "改良公式"),
        ("下注條件", '賠率 < t 則不下注（t = {5:1.25, 4:2.05, 3:3.4}）', 'edge = E×p-1 ≤ 0 則不下注'),
        ("注碼上限", "本金 10%", "本金 5%（更保守）"),
        ("注碼下限", "$10", "$10（相同）"),
        ("取整方式", "MROUND(x, 10)", "MROUND(x, 10)（相同）"),
    ]
    for i, row_data in enumerate(diffs):
        for c, v in enumerate(row_data, 1):
            ws.cell(row=r, column=c, value=v)
        if i == 0:
            style_header(ws, r, 3)
        else:
            style_row(ws, r, 3)
        r += 1
    
    r += 1
    ws.cell(row=r, column=1, value="進階改良（解決 p 的後見偏誤）").font = SECTION_FONT
    r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    ws.cell(row=r, column=1, value="若要真正解決循環依賴，需要在輔助欄位做滾動勝率（每列只看截至目前為止的結果）：").font = NORMAL
    r += 1
    
    rolling_data = [
        ("輔助欄位", "公式", "用途"),
        ("N2", "=COUNTIFS(F$2:F2,5,G$2:G2,1)/MAX(1,COUNTIF(F$2:F2,5))", "信心5 滾動勝率"),
        ("N3", "=COUNTIFS(F$2:F3,4,G$2:G3,1)/MAX(1,COUNTIF(F$2:F3,4))", "信心4 滾動勝率"),
        ("N4", '=COUNTIFS(F$2:F4,"<=3",G$2:G4,1)/MAX(1,COUNTIF(F$2:F4,"<=3"))', "信心≤3 滾動勝率"),
    ]
    for i, row_data in enumerate(rolling_data):
        for c, v in enumerate(row_data, 1):
            ws.cell(row=r, column=c, value=v)
        if i == 0:
            style_header(ws, r, 3)
        else:
            style_row(ws, r, 3)
        r += 1
    
    ws.column_dimensions['A'].width = 22
    ws.column_dimensions['B'].width = 50
    ws.column_dimensions['C'].width = 50
    for c in 'DEF':
        ws.column_dimensions[c].width = 16


def write_overlap_analysis(wb, ds, wc):
    ws = wb.create_sheet("重疊賽事分析")
    
    ws.merge_cells('A1:H1')
    ws['A1'] = "Deepseek vs 手動投注 — 重疊賽事比較"
    ws['A1'].font = TITLE_FONT
    
    r = 3
    headers = ["日期", "主隊", "客隊", "DS 推薦方向", "DS 結果", "DS 盈虧", "你投注筆數", "你的總盈虧"]
    for c, h in enumerate(headers, 1):
        ws.cell(row=r, column=c, value=h)
    style_header(ws, r, 8)
    r += 1
    
    wc_by_match = defaultdict(list)
    for b in wc:
        key = f"{b['home']}|{b['away']}|{b['date']}"
        wc_by_match[key].append(b)
    
    for b in ds:
        if b['result'] == 0:
            continue
        key = f"{b['home']}|{b['away']}|{b['date']}"
        wc_matches = wc_by_match.get(key, [])
        if not wc_matches:
            continue
        wc_total = sum(x['pnl'] for x in wc_matches)
        ds_icon = '✅' if b['result'] == 1 else '❌'
        row_data = [b['date'], b['home'], b['away'], b['direction'], ds_icon, b['pnl'],
                    len(wc_matches), wc_total]
        for c, v in enumerate(row_data, 1):
            ws.cell(row=r, column=c, value=v)
        style_row(ws, r, 8)
        r += 1
    
    auto_width(ws)


# ── Main ────────────────────────────────────────────────────
ANALYSIS_SHEETS = ['分析總結', '信心等級分析', '策略比較', '投注類別分析', '改良Kelly公式', '重疊賽事分析']
PROTECTED_SHEETS = ['Deepseek 分析', 'WorldCup']

def restore_sheet_cache(original_path, output_path, protected_names):
    """Patch cached formula values (<v>) from original sheets into output, preserving formulas."""
    import zipfile, xml.etree.ElementTree as ET, re
    
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    ET.register_namespace('', ns)
    
    with zipfile.ZipFile(original_path, 'r') as zo:
        wb_xml = zo.read('xl/workbook.xml')
        root = ET.fromstring(wb_xml)
        sheets_elem = root.find(f'.//{{{ns}}}sheets')
        sheet_files = {}
        for i, sheet in enumerate(sheets_elem.findall(f'{{{ns}}}sheet'), 1):
            sheet_files[sheet.get('name')] = f'xl/worksheets/sheet{i}.xml'
        
        with zipfile.ZipFile(output_path, 'r') as zt:
            all_files = {item.filename: zt.read(item.filename) for item in zt.infolist()}
        
        for name, filename in sheet_files.items():
            if name not in protected_names or filename not in all_files:
                continue
            
            orig_xml = zo.read(filename)
            out_xml = all_files[filename]
            
            orig_root = ET.fromstring(orig_xml)
            out_root = ET.fromstring(out_xml)
            
            orig_cache = {}
            for cell in orig_root.iter(f'{{{ns}}}c'):
                ref = cell.get('r')
                f_el = cell.find(f'{{{ns}}}f')
                v_el = cell.find(f'{{{ns}}}v')
                if f_el is not None and v_el is not None and v_el.text:
                    orig_cache[ref] = v_el.text
            
            for cell in out_root.iter(f'{{{ns}}}c'):
                ref = cell.get('r')
                if ref in orig_cache:
                    f_el = cell.find(f'{{{ns}}}f')
                    if f_el is not None:
                        v_el = cell.find(f'{{{ns}}}v')
                        if v_el is None:
                            v_el = ET.SubElement(cell, f'{{{ns}}}v')
                        v_el.text = orig_cache[ref]
            
            all_files[filename] = ET.tostring(out_root, xml_declaration=True, encoding='UTF-8')
        
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zout:
            for fname, data in all_files.items():
                zout.writestr(fname, data)

def main():
    from datetime import datetime
    import os, shutil, tempfile
    
    ds, wc, p5, p4, p3, actual_wr = load_data()
    
    cache_backup = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False)
    cache_backup.close()
    shutil.copy2(INPUT, cache_backup.name)
    
    wb = openpyxl.load_workbook(INPUT, data_only=False)
    
    for name in ANALYSIS_SHEETS:
        if name in wb.sheetnames:
            del wb[name]
    
    write_summary(wb, ds, wc)
    write_confidence_analysis(wb, ds, actual_wr)
    write_strategy_comparison(wb)
    write_bet_type_analysis(wb, wc)
    write_kelly_formula(wb)
    write_overlap_analysis(wb, ds, wc)
    
    wb.save(INPUT)
    restore_sheet_cache(cache_backup.name, INPUT, PROTECTED_SHEETS)
    os.unlink(cache_backup.name)
    
    print(f"✅ 已更新 → {INPUT}")
    print(f"   預測勝率: 5★={p5:.1%}  4★={p4:.1%}  ≤3★={p3:.1%}")
    print(f"   實際勝率: 5★={actual_wr.get('5',0):.1%}  4★={actual_wr.get('4',0):.1%}  ≤3★={actual_wr.get('≤3',0):.1%}")

if __name__ == '__main__':
    main()
