#!/usr/bin/env python3
"""
WorldCup 交叉分析腳本
- 資料提取 (Deepseek分析 + WorldCup投注記錄)
- 策略回測 (現有Kelly、改良Kelly、固定注碼)
- 蒙地卡羅模擬
- 投注類別盈利能力分析
"""

import openpyxl
import json
import math
import random
from collections import defaultdict
from datetime import datetime

# ============================================================
# 1. DATA EXTRACTION
# ============================================================

def load_data(filepath):
    wb = openpyxl.load_workbook(filepath, data_only=True)
    
    # --- Deepseek 分析 ---
    ws_ds = wb['Deepseek 分析']
    ds_bets = []
    # Columns: A=日期 B=主隊 C=客隊 D=投注類別(新) E=注項(新)
    #           F=推薦方向 G=倍率 H=信心指數 I=贏輸 J=(空) K=Weighted Bet L=盈虧
    for row in ws_ds.iter_rows(min_row=2, max_row=ws_ds.max_row, values_only=True):
        if row[0] is None:  # No date = empty row
            continue
        date, home, away = row[0], row[1], row[2]
        direction, odds, confidence, result = row[5], row[6], row[7], row[8]
        wager = row[10] if len(row) > 10 else None   # Column K
        pnl = row[11] if len(row) > 11 else None      # Column L
        ds_bets.append({
            'date': str(date)[:10] if date else None,
            'home': str(home).strip() if home else '',
            'away': str(away).strip() if away else '',
            'direction': str(direction).strip() if direction else '',
            'odds': float(odds) if odds else None,
            'confidence': int(confidence) if confidence else None,
            'result': int(result) if result else None,
            'wager': float(wager) if wager else 0,
            'pnl': float(pnl) if pnl else 0,
        })

    # --- WorldCup 投注記錄 ---
    ws_wc = wb['WorldCup']
    wc_bets = []
    for row in ws_wc.iter_rows(min_row=2, max_row=ws_wc.max_row, values_only=True):
        if row[0] is None:
            continue
        date, home, away, bet_type, selection, odds, stake, result, pnl, cashout = row[0:10]
        wc_bets.append({
            'date': str(date)[:10] if date else None,
            'home': str(home).strip() if home else '',
            'away': str(away).strip() if away else '',
            'bet_type': str(bet_type).strip() if bet_type else '',
            'selection': str(selection).strip() if selection else '',
            'odds': float(odds) if odds else None,
            'stake': float(stake) if stake else 0,
            'result': int(result) if result else None,
            'pnl': float(pnl) if pnl else 0,
            'cashout': float(cashout) if cashout else 0,
        })
    
    return ds_bets, wc_bets


# ============================================================
# 2. EXISTING KELLY FORMULA (as implemented in Excel)
# ============================================================

def existing_kelly(odds, confidence, p5, p4, p3, bankroll=300):
    """Replicate the existing Excel Kelly formula"""
    if odds is None or confidence is None:
        return 0
    
    # p = historical win rate by confidence
    if confidence == 5:
        p = p5
        t = 1.25
    elif confidence == 4:
        p = p4
        t = 2.05
    else:  # <=3
        p = p3
        t = 3.4
    
    if odds < t:
        return 0
    
    # Kelly fraction: (E*p - 1)/(E - 1) / 4
    kelly_frac = (odds * p - 1) / (odds - 1)
    x = kelly_frac / 4
    x = max(0, min(0.1, x))
    x = round(x * bankroll, 0)
    
    if x == 0:
        return 0
    # MROUND to nearest 10, min 10
    x = max(10, round(x / 10) * 10)
    return x


# ============================================================
# 3. IMPROVED KELLY FORMULA
# ============================================================

