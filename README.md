# 日本株セクター分析＆WordPress自動投稿システム

TOPIX-17業種ETF（1617〜1633）の株価データを毎日自動で取得・分析し、WordPressサイトへ見やすいレポートとして自動投稿するPythonツールセットです。
GitHub Actionsを利用して、市場終了後に完全自動で動作します。

## 機能概要

### 1. データ取得・分析 (`sector_analysis.py`)
* **データソース**: Yahoo! Finance (yfinance) から全17業種のヒストリカルデータを取得。
* **テクニカル指標**: 以下の指標を自動計算し、トレンドを判定します。
    * RSI (相対力指数)
    * ボリンジャーバンド %B
    * 移動平均乖離率
    * 出来高倍率
* **データ保存**: 処理結果をJSONファイルとして保存し、後続の処理へ渡します。

### 2. レポート生成・投稿 (`wordpress_publisher.py`)
WordPress REST APIを経由して、以下のコンテンツを含むリッチなHTMLレポートを固定ページへ自動投稿（更新）します。

* **短期トレンド判定パネル**: 各業種の前日比に加え、「過熱」「割安」シグナルを自動判定してバッジ表示。
* **長期パフォーマンスチャート**: 直近300営業日を起点(100)とした比較チャートを Chart.js で描画（スマホ操作対応）。
* **過熱ランキング**: 上昇トレンドかつ過熱感のある業種Top3を自動抽出してハイライト。

### 3. 自動実行 (GitHub Actions)
* **スケジュール**: 日本時間の市場終了後、毎日 **15:40 (UTC 06:40)** に自動実行されます。

## ファイル構成

```text
.
├── .github/workflows/
│   └── sector_trend_analysis.yml  # GitHub Actions 定義ファイル (スケジュール設定等)
├── sector_analysis.py             # データ取得・テクニカル計算・JSON保存
├── wordpress_publisher.py         # レポートHTML生成・WordPress API投稿
├── requirements.txt               # 依存ライブラリ一覧 (yfinance, pandas, requests 等)
└── README.md
