import os
import json
import requests
import base64
import datetime
import pandas as pd
import random

# gspread や google.oauth2 などのスプレッドシート関連ライブラリは不要になりました

def get_analysis_data(file_path='sector_data.json'):
    """
    前工程(sector_analysis.py)で生成されたJSONファイルからデータを読み込む
    スプレッドシートを経由しないため、認証不要かつ高速
    """
    if not os.path.exists(file_path):
        # ファイルがない場合はエラー
        raise FileNotFoundError(f"データファイル '{file_path}' が見つかりません。sector_analysis.py でJSON出力が行われているか確認してください。")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except Exception as e:
        raise Exception(f"JSONファイルの読み込みに失敗しました: {e}")

def process_data_for_chart(data):
    """
    取得したデータを加工する
    """
    if not data:
        return None, None, None, None

    # DataFrame化
    df = pd.DataFrame(data)
    
    # 日付型変換
    if '日付' in df.columns:
        df['日付'] = pd.to_datetime(df['日付'])
    else:
        # 日付カラムがない場合の安全策（ありえないはずだが）
        return None, None, None, None

    # --- 重複データの排除 ---
    sort_cols = ['日付', 'コード']
    if '更新日時' in df.columns:
        sort_cols.append('更新日時')
        
    df = df.sort_values(sort_cols)
    df = df.drop_duplicates(subset=['日付', 'コード'], keep='last')

    # --- 1. 最新データの抽出 (パネル用) ---
    # 各コードごとの最新行を取得
    latest_df = df.sort_values('日付').groupby('コード').tail(1).copy()
    latest_df = latest_df.sort_values('コード')

    # --- 2. 時系列データの作成 (チャート用) ---
    pivot_df = df.pivot(index='日付', columns='セクター名', values='現在値')
    pivot_df = pivot_df.tail(300)
    
    if not pivot_df.empty:
        base_prices = pivot_df.iloc[0]
        normalized_df = pivot_df.div(base_prices).mul(100).round(2)
    else:
        normalized_df = pivot_df

    # --- 3. 過熱ランキングTop3の作成 ---
    overheated_sectors = []
    
    if not latest_df.empty and not normalized_df.empty:
        for _, row in latest_df.iterrows():
            sector = row['セクター名']
            rsi = float(row['RSI'])
            bb = float(row['BB%B(過熱)'])
            
            # 過熱条件
            if rsi >= 70 or bb > 1.0:
                current_index_val = 0
                if sector in normalized_df.columns:
                    current_index_val = normalized_df[sector].iloc[-1]
                
                overheated_sectors.append({
                    'sector': sector,
                    'index_val': current_index_val,
                    'rsi': rsi
                })
        
        overheated_sectors.sort(key=lambda x: x['index_val'], reverse=True)
        overheated_top3 = overheated_sectors[:3]
    else:
        overheated_top3 = []

    # Chart.js用データ
    chart_labels = normalized_df.index.strftime('%Y/%m/%d').tolist()
    chart_datasets = []
    
    # --- 色のリスト (High Contrast) ---
    colors = [
        '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', 
        '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
        '#393b79', '#637939', '#8c6d31', '#843c39', '#7b4173',
        '#5254a3', '#8ca252', '#bd9e39', '#ad494a', '#a55194'
    ]
    
    for i, column in enumerate(normalized_df.columns):
        color = colors[i % len(colors)]
        dataset = {
            "label": column,
            "data": normalized_df[column].fillna(method='ffill').tolist(),
            "borderColor": color,
            "backgroundColor": color,
            "borderWidth": 2, # 線を少し太くして見やすく
            "pointRadius": 0,
            "pointHoverRadius": 4,
            "fill": False,
            "tension": 0.1
        }
        chart_datasets.append(dataset)

    return latest_df, chart_labels, chart_datasets, overheated_top3