class ImprovedKelly:
    """
    改良版 Kelly 策略:
    - 動態滾動勝率 (最近 N 場)
    - 移除固定門檻 t，改用 edge 判斷
    - 浮動本金
    - 依玩法分開統計
    - 暖機期: 前 N 場用固定注碼累積資料
    """
    
    def __init__(self, bankroll=300, kelly_fraction=0.25, window=20, warmup=15):
        self.bankroll = bankroll
        self.initial_bankroll = bankroll
        self.kelly_fraction = kelly_fraction
        self.window = window
        self.warmup = warmup  # First N bets use flat stake to build history
        self.history = []  # (odds, result) tuple
        self.history_by_type = defaultdict(list)
        self.bet_count = 0
        
    def get_rolling_winrate(self, bet_type=None):
        """Get rolling win rate, optionally filtered by bet type"""
        # Use type-specific history if we have enough data
        if bet_type and bet_type in self.history_by_type and len(self.history_by_type[bet_type]) >= 8:
            pool = self.history_by_type[bet_type][-self.window:]
        elif len(self.history) >= 5:
            pool = self.history[-self.window:]
        else:
            # Bayesian prior: assume 55% win rate with 20 observations of strength
            return 0.55
        
        wins = sum(1 for _, r in pool if r == 1)
        # Laplace smoothing with prior toward 0.55
        prior_strength = 10
        prior_wins = int(0.55 * prior_strength)
        return (wins + prior_wins) / (len(pool) + prior_strength)
    
    def compute_wager(self, odds, confidence=None, bet_type=None):
        if odds is None or odds <= 1.0:
            return 0
        
        self.bet_count += 1
        
        p = self.get_rolling_winrate(bet_type)
        edge = odds * p - 1
        
        if edge <= 0:
            return 0
        
        full_kelly = edge / (odds - 1)
        frac = full_kelly * self.kelly_fraction
        frac = min(frac, 0.10)
        
        wager = round(frac * self.bankroll)
        if wager < 10:
            return 0
        wager = round(wager / 10) * 10
        
        return wager
    
    def update(self, odds, result, wager, bet_type=None):
        """Update bankroll and history after bet"""
        self.history.append((odds, result))
        if bet_type:
            self.history_by_type[bet_type].append((odds, result))
        if result == 1:
            self.bankroll += wager * (odds - 1)
        elif result == -1:
            self.bankroll -= wager


# ============================================================
# 4. BACKTESTING
# ============================================================

def classify_bet_type(direction):
    """Classify Deepseek direction into bet type categories"""
    d = direction.lower() if direction else ''
    if '讓球主客和' in direction or '讓球盤' in direction or '/+' in d or '/-' in d:
        return '讓球'
    elif '入球' in direction:
        return '入球大細'
    elif '主勝' in direction or '客勝' in direction or '客隊勝' in direction or '主隊勝' in direction:
        return '主客和'
    elif '和局' in direction:
        return '讓球主客和-和局'
    else:
        return '其他'


def backtest_existing_kelly(bets):
    """Backtest the existing Kelly strategy"""
    # First pass: compute historical win rates
    wins_5 = sum(1 for b in bets if b['confidence'] == 5 and b['result'] == 1)
    total_5 = sum(1 for b in bets if b['confidence'] == 5)
    wins_4 = sum(1 for b in bets if b['confidence'] == 4 and b['result'] == 1)
    total_4 = sum(1 for b in bets if b['confidence'] == 4)
    wins_3 = sum(1 for b in bets if b['confidence'] in [1, 2, 3] and b['result'] == 1)
    total_3 = sum(1 for b in bets if b['confidence'] in [1, 2, 3])
    
    p5 = wins_5 / total_5 if total_5 > 0 else 0.5
    p4 = wins_4 / total_4 if total_4 > 0 else 0.5
    p3 = wins_3 / total_3 if total_3 > 0 else 0.5
    
    bankroll = 300
    total_wagered = 0
    total_pnl = 0
    bets_placed = 0
    wins = 0
    equity_curve = [300]
    
    for b in bets:
        wager = existing_kelly(b['odds'], b['confidence'], p5, p4, p3, bankroll)
        b['existing_wager'] = wager
        if wager > 0 and b['result'] is not None:
            bets_placed += 1
            total_wagered += wager
            if b['result'] == 1:
                pnl = wager * (b['odds'] - 1)
                wins += 1
            else:
                pnl = -wager
            total_pnl += pnl
            bankroll += pnl
            equity_curve.append(bankroll)
    
    return {
        'name': '現有 Kelly',
        'total_pnl': total_pnl,
        'total_wagered': total_wagered,
        'bets_placed': bets_placed,
        'wins': wins,
        'win_rate': wins / bets_placed if bets_placed > 0 else 0,
        'roi': total_pnl / total_wagered if total_wagered > 0 else 0,
        'final_bankroll': bankroll,
        'equity_curve': equity_curve,
    }


