# Awesome 数理最適化 実務事例集

> 世界と日本の企業が数理最適化で実際に成果を出した事例をまとめた。
> 「こういう問題に使えるのか」のイメージを掴むためのリスト。

---

## 物流・配送

| 企業 | 国 | 時期 | 問題 | 手法 | 効果 | 出典 |
|------|-----|------|------|------|------|------|
| **UPS** | 米 | 2012〜（2024更新） | 配送ルート最適化（ORION） | VRP + メタヒューリスティクス | 年間1億マイル削減、**$3億のコスト削減** | [INFORMS](https://www.informs.org/Impact/O.R.-Analytics-Success-Stories/UPS), [Ascend Analytics](https://www.ascendanalytics.co/post/how-upss-orion-system-slashed-delivery-costs-with-route-optimization) |
| **Amazon** | 米 | 2019〜（継続拡大中） | サプライチェーン全体最適化 | 大規模MIP + ML予測 | 毎秒数百万件の配送約束を最適化、配送時間の年々短縮 | [Amazon Science](https://www.amazon.science/latest-news/solving-some-of-the-largest-most-complex-operations-problems) |
| **ヤマト運輸** | 日 | 2023〜2024 | 配送業務量予測+適正配車 | 需要予測 + 配車最適化 | 生産性**最大20%向上**、走行距離**25%削減**、CO2削減 | [TRYETING](https://www.tryeting.jp/column/11639/) |
| **ARAUCO** | チリ | 2023 | サプライチェーン計画 | Gurobi(MIP) | 生産・配送の全体最適化、リソース活用率向上 | [Gurobi](https://www.gurobi.com/case_study/arauco-supply-chain-optimization/) |
| **LeanLogistics** | 米 | 2022〜2023 | 車両ルーティング | Gurobi(VRP) | 他ソルバー比2倍高速、荷主の運賃**12.9%削減** | [Gurobi](https://www.gurobi.com/case_studies/) |

## 製造・生産計画

| 企業 | 国 | 時期 | 問題 | 手法 | 効果 | 出典 |
|------|-----|------|------|------|------|------|
| **日本製鉄** | 日 | 2023年10月稼働 | 出鋼スケジューリング | 数理最適化(MIP) | 週次計画業務**70%以上削減**、数時間→数秒 | [日鉄ソリューションズ](https://www.nssol.nipponsteel.com/casestudy/02905.html) |
| **ライオン** | 日 | 2024年12月発表 | 生産計画の自動作成 | 数理最適化スケジューラ | 計画作成の自動化、属人性排除 | [NTTデータ数理システム](https://www.msiism.jp/technology/optimization/) |
| **BASF** | 独 | 2023年論文 | 実験室の搬送ロボット経路 | スケジューリング最適化 | 化学サンプルの搬送時間最小化 | [Nature](https://www.nature.com/articles/s41598-023-45668-1) |
| **トヨタ** | 日 | 継続的 | 生産ライン効率化 | LP/MIP | 生産コスト削減と品質向上の同時達成 | [BrainPad](https://www.brainpad.co.jp/doors/contents/about_mathematical_optimization/) |
| **ハウス食品** | 日 | 2023〜2024 | 需給最適化 | 需要予測 + 最適化 | 欠品**50%削減**、廃棄ロス**10%削減**、管理工数**60%削減** | [AI Market](https://ai-market.jp/purpose/mathematical-optimization/) |

## 交通・航空

| 企業 | 国 | 時期 | 問題 | 手法 | 効果 | 出典 |
|------|-----|------|------|------|------|------|
| **遠州鉄道** | 日 | 2024年12月発表 | バス運転者の勤務シフト | 数理計画法 | シフト表の自動作成 | [NTTデータ数理システム](https://www.msiism.jp/technology/optimization/) |
| **Hitit（航空各社）** | トルコ | 2023〜2024 | 乗務員の休暇スケジュール | Gurobi(MIP) | 数千人の最適休暇表を**数秒で生成** | [Gurobi](https://www.gurobi.com/case_studies/) |
| **Molslinjen** | デンマーク | 2024年受賞 | フェリー運航最適化 | OR + アナリティクス | **2024年エデルマン賞受賞** | [INFORMS](https://www.informs.org/Recognizing-Excellence/INFORMS-Prizes/Franz-Edelman-Award) |
| **USA Cycling** | 米 | 2024五輪/2025受賞 | レース戦略+選手準備 | OR + データ分析 | パリ五輪で女子チームパシュート金メダル、**2025年エデルマン賞** | [INFORMS](https://www.informs.org/Recognizing-Excellence/INFORMS-Prizes/Franz-Edelman-Award) |

## エネルギー・インフラ

| 企業 | 国 | 時期 | 問題 | 手法 | 効果 | 出典 |
|------|-----|------|------|------|------|------|
| **東京ガス** | 日 | 2025年7月発表 | ガス開栓業務の差配 | 数理最適化 | 差配業務の自動化 | [NTTデータ数理システム](https://www.msiism.jp/technology/optimization/) |
| **JR東日本** | 日 | 2023〜2024 | 設備検査の最適化 | AIスクリーニング+最適化 | 夜間検査省力化、年最大4回の多頻度検査 | [AI Market](https://ai-market.jp/purpose/mathematical-optimization/) |

## 小売・食品・EC

| 企業 | 国 | 時期 | 問題 | 手法 | 効果 | 出典 |
|------|-----|------|------|------|------|------|
| **ハウス食品** | 日 | 2023〜2024 | 需給最適化プラットフォーム | 需要予測+在庫最適化 | 欠品50%減、廃棄10%減、工数60%減 | [AI Market](https://ai-market.jp/purpose/mathematical-optimization/) |

## IT・テクノロジー

| 企業 | 国 | 時期 | 問題 | 手法 | 効果 | 出典 |
|------|-----|------|------|------|------|------|
| **NTTドコモ** | 日 | 2025年記事 | 生成AI×数理最適化の業務設計 | LLM + MIP | 業務プロセス革命、次世代業務デザイン | [NTT Engineers Blog](https://engineers.ntt.com/entry/202511-genai_opt/entry) |
| **NTTデータ** | 日 | 2023年記事 | プリント基板製造最適化 | 数理最適化 | 製造プロセスの効率化 | [NTT DATA](https://www.nttdata.com/jp/ja/trends/data-insight/2023/0912/) |

## 人道支援・医療・公共

| 企業/団体 | 国 | 時期 | 問題 | 手法 | 効果 | 出典 |
|----------|-----|------|------|------|------|------|
| **ESUPS（人道支援）** | 国際 | 2024年発表 | 災害救援の物資輸送 | 施設配置+VRP | 物資配送の迅速化、命を救う最適化 | [Gurobi](https://www.gurobi.com/news/new-educational-case-study-from-gurobi-and-esups-demonstrates-life-saving-impact-of-optimization/) |

---

## 効果の相場感

調査した事例から見える、数理最適化導入の**典型的な効果**:

| 指標 | 典型的な改善幅 | 代表事例 |
|------|-------------|---------|
| コスト削減 | **10-30%** | UPS(年$3億)、LeanLogistics(運賃12.9%減) |
| 業務時間削減 | **60-90%** | 日本製鉄(70%減)、ハウス食品(60%減) |
| 生産性向上 | **15-25%** | ヤマト運輸(20%向上) |
| 廃棄・ロス削減 | **10-50%** | ハウス食品(廃棄10%減、欠品50%減) |
| CO2削減 | **15-25%** | ヤマト運輸(25%削減)、UPS(1億マイル削減) |

**共通パターン**: 「ベテランが数時間かけていた作業を、ソルバーが数秒で。しかも品質が同等以上。」

---

## 注目のトレンド（2024-2025）

### 1. 生成AI × 数理最適化
NTTドコモが先行。LLMで問題を分析・定式化し、ソルバーで解く。
本スキルパックのアプローチはまさにこれ。

### 2. Edelman賞（OR界のノーベル賞的存在）
- 2024年: **Molslinjen**（デンマークのフェリー会社）— 運航最適化
- 2025年: **USA Cycling** — パリ五輪でOR活用し金メダル

### 3. ソルバーの民主化
Gurobi（商用）、OR-Tools（無料）、HiGHS（無料）の選択肢が充実。
以前は大企業しか使えなかったが、中小企業やスタートアップにも広がっている。

### 4. ML + 最適化の融合
予測（ML）→ 意思決定（最適化）のパイプラインが標準化しつつある。
Amazon、ヤマト運輸などが先行。

---

## 本スキルパックとの対応

| 事例 | 対応テンプレート |
|------|----------------|
| UPS/ヤマトの配送ルート | `vrp_template.py` |
| 日本製鉄/ライオンの生産計画 | `scheduling_template.py` |
| 遠鉄のバスシフト | `scheduling_template.py` |
| Hititの乗務員スケジュール | `scheduling_template.py` |
| ハウス食品の需給最適化 | `pulp_highs_guide.md` + ML予測 |
| ESUPSの災害物資輸送 | `facility_location_template.py` + `vrp_template.py` |
| NTTドコモのAI×最適化 | `ml_optimization_guide.md` |

---

## 参考リンク

- [Gurobi State of Mathematical Optimization 2024](https://www.gurobi.com/resources/report-state-of-mathematical-optimization-2024/) — 440社の最適化活用状況調査
- [INFORMS Edelman Award](https://www.informs.org/Recognizing-Excellence/INFORMS-Prizes/Franz-Edelman-Award) — OR界の最高賞の受賞事例集
- [Amazon Science - OR & Optimization](https://www.amazon.science/research-areas/operations-research-and-optimization) — Amazonの最適化研究
- [BrainPad - 数理最適化とは](https://www.brainpad.co.jp/doors/contents/about_mathematical_optimization/) — 日本語の包括的解説
- [NTT Engineers Blog - 生成AI×数理最適化](https://engineers.ntt.com/entry/202511-genai_opt/entry) — LLM+最適化の先進事例
