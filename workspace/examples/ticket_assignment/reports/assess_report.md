# アセスメントレポート — チケットアサイン最適化

**作成日**: 2026-04-01
**基準時刻**: 2026-04-01 14:00
**データ**: engineers.csv, tickets.csv, resolution_history.csv, constraints.csv

---

## 1. データ概要

| 項目 | 値 |
|------|-----|
| エンジニア数 | 20名 |
| 勤務中（on_shift） | 15名 |
| オンコール（L3 off-shift） | 1名（E020） |
| チケット総数 | 80件 |
| 未アサイン | 25件 |
| 対応中（in_progress） | 47件 |
| ブロック中 | 8件（vendor:4, approval:2, customer:2） |

## 2. エンジニア構成

| ティア | 人数 | 最大同時担当 | シフト分布 |
|--------|------|-------------|-----------|
| L1 | 8名 | 各6件 | day:4, late:2, night:2 |
| L2 | 8名 | 各4件 | day:4, late:2, night:2 |
| L3 | 4名 | 各3件 | day:2, late:1, night:1 |

- nightシフト（E007, E008, E015, E016, E020）はoff_shift
- L3のE020はP1チケットに対しオンコール対応可

## 3. チケット分布

### 優先度別
| 優先度 | 件数 | SLA残6h未満 |
|--------|------|------------|
| P1（Critical） | 3件 | 2件 |
| P2（High） | 13件 | 4件 |
| P3（Standard） | 42件 | 2件 |
| P4（Low） | 22件 | 0件 |

### 種別
| タイプ | 件数 |
|--------|------|
| incident_critical | 3 |
| incident_high | 10 |
| incident_mid | 20 |
| incident_low | 13 |
| service_request | 18 |
| change_standard | 3 |

### ブロック中チケット（8件）
| チケット | 状態 | 担当者 | SLA残 |
|----------|------|--------|-------|
| TK016 | blocked_vendor | E009 | 1.0h |
| TK017 | blocked_vendor | E013 | 21.0h |
| TK018 | blocked_approval | E014 | 19.0h |
| TK019 | blocked_customer | E012 | 2.0h |
| TK020 | blocked_vendor | E005 | 124.0h |
| TK031 | blocked_approval | E011 | 24.0h |
| TK069 | blocked_customer | E018 | 7.0h |
| TK073 | blocked_vendor | E003 | 20.0h |

## 4. SLAリスクチケット（残6時間未満: 8件）

| チケット | 優先度 | SLA残時間 | 状態 |
|----------|--------|----------|------|
| TK001 | P1 | 1.5h | in_progress |
| TK002 | P1 | 2.0h | in_progress |
| TK003 | P2 | 5.0h | in_progress |
| TK015 | P2 | 5.0h | in_progress |
| TK016 | P2 | 1.0h | blocked_vendor |
| TK019 | P3 | 2.0h | blocked_customer |
| TK036 | P1 | 4.0h | **未アサイン** |
| TK063 | P2 | 5.0h | in_progress |

**重大**: TK036（P1・認証基盤停止）が未アサインでSLA残4時間。即座のアサインが必要。

## 5. スキル需要 vs 供給（未アサインチケット）

| スキル | 需要（未アサイン） | 供給（on_shift + on_call） |
|--------|-------------------|--------------------------|
| app_support | 5 | 8 |
| monitoring | 3 | 5 |
| security | 4 | 5 |
| network | 3 | 5 |
| helpdesk | 3 | 6 |
| cloud | 3 | 5 |
| infra | 3 | 5 |
| database | 2 | 5 |

スキル供給は需要を上回っているが、既存の担当チケット負荷によりスロットが逼迫している。

## 6. 問題分類と仮説

**問題タイプ**: リソース制約付きマルチオブジェクティブ割当問題

**仮説**:
1. **容量ボトルネック**: 勤務中エンジニアの空きスロットが不足し、新規チケットをアサインできない
2. **ブロック非効率**: ブロック中チケットがスロットを占有し、実質的な処理能力を低下させている
3. **停滞チケット**: 長時間進捗のないチケットが再アサインされずにスロットを無駄にしている
4. **ティア温存**: L3をcritical案件に温存する必要があるが、P2チケットが多く対応が厳しい

**推奨アプローチ**: CP-SATソルバーによる最適化 + ブロック解放 + 停滞再アサイン
