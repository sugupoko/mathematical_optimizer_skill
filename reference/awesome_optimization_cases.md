# Awesome 数理最適化 実務事例集

> 世界と日本の企業が数理最適化で実際に成果を出した事例をまとめた。
> 「こういう問題に使えるのか」のイメージを掴むためのリスト。
> ※ 事例の調査日: 2026年4月。各事例の時期は「時期」列を参照。

---

## 物流・配送

| 企業 | 国 | 時期 | 問題 | 手法 | 効果 | 出典 |
|------|-----|------|------|------|------|------|
| **UPS** | 米 | 2012〜（2024更新） | 配送ルート最適化（ORION） | VRP + メタヒューリスティクス | 年間1億マイル削減、**$3億のコスト削減**。2024年は15%の物量増にも車両追加なしで対応 | [INFORMS](https://www.informs.org/Impact/O.R.-Analytics-Success-Stories/UPS), [Ascend Analytics](https://www.ascendanalytics.co/post/how-upss-orion-system-slashed-delivery-costs-with-route-optimization) |
| **Amazon** | 米 | 2019〜（継続拡大中） | サプライチェーン全体最適化 | 大規模MIP + ML予測 | 毎秒数百万件の配送約束を最適化。毎日数十億の在庫更新をリアルタイム追跡 | [Amazon Science](https://www.amazon.science/latest-news/solving-some-of-the-largest-most-complex-operations-problems) |
| **FedEx** | 米 | 2023年11月〜 | ラストマイル配送ルート | ML + 動的ルート最適化 | ラストマイル配送時間を大幅短縮。リアルタイム交通+天候データで動的調整 | [Debales AI](https://debales.ai/blog/real-world-examples-of-ai-route-optimization-in-logistics) |
| **DHL** | 独 | 2023年2月〜 | 欧州ネットワークのルート | AI + エコルーティング | 倉庫内スタッフ移動距離**50%削減**、拠点生産性**30%向上**。燃料+CO2削減 | [Debales AI](https://debales.ai/blog/real-world-examples-of-ai-route-optimization-in-logistics) |
| **ヤマト運輸** | 日 | 2023〜2024 | 配送業務量予測+適正配車 | 需要予測 + 配車最適化 | 生産性**最大20%向上**、走行距離**25%削減**、CO2削減 | [TRYETING](https://www.tryeting.jp/column/11639/) |
| **ARAUCO** | チリ | 2023 | 林業サプライチェーン計画 | Gurobi(MIP) | 生産・配送の全体最適化、リソース活用率向上 | [Gurobi](https://www.gurobi.com/case_study/arauco-supply-chain-optimization/) |
| **LeanLogistics** | 米 | 2022〜2023 | 車両ルーティング | Gurobi(VRP) | 他ソルバー比2倍高速、荷主の運賃**12.9%削減** | [Gurobi](https://www.gurobi.com/case_studies/) |

## 製造・生産計画

| 企業 | 国 | 時期 | 問題 | 手法 | 効果 | 出典 |
|------|-----|------|------|------|------|------|
| **日本製鉄** | 日 | 2023年10月稼働 | 出鋼スケジューリング | 数理最適化(MIP) | 週次計画業務**70%以上削減**、数時間→数秒 | [日鉄ソリューションズ](https://www.nssol.nipponsteel.com/casestudy/02905.html) |
| **BMW** | 独 | 2023年論文 | 車両生産計画の最適化 | 量子インスパイア+生成AI(GEO) | 組立ラインのアイドル時間を最小化。従来のソルバーを上回る性能 | [Zapata AI](https://zapata.ai/news/bmw-optimizes-vehicle-production-planning-using-quantum-inspired-generative-ai-techniques/) |
| **ライオン** | 日 | 2024年12月発表 | 生産計画の自動作成 | 数理最適化スケジューラ | 計画作成の自動化、属人性排除 | [NTTデータ数理システム](https://www.msiism.jp/technology/optimization/) |
| **BASF** | 独 | 2023年論文 | 実験室の搬送ロボット経路 | スケジューリング最適化 | 化学サンプルの搬送時間最小化 | [Nature](https://www.nature.com/articles/s41598-023-45668-1) |
| **トヨタ** | 日 | 継続的 | 生産ライン効率化 | LP/MIP | 生産コスト削減と品質向上の同時達成 | [BrainPad](https://www.brainpad.co.jp/doors/contents/about_mathematical_optimization/) |
| **ハウス食品** | 日 | 2023〜2024 | 需給最適化 | 需要予測 + 最適化 | 欠品**50%削減**、廃棄ロス**10%削減**、管理工数**60%削減** | [AI Market](https://ai-market.jp/purpose/mathematical-optimization/) |

## 交通・航空・スポーツ

| 企業 | 国 | 時期 | 問題 | 手法 | 効果 | 出典 |
|------|-----|------|------|------|------|------|
| **Molslinjen** | デンマーク | 2024年受賞 | フェリー運航最適化 | OR + アナリティクス | **2024年エデルマン賞受賞**（OR界の最高賞） | [INFORMS](https://www.informs.org/Recognizing-Excellence/INFORMS-Prizes/Franz-Edelman-Award) |
| **USA Cycling** | 米 | 2024五輪/2025受賞 | レース戦略+選手準備 | OR + データ分析 | パリ五輪で女子チームパシュート**金メダル**。**2025年エデルマン賞** | [INFORMS](https://www.informs.org/Recognizing-Excellence/INFORMS-Prizes/Franz-Edelman-Award) |
| **遠州鉄道** | 日 | 2024年12月発表 | バス運転者の勤務シフト | 数理計画法 | シフト表の自動作成 | [NTTデータ数理システム](https://www.msiism.jp/technology/optimization/) |
| **Hitit（航空各社）** | トルコ | 2023〜2024 | 乗務員の休暇スケジュール | Gurobi(MIP) | 数千人の最適休暇表を**数秒で生成** | [Gurobi](https://www.gurobi.com/case_studies/) |

## 医療・ヘルスケア

| 企業/機関 | 国 | 時期 | 問題 | 手法 | 効果 | 出典 |
|----------|-----|------|------|------|------|------|
| **仁荷大学病院** | 韓国 | 2023年12月 | 看護師AIシフト(IH-NASS) | AI + 数理最適化 | 14病棟253名のシフトを自動生成。業務品質と満足度が向上 | [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12210576/) |
| **フランスの病院** | 仏 | 2024年論文 | 看護師スケジューリング | MIP（負荷均等化） | 負荷分散と公平性を数学的に保証。実務フィードバックで有効性確認 | [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0038012124002453) |
| **Dr. Saiful Anwar病院** | インドネシア | 2024年1月 | 救急部の看護師スケジュール | 目標計画法 | 21名の看護師の負荷分散を最適化。1ヶ月分のシフトを自動生成 | [Journal](https://journal.upy.ac.id/index.php/derivat/article/view/6899) |
| **大学病院ICU** | 欧州 | 2024年論文 | ICUスタッフ年間スケジュール | 整数計画法 | 医師10名+看護師14名+介護士9名の年間最適シフト。規則遵守を保証 | [MDPI](https://www.mdpi.com/2076-3417/15/7/3610) |

## エネルギー・インフラ

| 企業 | 国 | 時期 | 問題 | 手法 | 効果 | 出典 |
|------|-----|------|------|------|------|------|
| **東京ガス** | 日 | 2025年7月発表 | ガス開栓業務の差配 | 数理最適化 | 差配業務の自動化 | [NTTデータ数理システム](https://www.msiism.jp/technology/optimization/) |
| **JR東日本** | 日 | 2023〜2024 | 設備検査の最適化 | AIスクリーニング+最適化 | 夜間検査省力化、年最大4回の多頻度検査 | [AI Market](https://ai-market.jp/purpose/mathematical-optimization/) |
| **シゼン・コネクト** | 日 | 2024年1月 | 家庭用EV 186台の充放電制御 | VPP最適化 | 指示値の**90%精度**で遠隔制御。V2H大規模実証 | [エネこれ](https://www.enecho.meti.go.jp/about/special/tokushu/denryokugaskaikaku/digitalization.html) |
| **エネX** | 日 | 2024年4月〜 | 需給調整力（容量市場） | 需給最適化 | 約1GWの調整力契約。19日間で計約**7GWh**の節電量提供 | [PPS-NET](https://pps-net.org/column/109140) |

## 施設配置・EV充電

| 企業/機関 | 国 | 時期 | 問題 | 手法 | 効果 | 出典 |
|----------|-----|------|------|------|------|------|
| **ムンバイ/デリーEV研究** | 印 | 2024年論文 | フリート向けEV充電ステーション配置 | 空間モデリング + p-median | 充電待ち時間**70%削減**、到達時間**20%短縮** | [Springer](https://link.springer.com/chapter/10.1007/978-3-031-82439-5_34) |
| **シンガポールEV研究** | 星 | 2024年論文 | 住宅駐車場のEV充電設備配置 | 確率制約最適化 | 需要不確実性と電力網変動を考慮した配置設計 | [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0968090X24001001) |
| **ESUPS（人道支援）** | 国際 | 2024年発表 | 災害救援の物資輸送拠点配置 | 施設配置+VRP | 物資配送の迅速化、命を救う最適化 | [Gurobi](https://www.gurobi.com/news/new-educational-case-study-from-gurobi-and-esups-demonstrates-life-saving-impact-of-optimization/) |

## 金融・保険

| 企業/機関 | 国 | 時期 | 問題 | 手法 | 効果 | 出典 |
|----------|-----|------|------|------|------|------|
| **GlobalTrust Insurance** | 米 | 2024年事例 | 保険リスク評価+価格最適化 | AI + 数理最適化 | リスク予測精度**30%向上**、手動レビュー削減、顧客維持率向上 | [DigitalDefynd](https://digitaldefynd.com/IQ/ai-in-finance-case-studies/) |
| **EquityPlus Investment** | 米 | 2024年事例 | AIポートフォリオ管理 | リアルタイム市場分析 + 最適化 | 動的アセットアロケーション、戦略的投資判断の高速化 | [DigitalDefynd](https://digitaldefynd.com/IQ/ai-in-finance-case-studies/) |
| **イスラム金融研究** | 国際 | 2024年論文 | イスラム金融ポートフォリオ | 強化学習 + 最適化 | シャリア準拠の動的ポートフォリオ最適化 | [ResearchGate](https://www.researchgate.net/publication/391961406_Reinforcement_Learning_for_Dynamic_Portfolio_Optimization_in_Fintech) |

## 小売・食品・EC

| 企業 | 国 | 時期 | 問題 | 手法 | 効果 | 出典 |
|------|-----|------|------|------|------|------|
| **ハウス食品** | 日 | 2023〜2024 | 需給最適化プラットフォーム | 需要予測+在庫最適化 | 欠品**50%減**、廃棄**10%減**、工数**60%減** | [AI Market](https://ai-market.jp/purpose/mathematical-optimization/) |

## IT・テクノロジー

| 企業 | 国 | 時期 | 問題 | 手法 | 効果 | 出典 |
|------|-----|------|------|------|------|------|
| **NTTドコモ** | 日 | 2025年記事 | 生成AI×数理最適化の業務設計 | LLM + MIP | 業務プロセス革命、次世代業務デザイン | [NTT Engineers Blog](https://engineers.ntt.com/entry/202511-genai_opt/entry) |
| **NTTデータ** | 日 | 2023年記事 | プリント基板製造最適化 | 数理最適化 | 製造プロセスの効率化 | [NTT DATA](https://www.nttdata.com/jp/ja/trends/data-insight/2023/0912/) |
| **Gurobi調査** | 国際 | 2024年 | 440社の最適化活用状況 | 調査レポート | 企業の最適化投資は年々増加。コスト削減・利益最大化・効率化が主な目的 | [Gurobi](https://www.gurobi.com/resources/report-state-of-mathematical-optimization-2024/) |

---

## 効果の相場感

調査した事例から見える、数理最適化導入の**典型的な効果**:

| 指標 | 典型的な改善幅 | 代表事例 |
|------|-------------|---------|
| コスト削減 | **10-30%** | UPS(年$3億)、LeanLogistics(運賃12.9%減) |
| 業務時間削減 | **60-90%** | 日本製鉄(70%減)、ハウス食品(60%減) |
| 生産性向上 | **15-30%** | ヤマト運輸(20%向上)、DHL(倉庫30%向上) |
| 廃棄・ロス削減 | **10-50%** | ハウス食品(廃棄10%減、欠品50%減) |
| CO2・環境負荷削減 | **15-25%** | ヤマト運輸(25%削減)、UPS(1億マイル削減)、DHLエコルーティング |
| リスク予測精度 | **20-30%** | GlobalTrust(30%向上) |
| 待ち時間削減 | **50-70%** | ムンバイEV(充電待ち70%減)、DHL(移動距離50%減) |

**共通パターン**: 「ベテランが数時間かけていた作業を、ソルバーが数秒で。しかも品質が同等以上。」

---

## 注目のトレンド（2024-2025）

### 1. 生成AI × 数理最適化
NTTドコモが先行。LLMで問題を分析・定式化し、ソルバーで解く。
BMWは量子インスパイア+生成AIで生産計画を最適化。
本スキルパックのアプローチはまさにこれ。

### 2. Edelman賞（OR界のノーベル賞的存在）
- 2024年: **Molslinjen**（デンマークのフェリー会社）— 運航最適化
- 2025年: **USA Cycling** — パリ五輪でOR活用し金メダル

### 3. ソルバーの民主化
Gurobi（商用）、OR-Tools（無料）、HiGHS（無料）の選択肢が充実。
以前は大企業しか使えなかったが、中小企業やスタートアップにも広がっている。
Gurobi 2024年調査: 440社が最適化を活用中。

### 4. ML + 最適化の融合
予測（ML）→ 意思決定（最適化）のパイプラインが標準化しつつある。
Amazon、ヤマト運輸、FedExなどが先行。
英国FCA調査(2024): 金融サービス企業の75%がAIを活用中。

### 5. 医療・ヘルスケアへの展開
看護師スケジューリングは韓国、フランス、インドネシアで実証事例が急増。
ICUスタッフの年間シフト最適化まで実用レベルに。

---

## 本スキルパックとの対応

| 事例 | 対応テンプレート |
|------|----------------|
| UPS/ヤマト/FedEx/DHLの配送ルート | `vrp_template.py` |
| 日本製鉄/ライオン/BMWの生産計画 | `scheduling_template.py` |
| 看護師/遠鉄のシフト | `scheduling_template.py` |
| Hititの乗務員スケジュール | `scheduling_template.py` |
| ハウス食品の需給最適化 | `pulp_highs_guide.md` + ML予測 |
| EV充電ステーション/ESUPSの施設配置 | `facility_location_template.py` |
| 保険/ポートフォリオの金融最適化 | `continuous_optimization_template.py` |
| NTTドコモのAI×最適化 | `ml_optimization_guide.md` |

---

## 参考リンク

- [Gurobi State of Mathematical Optimization 2024](https://www.gurobi.com/resources/report-state-of-mathematical-optimization-2024/) — 440社の最適化活用状況調査
- [INFORMS Edelman Award](https://www.informs.org/Recognizing-Excellence/INFORMS-Prizes/Franz-Edelman-Award) — OR界の最高賞の受賞事例集
- [Amazon Science - OR & Optimization](https://www.amazon.science/research-areas/operations-research-and-optimization) — Amazonの最適化研究
- [BrainPad - 数理最適化とは](https://www.brainpad.co.jp/doors/contents/about_mathematical_optimization/) — 日本語の包括的解説
- [NTT Engineers Blog - 生成AI×数理最適化](https://engineers.ntt.com/entry/202511-genai_opt/entry) — LLM+最適化の先進事例
- [NTT Engineers Blog - ML×数理最適化](https://engineers.ntt.com/entry/20241209-business_process_opt/entry) — ML+最適化の業務プロセス革命
- [LogMi - ポストデータサイエンスとしての数理最適化](https://logmi.jp/brandtopics/330853) — AI時代の数理最適化の位置づけ
