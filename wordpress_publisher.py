import os
import json
import gspread
import requests
import base64
from google.oauth2.service_account import Credentials
import datetime
import pandas as pd
import random

def get_sheet_data():
    """Googleスプレッドシートからデータを取得する"""
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    
    # --- GCP認証情報の読み込み ---
    creds_json = None
    env_sa = os.environ.get('GCP_SERVICE_ACCOUNT')
    
    if env_sa:
        try:
            creds_json = json.loads(env_sa)
        except json.JSONDecodeError as e:
            print(f"JSON Decode Error: {e}")
    
    if not creds_json and os.path.exists('service_account.json'):
        with open('service_account.json', 'r') as f:
            creds_json = json.load(f)

    if not creds_json:
        raise Exception("GCP認証情報が見つかりません。SecretsのGCP_SERVICE_ACCOUNTを確認してください。")

    creds = Credentials.from_service_account_info(creds_json, scopes=scope)
    gc = gspread.authorize(creds)

    # --- シートを開く ---
    sheet_url = os.environ.get('SHEET_URL')
    if not sheet_url:
        raise Exception("SHEET_URLが設定されていません")

    wb = gc.open_by_url(sheet_url)
    worksheet = wb.worksheet("業種分析")
    
    # 全データを取得
    data = worksheet.get_all_records()
    return data

def process_data_for_chart(data):
    """
    取得したデータを加工する
    """
    if not data:
        return None, None, None

    # DataFrame化
    df = pd.DataFrame(data)
    
    # 日付型変換とソート
    df['日付'] = pd.to_datetime(df['日付'])
    df = df.sort_values(['日付', 'コード'])

    # --- 1. 最新データの抽出 (パネル用) ---
    # 修正: 全体でのMax日付ではなく、各コードごとの最新行を取得する（更新ズレによる欠落防止）
    latest_df = df.sort_values('日付').groupby('コード').tail(1).copy()
    
    # 表示順をコード順またはセクター名順に整える（ここではコード順）
    latest_df = latest_df.sort_values('コード')

    # --- 2. 時系列データの作成 (チャート用) ---
    # ピボットテーブル作成 (行:日付, 列:セクター名, 値:現在値)
    pivot_df = df.pivot(index='日付', columns='セクター名', values='現在値')
    
    # 直近300日分を取得
    pivot_df = pivot_df.tail(300)
    
    # データが空でなければ指数化 (起点=100)
    if not pivot_df.empty:
        base_prices = pivot_df.iloc[0]
        # 0除算回避
        normalized_df = pivot_df.div(base_prices).mul(100).round(2)
    else:
        normalized_df = pivot_df

    # Chart.js用に日付ラベルを文字列リスト化
    chart_labels = normalized_df.index.strftime('%Y/%m/%d').tolist()
    
    # Chart.js用にデータセットリスト化
    chart_datasets = []
    
    # 色のリスト (視認性の高い色パレット)
    colors = [
        '#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231', 
        '#911eb4', '#46f0f0', '#f032e6', '#bcf60c', '#fabebe', 
        '#008080', '#e6beff', '#9a6324', '#fffac8', '#800000', 
        '#aaffc3', '#808000', '#ffd8b1', '#000075', '#808080'
    ]
    
    for i, column in enumerate(normalized_df.columns):
        color = colors[i % len(colors)]
        dataset = {
            "label": column,
            "data": normalized_df[column].fillna(method='ffill').tolist(), # 欠損値は前日埋め
            "borderColor": color,
            "backgroundColor": color,
            "borderWidth": 1.5,
            "pointRadius": 0,
            "pointHoverRadius": 4,
            "fill": False,
            "tension": 0.1
        }
        chart_datasets.append(dataset)

    return latest_df, chart_labels, chart_datasets

def generate_html_content(latest_df, chart_labels, chart_datasets):
    """HTMLコンテンツ（パネル＋Chart.jsスクリプト）を生成"""
    
    if latest_df is None or latest_df.empty:
        return "<p>データがありません。</p>"

    # 更新日時（データの最新日付を使用）
    last_update_str = latest_df['日付'].max().strftime('%Y-%m-%d')

    # 一意なID生成（キャッシュ対策）
    chart_id = f"sectorChart_{random.randint(1000, 9999)}"

    # --- CSS (インライン) ---
    style_grid = "display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 30px;"
    # パネルは白背景、影付きで見やすく
    style_card = "padding: 12px; border-radius: 6px; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border: 1px solid #eee;"

    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 0 auto;">
        <p style="text-align: right; font-size: 0.8rem; color: #666; margin-bottom: 10px;">データ更新日: {last_update_str}</p>
        
        <!-- パネルエリア -->
        <div style="{style_grid}">
    """

    for _, row in latest_df.iterrows():
        sector = row['セクター名']
        change = float(row['前日比(%)'])
        rsi = float(row['RSI'])
        bb = float(row['BB%B(過熱)'])
        
        # --- ステータス判定 ---
        # 背景色は白固定。文字と枠線でステータスを表示
        status_text = "通常"
        status_style = "color: #666; font-size: 0.75rem; background: #f0f0f0; padding: 2px 6px; border-radius: 3px;"
        
        # 過熱判定
        if rsi >= 70 or bb > 1.0:
            status_text = "🔥 過熱"
            status_style = "color: #d32f2f; font-weight: bold; font-size: 0.75rem; background: #ffebee; padding: 2px 6px; border-radius: 3px; border: 1px solid #ffcdd2;"
            
        # 割安判定
        elif rsi <= 30 or bb < 0:
            status_text = "❄️ 割安"
            status_style = "color: #1565c0; font-weight: bold; font-size: 0.75rem; background: #e3f2fd; padding: 2px 6px; border-radius: 3px; border: 1px solid #bbdefb;"

        # 前日比の文字色
        change_color = "#d32f2f" if change > 0 else ("#1976d2" if change < 0 else "#333")
        sign = "+" if change > 0 else ""
        
        html += f"""
        <div style="{style_card}">
            <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 5px;">
                <div style="font-weight: bold; font-size: 0.9rem; color: #333;">{sector}</div>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: flex-end;">
                <div style="font-size: 1.4rem; font-weight: bold; color: {change_color}; line-height: 1;">
                    {sign}{change}<span style="font-size: 0.8rem;">%</span>
                </div>
                <div style="{status_style}">{status_text}</div>
            </div>
        </div>
        """

    # PythonデータをJSON文字列化してJSに埋め込む
    json_labels = json.dumps(chart_labels)
    json_datasets = json.dumps(chart_datasets)

    html += f"""
        </div>
        <!-- チャートエリア -->
        <h3 style="font-size: 1.1rem; border-bottom: 2px solid #333; padding-bottom: 5px; margin-top: 40px; margin-bottom: 15px;">📊 300日推移チャート (起点=100)</h3>
        <p style="font-size: 0.8rem; color: #666; margin-bottom: 15px;">
            ※300営業日前を100とした指数チャートです。<br>
            ※凡例の四角(■)をタップすると、その業種の表示/非表示を切り替えられます。
        </p>
        
        <!-- Chart.js CDN -->
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        
        <div style="position: relative; width: 100%; height: 500px; border: 1px solid #eee; border-radius: 4px; padding: 5px;">
            <canvas id="{chart_id}"></canvas>
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
        raw_data = get_sheet_data()
        
        print("データを加工中(パネル＆チャート)...")
        latest_df, chart_labels, chart_datasets = process_data_for_chart(raw_data)
        
        print("HTMLコンテンツ生成中...")
        html_content = generate_html_content(latest_df, chart_labels, chart_datasets)
        
        update_wordpress(html_content)
        
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
