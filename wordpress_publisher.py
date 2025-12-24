import os
import json
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import requests
import base64
from datetime import datetime

# --- 設定 ---
SHEET_NAME = "業種分析"

def get_sheet_data():
    """スプレッドシートからデータを取得してDataFrameにする"""
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    
    # 認証情報の読み込み
    if 'GCP_SERVICE_ACCOUNT' in os.environ:
        creds_json = json.loads(os.environ['GCP_SERVICE_ACCOUNT'])
    elif os.path.exists('service_account.json'):
        with open('service_account.json', 'r') as f:
            creds_json = json.load(f)
    else:
        raise Exception("GCP認証情報が見つかりません")

    creds = Credentials.from_service_account_info(creds_json, scopes=scope)
    gc = gspread.authorize(creds)
    
    sheet_url = os.environ.get('SHEET_URL')
    if not sheet_url:
        # ローカルテスト用フォールバック
        sheet_url = "https://docs.google.com/spreadsheets/d/11Pp6Y8Eh-xNGyp6npiVpteuExno5pLigEkkmlBq1iFE/edit"

    wb = gc.open_by_url(sheet_url)
    ws = wb.worksheet(SHEET_NAME)
    
    # 全データを取得してDataFrame化
    data = ws.get_all_values()
    df = pd.DataFrame(data[1:], columns=data[0])
    
    # 数値型に変換
    numeric_cols = ["現在値", "前日比(%)", "短期(5日乖離)", "中期(25日乖離)", "長期(75日乖離)", "RSI", "BB%B(過熱)", "出来高倍率"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        
    return df

def generate_html_content(df):
    """WordPressに投稿するHTMLとJavaScript(Chart.js)を生成する"""
    
    # 最新日付のデータのみ抽出
    latest_date = df['日付'].iloc[0]
    df_latest = df[df['日付'] == latest_date].copy()
    
    # 日付表示
    html = f"<h3>📅 基準日: {latest_date} のセクター分析</h3>"
    html += f"<p>最終更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>"

    # --- 1. ヒートマップテーブルの生成 ---
    html += "<h4>📊 セクター別ヒートマップ</h4>"
    html += """
    <style>
        .sector-table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
        .sector-table th, .sector-table td { border: 1px solid #ddd; padding: 8px; text-align: center; }
        .sector-table th { background-color: #f2f2f2; }
        .heat-red { background-color: #ffcccc; color: #cc0000; font-weight: bold; }
        .heat-blue { background-color: #e6f2ff; color: #0066cc; font-weight: bold; }
        .heat-yellow { background-color: #fff9c4; font-weight: bold; }
    </style>
    <div style="overflow-x:auto;">
    <table class="sector-table">
        <thead>
            <tr>
                <th>セクター</th>
                <th>現在値</th>
                <th>前日比</th>
                <th>短期(5日)</th>
                <th>中期(25日)</th>
                <th>RSI</th>
                <th>過熱感(BB)</th>
            </tr>
        </thead>
        <tbody>
    """
    
    for _, row in df_latest.iterrows():
        # 色付けロジック
        rsi_style = 'class="heat-red"' if row['RSI'] >= 70 else ('class="heat-blue"' if row['RSI'] <= 30 else '')
        bb_style = 'class="heat-red"' if row['BB%B(過熱)'] >= 1.0 else ('class="heat-blue"' if row['BB%B(過熱)'] <= 0 else '')
        change_style = 'class="heat-red"' if row['前日比(%)'] > 0 else 'class="heat-blue"'
        
        # 前日比にプラス記号をつける
        change_sign = "+" if row['前日比(%)'] > 0 else ""
        
        html += f"""
            <tr>
                <td style="text-align:left;">{row['セクター名']}</td>
                <td>{row['現在値']:,}</td>
                <td {change_style}>{change_sign}{row['前日比(%)']}%</td>
                <td>{row['短期(5日乖離)']}%</td>
                <td>{row['中期(25日乖離)']}%</td>
                <td {rsi_style}>{row['RSI']}</td>
                <td {bb_style}>{row['BB%B(過熱)']}</td>
            </tr>
        """
    html += "</tbody></table></div>"

    # --- 2. Chart.js グラフの生成 ---
    # データをJSON用に整形
    labels = df_latest['セクター名'].tolist()
    data_mid = df_latest['中期(25日乖離)'].tolist()
    data_rsi = df_latest['RSI'].tolist()
    
    # 乖離率ランキング順にソートしてグラフ化するための処理
    sorted_indices = sorted(range(len(data_mid)), key=lambda k: data_mid[k], reverse=True)
    sorted_labels = [labels[i] for i in sorted_indices]
    sorted_data_mid = [data_mid[i] for i in sorted_indices]
    
    # グラフ用Canvas
    html += "<h4>📈 中期トレンド(25日乖離) ランキング</h4>"
    html += '<canvas id="sectorChart" width="400" height="250"></canvas>'
    
    # Chart.jsのスクリプト埋め込み
    # 注意: WordPressの自動整形(wpautop)対策のため、改行を極力減らす
    script = f"""
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
    document.addEventListener("DOMContentLoaded", function() {{
        var ctx = document.getElementById('sectorChart').getContext('2d');
        var myChart = new Chart(ctx, {{
            type: 'bar',
            data: {{
                labels: {json.dumps(sorted_labels, ensure_ascii=False)},
                datasets: [{{
                    label: '25日移動平均乖離率(%)',
                    data: {json.dumps(sorted_data_mid)},
                    backgroundColor: {json.dumps(['rgba(255, 99, 132, 0.7)' if x >= 0 else 'rgba(54, 162, 235, 0.7)' for x in sorted_data_mid])},
                    borderColor: {json.dumps(['rgba(255, 99, 132, 1)' if x >= 0 else 'rgba(54, 162, 235, 1)' for x in sorted_data_mid])},
                    borderWidth: 1
                }}]
            }},
            options: {{
                responsive: true,
                indexAxis: 'y',
                scales: {{
                    x: {{ beginAtZero: true, grid: {{ color: '#eee' }} }}
                }}
            }}
        }});
    }});
    </script>
    """
    html += script
    
    html += "<p><small>※ データソース: Yahoo! Finance / TOPIX-17シリーズETF</small></p>"
    
    return html

def update_wordpress(html_content):
    """WordPress REST APIを使って記事を更新する"""
    wp_url = os.environ.get('WP_URL') # 例: https://example.com
    wp_user = os.environ.get('WP_USER')
    wp_password = os.environ.get('WP_PASSWORD') # Application Password
    page_id = os.environ.get('WP_PAGE_ID') # 更新したい固定ページのID

    if not all([wp_url, wp_user, wp_password, page_id]):
        print("WordPress設定が足りません。環境変数を確認してください。")
        return

    api_url = f"{wp_url}/wp-json/wp/v2/pages/{page_id}"
    
    # 認証ヘッダー作成
    credentials = f"{wp_user}:{wp_password}"
    token = base64.b64encode(credentials.encode()).decode()
    headers = {
        'Authorization': f'Basic {token}',
        'Content-Type': 'application/json'
    }
    
    # データ作成
    post_data = {
        'content': html_content,
        # 'title': f'【自動更新】日本株セクター分析 ({datetime.now().strftime("%m/%d")})' # タイトルも変えたい場合
    }
    
    # 送信
    response = requests.post(api_url, headers=headers, json=post_data)
    
    if response.status_code == 200:
        print("✅ WordPressの更新に成功しました！")
    else:
        print(f"❌ WordPress更新エラー: {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    try:
        print("データを取得中...")
        df = get_sheet_data()
        
        print("HTML生成中...")
        html = generate_html_content(df)
        
        print("WordPress更新中...")
        update_wordpress(html)
        
    except Exception as e:
        print(f"エラーが発生しました: {e}")