def backtest_improved_kelly(bets, kelly_fraction=0.25, window=20, warmup=15):
    kelly = ImprovedKelly(bankroll=300, kelly_fraction=kelly_fraction, window=window, warmup=warmup)
    
    bets_placed = 0
    wins = 0
    total_wagered = 0
    total_pnl = 0
    equity_curve = [300]
    
    for b in bets:
        bet_type = classify_bet_type(b['direction'])
        
        if kelly.bet_count < warmup:
            # Warmup: flat $20 bet on every recommendation to build history
            wager = 20
        else:
            wager = kelly.compute_wager(b['odds'], b['confidence'], bet_type)
        
        b['improved_wager'] = wager
        
        if wager > 0 and b['result'] is not None:
            bets_placed += 1
            total_wagered += wager
            kelly.update(b['odds'], b['result'], wager, bet_type)
            if b['result'] == 1:
                wins += 1
                pnl = wager * (b['odds'] - 1)
            else:
                pnl = -wager
            total_pnl += pnl
            equity_curve.append(kelly.bankroll)
        else:
            equity_curve.append(kelly.bankroll)
    
    return {
        'name': f'改良Kelly(f={kelly_fraction},w={window},wu={warmup})',
        'total_pnl': total_pnl,
        'total_wagered': total_wagered,
        'bets_placed': bets_placed,
        'wins': wins,
        'win_rate': wins / bets_placed if bets_placed > 0 else 0,
        'roi': total_pnl / total_wagered if total_wagered > 0 else 0,
        'final_bankroll': kelly.bankroll,
        'equity_curve': equity_curve,
    }


def backtest_fixed_stake(bets, stake=20):
    """Backtest fixed stake strategy (as user's actual betting)"""
    bankroll = 300
    bets_placed = 0
    wins = 0
    total_pnl = 0
    equity_curve = [300]
    
    for b in bets:
        if b['result'] is not None:
            bets_placed += 1
            if b['result'] == 1:
                pnl = stake * (b['odds'] - 1)
                wins += 1
            else:
                pnl = -stake
            total_pnl += pnl
            bankroll += pnl
            equity_curve.append(bankroll)
    
    return {
        'name': f'固定注碼 ${stake}',
        'total_pnl': total_pnl,
        'total_wagered': stake * bets_placed,
        'bets_placed': bets_placed,
        'wins': wins,
        'win_rate': wins / bets_placed if bets_placed > 0 else 0,
        'roi': total_pnl / (stake * bets_placed) if bets_placed > 0 else 0,
        'final_bankroll': bankroll,
        'equity_curve': equity_curve,
    }


# ============================================================
# 5. MONTE CARLO SIMULATION
# ============================================================