def generate_html_content(latest_df, chart_labels, chart_datasets, overheated_top3):
    """HTMLコンテンツ（パネル＋Chart.jsスクリプト）を生成"""
    
    if latest_df is None or latest_df.empty:
        return "<p>データがありません。</p>"

    # 更新日時
    last_update_str = latest_df['日付'].max().strftime('%Y-%m-%d')
    chart_id = f"sectorChart_{random.randint(1000, 9999)}"

    # --- CSS (インライン) ---
    style_grid = "display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 20px;"
    style_card = "padding: 12px; border-radius: 6px; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border: 1px solid #eee;"

    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 0 auto;">
        <p style="text-align: right; font-size: 0.8rem; color: #666; margin-bottom: 10px;">データ更新日: {last_update_str}</p>
        
        <h3 style="font-size: 1.1rem; margin-bottom: 15px; color: #333;">短期の過熱割安判定パネル</h3>

        <div style="{style_grid}">
    """

    for _, row in latest_df.iterrows():
        sector = row['セクター名']
        change = float(row['前日比(%)'])
        rsi = float(row['RSI'])
        bb = float(row['BB%B(過熱)'])
        
        # --- ステータス判定 (変更箇所) ---
        
        # デフォルト（通常）: 元のままに近い控えめな表示
        status_text = "通常"
        status_style = "color: #aaa; font-size: 0.7rem; background: #f7f7f7; padding: 2px 6px; border-radius: 4px; display: inline-block;"
        
        # 過熱判定: 文字サイズ大(1.1rem)、太字(900)、赤背景、白文字、影付き
        if rsi >= 70 or bb > 1.0:
            status_text = "過熱"
            status_style = (
                "color: #fff; font-weight: 900; font-size: 1.1rem; "
                "background: #d32f2f; padding: 6px 12px; border-radius: 6px; "
                "box-shadow: 0 3px 6px rgba(211, 47, 47, 0.4); "
                "display: inline-block; transform: scale(1.05);"
            )
            
        # 割安判定: 文字サイズ大(1.1rem)、太字(900)、青背景、白文字、影付き
        elif rsi <= 30 or bb < 0:
            status_text = "割安"
            status_style = (
                "color: #fff; font-weight: 900; font-size: 1.1rem; "
                "background: #1976d2; padding: 6px 12px; border-radius: 6px; "
                "box-shadow: 0 3px 6px rgba(25, 118, 210, 0.4); "
                "display: inline-block; transform: scale(1.05);"
            )

        change_color = "#d32f2f" if change > 0 else ("#1976d2" if change < 0 else "#333")
        sign = "+" if change > 0 else ""
        
        # パネルHTML (変更箇所: align-itemsをcenterにして配置調整)
        html += f"""
        <div style="{style_card}">
            <div style="font-weight: bold; font-size: 0.95rem; color: #333; margin-bottom: 8px;">{sector}</div>
            
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div>
                    <div style="font-size: 0.7rem; color: #888; margin-bottom: 2px;">ETF価格前日比</div>
                    <div style="font-size: 1.4rem; font-weight: bold; color: {change_color}; line-height: 1;">
                        {sign}{change}<span style="font-size: 0.8rem;">%</span>
                    </div>
                </div>
                <div style="text-align: right;">
                    <div style="{status_style}">{status_text}</div>
                </div>
            </div>
            
            <div style="font-size: 0.75rem; color: #666; border-top: 1px solid #f9f9f9; padding-top: 6px; display: flex; justify-content: space-between;">
                <span>RSI(14): <strong>{rsi:.1f}</strong></span>
                <span>BB: <strong>{bb:.2f}</strong></span>
            </div>
        </div>
        """

    # パネル下の説明エリア
    html += """
        </div>
        <div style="font-size: 0.8rem; color: #666; background: #f9f9f9; padding: 12px; border-radius: 6px; margin-bottom: 40px; border: 1px solid #eee;">
            <strong>【パネルの見方・判定条件】</strong><br>
            <ul style="margin: 5px 0 0 20px; padding: 0;">
                <li><strong>ETF価格前日比</strong>：東証上場のTOPIX-17シリーズETF終値の前日比です。</li>
                <li><strong>過熱</strong>：RSI(14日)が70以上、またはボリンジャーバンド(20日/2σ)の%Bが1.0(バンド上限)を超えた場合。</li>
                <li><strong>割安</strong>：RSI(14日)が30以下、またはボリンジャーバンド(20日/2σ)の%Bが0(バンド下限)を下回った場合。</li>
                <li><strong>BB</strong>：ボリンジャーバンド%B値。1.0以上でバンド上限突破、0以下でバンド下限割れを示唆します。</li>
            </ul>
        </div>
    """

    json_labels = json.dumps(chart_labels)
    json_datasets = json.dumps(chart_datasets)

    # 過熱Top3
    top3_html = ""
    if overheated_top3:
        top3_html += '<div style="background: #fff3e0; padding: 12px; border-radius: 6px; margin-bottom: 20px; border: 1px solid #ffe0b2;">'
        top3_html += '<div style="font-weight:bold; color:#e65100; margin-bottom:8px; font-size:0.95rem;">上昇トレンド × 過熱シグナル発生中 (Top 3)</div>'
        top3_html += '<ul style="margin: 0; padding-left: 20px; color: #333; font-size: 0.9rem;">'
        for item in overheated_top3:
            idx_val = round(item['index_val'], 1)
            top3_html += f"<li><strong>{item['sector']}</strong> <span style='color:#666; font-size:0.85rem;'>(300日指数: {idx_val} / RSI: {item['rsi']})</span></li>"
        top3_html += '</ul></div>'
    else:
        top3_html += '<div style="background: #f9f9f9; padding: 10px; border-radius: 6px; margin-bottom: 20px; border: 1px solid #eee; color: #666; font-size: 0.9rem;">現在、過熱圏にある業種はありません。</div>'

    html += f"""
        <h3 style="font-size: 1.1rem; margin-top: 40px; margin-bottom: 15px; color: #333;">長期の過熱割安判定チャート(起点100)</h3>
        
        {top3_html}
        
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        
        <div style="position: relative; width: 100%; height: 500px; border: 1px solid #eee; border-radius: 4px; padding: 5px;">
            <canvas id="{chart_id}"></canvas>
        </div>
        
        <div style="font-size: 0.8rem; color: #666; background: #f9f9f9; padding: 12px; border-radius: 6px; margin-top: 15px; border: 1px solid #eee;">
            <strong>【チャートの仕様】</strong><br>
            <ul style="margin: 5px 0 0 20px; padding: 0;">
                <li>直近300営業日前の終値を「100」として指数化したパフォーマンス推移です。</li>
                <li>グラフ上の凡例の四角(●)をタップすると、その業種の表示/非表示を切り替えられます。</li>
                <li>チャート上の点をタップすると、詳細な日付と指数値が表示されます。</li>
            </ul>
        </div>
        
        <script>
        (function() {{
            const ctx = document.getElementById('{chart_id}').getContext('2d');
            const myChart = new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: {json_labels},
                    datasets: {json_datasets}
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {{
                        mode: 'index',
                        intersect: false,
                    }},
                    plugins: {{
                        legend: {{
                            position: 'bottom',
                            labels: {{
                                usePointStyle: true,
                                boxWidth: 8,
                                padding: 15,
                                font: {{ size: 11 }}
                            }}
                        }},
                        tooltip: {{
                            enabled: true,
                            position: 'nearest'
                        }}
                    }},
                    scales: {{
                        y: {{
                            title: {{ display: true, text: '指数' }},
                            grid: {{ color: '#f0f0f0' }}
                        }},
                        x: {{
                            grid: {{ display: false }},
                            ticks: {{ maxTicksLimit: 10 }}
                        }}
                    }},
                    elements: {{
                        point: {{
                            radius: 0,
                            hitRadius: 10,
                            hoverRadius: 5
                        }}
                    }}
                }}
            }});
        }})();
        </script>
    </div>
    """
    
    return html

def get_wordpress_config():
    """設定取得"""
    config = {
        "url": os.environ.get("WP_URL"),
        "user": os.environ.get("WP_USER"),
        "password": os.environ.get("WP_PASSWORD"),
        "page_id": os.environ.get("WP_PAGE_ID"),
    }
    tofu_secret = os.environ.get("TOFU_WORDPRESS")
    if tofu_secret:
        for line in tofu_secret.splitlines():
            line = line.strip()
            if not line or "=" not in line: continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key == "WP_URL": config["url"] = value
            elif key == "WP_USER": config["user"] = value
            elif key == "WP_PASSWORD": config["password"] = value
            elif key == "WP_PAGE_ID": config["page_id"] = value
    return config

def update_wordpress(content):
    """WordPress更新"""
    wp_config = get_wordpress_config()
    wp_url = wp_config["url"]
    wp_user = wp_config["user"]
    wp_pass = wp_config["password"]
    page_id = wp_config["page_id"]

    if not all([wp_url, wp_user, wp_pass, page_id]):
        print("エラー: WordPress設定不足")
        return

    api_url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/pages/{page_id}"
    credentials = f"{wp_user}:{wp_pass}"
    token = base64.b64encode(credentials.encode())
    headers = {
        'Authorization': f'Basic {token.decode("utf-8")}',
        'Content-Type': 'application/json'
    }
    payload = {'content': content}

    print(f"WordPress ({api_url}) へ投稿中...")
    response = requests.post(api_url, headers=headers, json=payload)

    if response.status_code == 200:
        print("投稿成功！")
    else:
        print(f"投稿失敗: {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    try:
        print("データを取得中...")
        # ファイルからデータを取得する形に変更
        raw_data = get_analysis_data()
        
        print("データを加工中(パネル＆チャート)...")
        latest_df, chart_labels, chart_datasets, overheated_top3 = process_data_for_chart(raw_data)
        
        print("HTMLコンテンツ生成中...")
        html_content = generate_html_content(latest_df, chart_labels, chart_datasets, overheated_top3)
        
        update_wordpress(html_content)
        
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
