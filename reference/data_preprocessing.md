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

## 大規模距離行列の扱い

N×N の距離行列は N>1,000 でメモリ問題が発生する（1,000地点で約8MB、10,000地点で約800MB）。

### 方法1: int16 でスケーリング（最も簡単）

```python
import numpy as np

def build_distance_matrix_compact(locations: list[dict], scale: int = 100) -> np.ndarray:
    """距離をscaleメートル単位の整数で保持。メモリを1/4に削減。

    scale=100 なら 100m単位（最大 3,276km まで表現可能）。
    """
    n = len(locations)
    matrix = np.zeros((n, n), dtype=np.int16)
    for i in range(n):
        for j in range(i + 1, n):
            dist_km = haversine_km(
                locations[i]['lat'], locations[i]['lng'],
                locations[j]['lat'], locations[j]['lng']
            )
            dist_scaled = int(dist_km * 1000 / scale)  # km → m → scaled
            dist_scaled = min(dist_scaled, 32767)  # int16 の上限
            matrix[i][j] = dist_scaled
            matrix[j][i] = dist_scaled
    return matrix

# メモリ比較:
#   float64: N×N×8 bytes = 10,000地点で 800MB
#   int16:   N×N×2 bytes = 10,000地点で 200MB
```

### 方法2: k-nearest neighbor のみ保持（疎行列）

```python
from scipy.sparse import lil_matrix
import numpy as np

def build_sparse_distance_matrix(
    locations: list[dict], k: int = 50
) -> lil_matrix:
    """各地点からの近い k 地点のみ距離を保持。メモリを大幅削減。

    VRP では遠い地点間の距離は使わないことが多い。
    k=50 なら 10,000地点でも約 4MB（N×k×8 bytes）。
    """
    n = len(locations)
    matrix = lil_matrix((n, n), dtype=np.float32)

    for i in range(n):
        # 全地点への距離を計算
        distances = []
        for j in range(n):
            if i == j:
                continue
            d = haversine_km(
                locations[i]['lat'], locations[i]['lng'],
                locations[j]['lat'], locations[j]['lng']
            )
            distances.append((j, d))

        # 近い k 地点のみ保持
        distances.sort(key=lambda x: x[1])
        for j, d in distances[:k]:
            matrix[i, j] = d

    return matrix.tocsr()  # CSR形式に変換（高速アクセス）

# 注意: ルート構築時に疎行列にない距離が必要な場合は都度計算する
```

### 方法3: オンデマンド計算（OR-Tools コールバック）

```python
def create_distance_callback(locations: list[dict]):
    """距離行列を保持せず、コールバック内で都度計算する。

    メモリ使用量はO(1)だが、計算回数が多くなる。
    地点数が非常に多い場合（10,000+）に有効。
    LRUキャッシュで頻繁にアクセスされる距離をキャッシュ。
    """
    from functools import lru_cache

    @lru_cache(maxsize=100000)
    def distance(i: int, j: int) -> int:
        if i == j:
            return 0
        d = haversine_km(
            locations[i]['lat'], locations[i]['lng'],
            locations[j]['lat'], locations[j]['lng']
        )
        return int(d * 1000)  # km → m

    return distance

# OR-Tools での使用例:
# callback = create_distance_callback(locations)
# transit_callback_index = routing.RegisterTransitCallback(
#     lambda from_idx, to_idx: callback(
#         manager.IndexToNode(from_idx), manager.IndexToNode(to_idx)
#     )
# )
```

### 方法の選び方

```
地点数:
  ├── ~1,000  → 通常の float64 行列で問題なし
  ├── 1,000~5,000 → 方法1（int16スケーリング）
  ├── 5,000~20,000 → 方法2（疎行列） or 方法3（オンデマンド）
  └── 20,000+ → 方法3（オンデマンド + LRUキャッシュ）
               + 必ずクラスタ分割（reference/improvement_patterns.md パターン3）
```