def monte_carlo_simulation(bets, strategy='improved', n_simulations=10000):
    """
    Monte Carlo: randomly shuffle bet order to see distribution of outcomes.
    This accounts for path dependency in bankroll management.
    """
    results = []
    equity_paths = []
    
    for sim in range(n_simulations):
        shuffled = random.sample(bets, len(bets))
        
        if strategy == 'improved':
            kelly = ImprovedKelly(bankroll=300, kelly_fraction=0.25)
            bankroll = 300
            eq = [300]
            for b in shuffled:
                bt = classify_bet_type(b['direction'])
                wager = kelly.compute_wager(b['odds'], b['confidence'], bt)
                if wager > 0 and b['result'] is not None:
                    kelly.update(b['odds'], b['result'], wager, bt)
                    eq.append(kelly.bankroll)
                else:
                    eq.append(kelly.bankroll)
            bankroll = kelly.bankroll
        else:  # existing
            wins_5 = sum(1 for b in bets if b['confidence'] == 5 and b['result'] == 1)
            total_5 = sum(1 for b in bets if b['confidence'] == 5)
            wins_4 = sum(1 for b in bets if b['confidence'] == 4 and b['result'] == 1)
            total_4 = sum(1 for b in bets if b['confidence'] == 4)
            wins_3 = sum(1 for b in bets if b['confidence'] in [1,2,3] and b['result'] == 1)
            total_3 = sum(1 for b in bets if b['confidence'] in [1,2,3])
            p5 = wins_5/total_5 if total_5 else 0.5
            p4 = wins_4/total_4 if total_4 else 0.5
            p3 = wins_3/total_3 if total_3 else 0.5
            bankroll = 300
            eq = [300]
            for b in shuffled:
                wager = existing_kelly(b['odds'], b['confidence'], p5, p4, p3, bankroll)
                if wager > 0 and b['result'] is not None:
                    if b['result'] == 1:
                        bankroll += wager * (b['odds'] - 1)
                    else:
                        bankroll -= wager
                    eq.append(bankroll)
                else:
                    eq.append(bankroll)
        
        results.append(bankroll)
        if sim < 100:  # Store first 100 paths for visualization data
            equity_paths.append(eq)
    
    results.sort()
    return {
        'mean': sum(results) / len(results),
        'median': results[len(results)//2],
        'min': results[0],
        'max': results[-1],
        'p5': results[int(len(results)*0.05)],
        'p25': results[int(len(results)*0.25)],
        'p75': results[int(len(results)*0.75)],
        'p95': results[int(len(results)*0.95)],
        'prob_profit': sum(1 for r in results if r > 300) / len(results),
        'prob_ruin': sum(1 for r in results if r < 30) / len(results),  # Ruin if < 10% of bankroll
        'all_results': results,
        'sample_paths': equity_paths,
    }


# ============================================================
# 6. BET TYPE ANALYSIS (WorldCup sheet)
# ============================================================

def analyze_bet_types(wc_bets):
    """Analyze profitability by bet type"""
    by_type = defaultdict(lambda: {'bets': 0, 'wins': 0, 'stake': 0, 'pnl': 0})
    
    for b in wc_bets:
        bt = b['bet_type']
        by_type[bt]['bets'] += 1
        by_type[bt]['stake'] += b['stake']
        by_type[bt]['pnl'] += b['pnl']
        by_type[bt]['pnl'] += b.get('cashout', 0)
        if b['result'] == 1:
            by_type[bt]['wins'] += 1
    
    results = []
    for bt, d in sorted(by_type.items(), key=lambda x: x[1]['pnl']):
        d['type'] = bt
        d['win_rate'] = d['wins'] / d['bets'] if d['bets'] > 0 else 0
        d['roi'] = d['pnl'] / d['stake'] if d['stake'] > 0 else 0
        results.append(d)
    
    return results


def analyze_by_odds_range(wc_bets):
    """Analyze profitability by odds range"""
    ranges = [(1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 100)]
    by_range = defaultdict(lambda: {'bets': 0, 'wins': 0, 'stake': 0, 'pnl': 0})
    
    for b in wc_bets:
        if b['odds'] is None:
            continue
        for lo, hi in ranges:
            if lo <= b['odds'] < hi:
                label = f'{lo}-{hi}' if hi < 100 else f'{lo}+'
                by_range[label]['bets'] += 1
                by_range[label]['stake'] += b['stake']
                by_range[label]['pnl'] += b['pnl']
                if b['result'] == 1:
                    by_range[label]['wins'] += 1
                break
    
    results = []
    for label, d in by_range.items():
        d['range'] = label
        d['win_rate'] = d['wins'] / d['bets'] if d['bets'] > 0 else 0
        d['roi'] = d['pnl'] / d['stake'] if d['stake'] > 0 else 0
        results.append(d)
    
    return results


def analyze_overlap(ds_bets, wc_bets):
    """Analyze overlapping matches between Deepseek and WorldCup"""
    # Build lookup by match key
    wc_by_match = defaultdict(list)
    for b in wc_bets:
        key = f"{b['home']}|{b['away']}|{b['date']}"
        wc_by_match[key].append(b)
    
    overlaps = []
    ds_only_wins = 0
    wc_only_wins = 0
    both_wins = 0
    both_losses = 0
    
    for ds in ds_bets:
        if ds['result'] is None:
            continue
        key = f"{ds['home']}|{ds['away']}|{ds['date']}"
        wc_matches = wc_by_match.get(key, [])
        
        if wc_matches:
            wc_total_pnl = sum(b['pnl'] for b in wc_matches)
            overlaps.append({
                'date': ds['date'],
                'home': ds['home'],
                'away': ds['away'],
                'ds_direction': ds['direction'],
                'ds_result': ds['result'],
                'ds_pnl': ds['pnl'],
                'wc_bets': len(wc_matches),
                'wc_total_pnl': wc_total_pnl,
            })
            if ds['result'] == 1 and wc_total_pnl > 0:
                both_wins += 1
            elif ds['result'] == 1 and wc_total_pnl <= 0:
                ds_only_wins += 1
            elif ds['result'] == -1 and wc_total_pnl > 0:
                wc_only_wins += 1
            else:
                both_losses += 1
    
    return {
        'overlaps': overlaps,
        'total_overlapping_matches': len(set(o['date']+o['home']+o['away'] for o in overlaps)),
        'both_wins': both_wins,
        'ds_only_wins': ds_only_wins,
        'wc_only_wins': wc_only_wins,
        'both_losses': both_losses,
    }


# ============================================================
# 7. DEEPSEEK CONFIDENCE ANALYSIS
# ============================================================

def analyze_confidence_levels(ds_bets):
    by_conf = defaultdict(lambda: {'bets': 0, 'wins': 0, 'placed': 0, 'won_placed': 0, 'pnl': 0.0})
    
    for b in ds_bets:
        conf = b['confidence'] if b['confidence'] else 0
        level = '5' if conf == 5 else ('4' if conf == 4 else '3')
        by_conf[level]['bets'] += 1
        if b['result'] == 1:
            by_conf[level]['wins'] += 1
        if b['wager'] is not None and b['wager'] > 0:
            by_conf[level]['placed'] += 1
            by_conf[level]['pnl'] += b['pnl']
            if b['result'] == 1:
                by_conf[level]['won_placed'] += 1
    
    results = []
    for level in ['5', '4', '3']:
        d = by_conf[level]
        d['level'] = level
        d['pred_win_rate'] = d['wins'] / d['bets'] if d['bets'] else 0
        d['actual_win_rate'] = d['won_placed'] / d['placed'] if d['placed'] else 0
        results.append(d)
    
    return results


# ============================================================
# MAIN
# ============================================================

def main():
    filepath = '/Users/Kenny/OneDrive/WorldCup/documents/WorldCup.xlsx'
    print("=" * 70)
    print("  WorldCup 交叉分析報告")
    print("=" * 70)
    
    ds_bets, wc_bets = load_data(filepath)
    
    # Filter to bets with actual results only
    ds_with_result = [b for b in ds_bets if b['result'] is not None]
    
    print(f"\n📊 資料載入:")
    print(f"  Deepseek 分析: {len(ds_bets)} 行, {len(ds_with_result)} 有結果")
    print(f"  WorldCup 投注: {len(wc_bets)} 筆")
    
    # ========================================================
    # SECTION A: Kelly Formula Comparison
    # ========================================================
    print("\n" + "=" * 70)
    print("  A. Kelly 公式策略比較")
    print("=" * 70)
    
    strategies = [
        backtest_existing_kelly(ds_with_result),
        backtest_improved_kelly(ds_with_result, kelly_fraction=0.25, window=20, warmup=15),
        backtest_improved_kelly(ds_with_result, kelly_fraction=0.125, window=20, warmup=15),
        backtest_improved_kelly(ds_with_result, kelly_fraction=0.25, window=30, warmup=20),
        backtest_fixed_stake(ds_with_result, stake=20),
        backtest_fixed_stake(ds_with_result, stake=10),
    ]
    
    print(f"\n{'策略':<30} {'總盈虧':>8} {'下注數':>6} {'勝率':>7} {'ROI':>8} {'最終本金':>10}")
    print("-" * 70)
    for s in strategies:
        print(f"{s['name']:<30} {s['total_pnl']:>+8.1f} {s['bets_placed']:>6} {s['win_rate']:>6.1%} {s['roi']:>7.1%} {s['final_bankroll']:>10.1f}")
    
    # ========================================================
    # SECTION B: Monte Carlo
    # ========================================================
    print("\n" + "=" * 70)
    print("  B. 蒙地卡羅模擬 (10,000 次隨機排序)")
    print("=" * 70)
    
    mc_existing = monte_carlo_simulation(ds_with_result, strategy='existing', n_simulations=10000)
    mc_improved = monte_carlo_simulation(ds_with_result, strategy='improved', n_simulations=10000)
    
    for mc, name in [(mc_existing, '現有 Kelly'), (mc_improved, '改良 Kelly (frac=0.25)')]:
        print(f"\n  {name}:")
        print(f"    平均最終本金: ${mc['mean']:.1f}")
        print(f"    中位數:        ${mc['median']:.1f}")
        print(f"    最差 5%:       ${mc['p5']:.1f}")
        print(f"    最佳 5%:       ${mc['p95']:.1f}")
        print(f"    P(獲利):        {mc['prob_profit']:.1%}")
        print(f"    P(破產<30):     {mc['prob_ruin']:.2%}")
    
    # ========================================================
    # SECTION C: Bet Type Analysis
    # ========================================================
    print("\n" + "=" * 70)
    print("  C1. 投注類別盈利能力 (WorldCup 實際投注)")
    print("=" * 70)
    
    bt_results = analyze_bet_types(wc_bets)
    print(f"\n{'類別':<20} {'筆數':>5} {'勝率':>7} {'總投注':>8} {'盈虧':>8} {'ROI':>8}")
    print("-" * 60)
    for d in bt_results:
        print(f"{d['type']:<20} {d['bets']:>5} {d['win_rate']:>6.1%} {d['stake']:>8.0f} {d['pnl']:>+8.1f} {d['roi']:>7.1%}")
    
    print("\n" + "=" * 70)
    print("  C2. 賠率區間分析 (WorldCup)")
    print("=" * 70)
    
    odds_results = analyze_by_odds_range(wc_bets)
    print(f"\n{'賠率區間':<12} {'筆數':>5} {'勝率':>7} {'總投注':>8} {'盈虧':>8} {'ROI':>8}")
    print("-" * 60)
    for d in odds_results:
        print(f"{d['range']:<12} {d['bets']:>5} {d['win_rate']:>6.1%} {d['stake']:>8.0f} {d['pnl']:>+8.1f} {d['roi']:>7.1%}")
    
    print("\n" + "=" * 70)
    print("  C3. Deepseek 信心等級分析")
    print("=" * 70)
    
    conf_results = analyze_confidence_levels(ds_bets)
    print(f"\n{'信心':<6} {'總推薦':>6} {'預測勝率':>8} {'實際下注':>8} {'實際勝率':>8} {'盈虧':>8}")
    print("-" * 55)
    for d in conf_results:
        print(f"{d['level']:<6} {d['bets']:>6} {d['pred_win_rate']:>7.1%} {d['placed']:>8} {d['actual_win_rate']:>7.1%} {d['pnl']:>+8.1f}")
    
    # ========================================================
    # SECTION D: Overlap Analysis
    # ========================================================
    print("\n" + "=" * 70)
    print("  D. 重疊賽事分析")
    print("=" * 70)
    
    overlap_data = analyze_overlap(ds_with_result, wc_bets)
    print(f"\n  重疊比賽場次: {overlap_data['total_overlapping_matches']}")
    print(f"  DS贏+你贏: {overlap_data['both_wins']}")
    print(f"  DS贏+你輸: {overlap_data['ds_only_wins']}")
    print(f"  DS輸+你贏: {overlap_data['wc_only_wins']}")
    print(f"  兩邊都輸:   {overlap_data['both_losses']}")
    
    # Print top overlaps where DS and user diverge
    print("\n  DS與用戶結果分歧的重疊場次 (前10):")
    print(f"  {'日期':<12} {'比賽':<25} {'DS推薦':<32} {'DS':>4} {'你':>8}")
    print("  " + "-" * 85)
    divergent = [(o, abs(o['ds_pnl'] - o['wc_total_pnl'])) for o in overlap_data['overlaps']
                 if o['ds_pnl'] != 0 or o['wc_total_pnl'] != 0]
    divergent.sort(key=lambda x: abs(x[0]['wc_total_pnl']), reverse=True)
    for o, _ in divergent[:10]:
        match = f"{o['home']}vs{o['away']}"
        ds_label = '✅' if o['ds_result'] == 1 else '❌'
        print(f"  {o['date']:<12} {match:<25} {o['ds_direction']:<32} {ds_label:<4} {o['wc_total_pnl']:>+8.1f}")
    
    # ========================================================
    # Summary
    # ========================================================
    print("\n" + "=" * 70)
    print("  總結")
    print("=" * 70)
    
    wc_total_pnl = sum(b['pnl'] for b in wc_bets) + sum(b.get('cashout', 0) for b in wc_bets)
    wc_total_stake = sum(b['stake'] for b in wc_bets)
    wc_wins = sum(1 for b in wc_bets if b['result'] == 1)
    
    print(f"""
    WorldCup 手動投注:
      - {len(wc_bets)} 筆, 總投注 ${wc_total_stake:.0f}, 勝率 {wc_wins/len(wc_bets):.1%}
      - 總盈虧 ${wc_total_pnl:+.1f}, ROI {wc_total_pnl/wc_total_stake:+.1%}
    
    Deepseek 現有 Kelly:
      - 策略: {strategies[0]['name']}, 盈虧 ${strategies[0]['total_pnl']:+.1f}
    
    Deepseek 改良 Kelly:
      - 策略: {strategies[1]['name']}, 盈虧 ${strategies[1]['total_pnl']:+.1f}
      - 蒙地卡羅: 中位數 ${mc_improved['median']:.1f}, P(獲利)={mc_improved['prob_profit']:.1%}
    """)
    
    # Export summary JSON for reference
    summary = {
        'strategies': [{k: v for k, v in s.items() if k != 'equity_curve'} for s in strategies],
        'monte_carlo_existing': {k: v for k, v in mc_existing.items() if k not in ('all_results', 'sample_paths')},
        'monte_carlo_improved': {k: v for k, v in mc_improved.items() if k not in ('all_results', 'sample_paths')},
        'bet_type_analysis': bt_results,
        'odds_range_analysis': odds_results,
        'confidence_analysis': conf_results,
        'overlap_analysis': {k: v for k, v in overlap_data.items() if k != 'overlaps'},
    }
    
    with open('/Users/Kenny/Desktop/WorldCup/analysis_summary.json', 'w') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    
    print("  JSON summary saved to analysis_summary.json")
    return ds_bets, wc_bets


if __name__ == '__main__':
    random.seed(42)  # Reproducible
    main()
