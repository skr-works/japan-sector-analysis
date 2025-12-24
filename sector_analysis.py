import yfinance as yf
import pandas as pd
import numpy as np
import json
import datetime
import os
from concurrent.futures import ThreadPoolExecutor

# --- 設定: TOPIX-17業種 ETFリスト ---
SECTOR_ETFS = {
    "1617": "食品",
    "1618": "エネルギー・資源",
    "1619": "建設・資材",
    "1620": "素材・化学",
    "1621": "医薬品",
    "1622": "自動車・輸送機",
    "1623": "鉄鋼・非鉄",
    "1624": "機械",
    "1625": "電機・精密",
    "1626": "情報通信・サービス",
    "1627": "電力・ガス",
    "1628": "運輸・物流",
    "1629": "商社・卸売",
    "1630": "小売",
    "1631": "銀行",
    "1632": "金融(除く銀行)",
    "1633": "不動産"
}

def calculate_technical_indicators(df):
    """データフレーム全体に対してテクニカル指標を一括計算する"""
    df = df.copy()
    
    # 1. 移動平均乖離率
    df['ma5'] = df['Close'].rolling(window=5).mean()
    df['ma25'] = df['Close'].rolling(window=25).mean()
    df['ma75'] = df['Close'].rolling(window=75).mean()
    
    df['diff_short'] = ((df['Close'] - df['ma5']) / df['ma5']) * 100
    df['diff_mid'] = ((df['Close'] - df['ma25']) / df['ma25']) * 100
    df['diff_long'] = ((df['Close'] - df['ma75']) / df['ma75']) * 100

    # 2. RSI (14日)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # 3. ボリンジャーバンド %B (20日, 2σ)
    df['bb_ma'] = df['Close'].rolling(window=20).mean()
    df['bb_std'] = df['Close'].rolling(window=20).std()
    df['bb_up'] = df['bb_ma'] + (df['bb_std'] * 2)
    df['bb_low'] = df['bb_ma'] - (df['bb_std'] * 2)
    
    bb_range = df['bb_up'] - df['bb_low']
    df['bb_pct_b'] = np.where(bb_range == 0, 0, (df['Close'] - df['bb_low']) / bb_range)

    # 4. 出来高倍率 (直近5日平均との比較)
    df['vol_ma5'] = df['Volume'].rolling(window=5).mean()
    df['vol_ratio'] = np.where(df['vol_ma5'] == 0, 0, df['Volume'] / df['vol_ma5'])

    # 5. 前日比
    df['change_pct'] = df['Close'].pct_change() * 100

    return df

def get_sector_data(code, name):
    """
    指定銘柄のデータを取得・計算し、辞書のリストとして返す
    """
    ticker = f"{code}.T"
    try:
        stock = yf.Ticker(ticker)
        # 過去2年分取得
        hist = stock.history(period="2y")
        
        if hist.empty:
            return []

        # 指標計算
        df = calculate_technical_indicators(hist)
        
        # NaNを除去し、直近1年(250営業日)分に絞る
        df = df.dropna().tail(250) 

        # 行データ作成用ヘルパー関数 (辞書型を返す)
        def make_row(date_idx, row):
            return {
                "コード": code,
                "セクター名": name,
                "日付": date_idx.strftime('%Y-%m-%d'),
                "現在値": round(row['Close'], 1),
                "前日比(%)": round(row['change_pct'], 2),
                "短期(5日乖離)": round(row['diff_short'], 2),
                "中期(25日乖離)": round(row['diff_mid'], 2),
                "長期(75日乖離)": round(row['diff_long'], 2),
                "RSI": round(row['rsi'], 1),
                "BB%B(過熱)": round(row['bb_pct_b'], 2),
                "出来高倍率": round(row['vol_ratio'], 2),
                "更新日時": datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
            }

        results = []
        # 過去すべての行をリスト化 (日付の新しい順)
        for date_idx, row in df.iloc[::-1].iterrows():
            results.append(make_row(date_idx, row))
            
        return results

    except Exception as e:
        print(f"Error {code}: {e}")
        return []

def main():
    print("セクターデータの取得を開始します...")

    # --- データ取得 (並列処理) ---
    all_rows = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(get_sector_data, code, name) for code, name in SECTOR_ETFS.items()]
        for future in futures:
            res = future.result()
            if res:
                all_rows.extend(res)

    # ソート: 日付(新しい順) > コード順
    all_rows.sort(key=lambda x: (x['日付'], x['コード']), reverse=True)

    # --- JSONファイルへの保存 ---
    output_file = 'sector_data.json'
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_rows, f, ensure_ascii=False, indent=2)
        
        print(f"データ取得完了: {len(all_rows)}件のデータを '{output_file}' に保存しました。")
        
    except Exception as e:
        print(f"ファイル保存エラー: {e}")
        exit(1)

if __name__ == "__main__":
    main()
