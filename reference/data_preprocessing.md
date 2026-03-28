# データ前処理の定石

## 住所 → 緯度経度

```python
# Google Geocoding API（有料だが精度高い）
import googlemaps
gmaps = googlemaps.Client(key='YOUR_API_KEY')
result = gmaps.geocode('東京都千代田区丸の内1-1-1')
lat = result[0]['geometry']['location']['lat']
lng = result[0]['geometry']['location']['lng']

# 無料代替: 国土地理院API
import requests
res = requests.get(
    'https://msearch.gsi.go.jp/address-search/AddressSearch',
    params={'q': '東京都千代田区丸の内1-1-1'}
)
# res.json()[0]['geometry']['coordinates'] → [lng, lat]

# 大量処理: CSVを一括変換
import pandas as pd
df = pd.read_csv('locations.csv')
# ジオコーディングAPIを各行に適用（レート制限に注意）
```

## 距離マトリクスの作成

```python
import math

def haversine_km(lat1, lng1, lat2, lng2):
    """2点間の距離(km)。道路係数1.3を含む。"""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat/2)**2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng/2)**2)
    return R * 2 * math.asin(math.sqrt(a)) * 1.3

# 道路係数の目安:
#   1.3: 市街地（一般的）
#   1.2: 碁盤目状の道路（京都、札幌）
#   1.4: 山間部（曲がりくねった道）
#   1.0: 直線距離のまま使う場合

# より正確: Google Distance Matrix API（道路距離+所要時間が取れる）
```

## 時間の統一

```python
# 「9:00」「09:00」「9時」を分単位に統一
def time_to_minutes(time_str):
    """時刻文字列を午前0時からの分数に変換"""
    if '時' in time_str:
        h = int(time_str.replace('時', '').strip())
        return h * 60
    parts = time_str.split(':')
    return int(parts[0]) * 60 + int(parts[1])

# 例: "9:00" → 540, "17:30" → 1050
```

## 日本語特有の処理

```python
# 表記ゆれの統一
import re

def normalize_name(name):
    """施設名の表記ゆれを統一"""
    name = name.strip()
    name = re.sub(r'\s+', '', name)  # 空白除去
    name = name.replace('（', '(').replace('）', ')')  # 全角→半角
    name = name.replace('　', '')  # 全角スペース
    return name

# 住所の正規化
def normalize_address(addr):
    addr = addr.replace('丁目', '-').replace('番地', '-').replace('号', '')
    addr = re.sub(r'[０-９]', lambda m: chr(ord(m.group()) - 0xFEE0), addr)  # 全角数字→半角
    return addr
```

## Excelの読み込み

```python
import pandas as pd

# 複数シートがある場合
xlsx = pd.ExcelFile('data.xlsx')
print(xlsx.sheet_names)  # シート名一覧

# シートごとに読む
df_master = pd.read_excel('data.xlsx', sheet_name='マスタ')
df_schedule = pd.read_excel('data.xlsx', sheet_name='スケジュール')

# 日付列の処理
df['date'] = pd.to_datetime(df['日付'], format='%Y/%m/%d')

# NULLの意味を確認（0? 未入力? 該当なし?）
print(df.isnull().sum())  # カラムごとのNULL数
```
