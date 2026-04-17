"""ticket_assignment_advanced データ生成スクリプト。

50 エンジニア × 200 チケット × 4 タイムステップの
全部盛りチケットアサイン最適化問題データを生成する。

優先要素:
  1. マルチスキル & スワーミング (40 件 2 スキル, 10 件 3 スキル)
  2. 不確実性 (解決時間分布, ブロック解除確率, 到着予測)

追加要素:
  - 時間軸 (4 期, シフト交代)
  - エスカレーション・チェーン
  - チケット依存 DAG
  - 非線形 SLA ペナルティ
  - 組織制約 (ペア禁止, メンタリング)
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

random.seed(42)

OUT = Path(__file__).parent

# ============================================================
# 定数
# ============================================================

SKILLS = [
    "helpdesk", "app_support", "monitoring", "network",
    "database", "cloud", "security", "infra",
    "container", "ai_ml", "sap", "iot",
]

TIERS = ["L1", "L2", "L3", "L4"]

SHIFTS = {
    "day":   {"start": "08:00", "end": "17:00"},
    "late":  {"start": "14:00", "end": "23:00"},
    "night": {"start": "22:00", "end": "07:00"},
}

# 日本人名プール
LAST_NAMES = [
    "田中", "鈴木", "山本", "佐藤", "中村", "小林", "加藤", "吉田",
    "渡辺", "伊藤", "高橋", "松本", "木村", "林", "山田", "井上",
    "石川", "藤田", "中島", "岡田", "清水", "前田", "森", "池田",
    "橋本", "阿部", "石井", "上田", "大野", "久保", "原", "浜田",
    "川口", "谷口", "西村", "三浦", "福田", "菅原", "長谷川", "青木",
    "坂本", "島田", "野口", "古川", "武田", "杉山", "平野", "内田",
    "河野", "安藤",
]
FIRST_NAMES = [
    "健太", "美咲", "翔太", "由美", "大輔", "愛", "拓海", "さくら",
    "誠", "花", "亮介", "真由", "隼人", "彩乃", "悠斗", "理恵",
    "徹", "恵子", "康平", "美穂", "陽太", "千尋", "蓮", "葵",
    "颯太", "凛", "大翔", "結衣", "海斗", "七海", "樹", "桃子",
    "奏太", "莉子", "悠真", "朱里", "湊", "楓", "蒼", "紬",
    "律", "芽依", "暖", "彩花", "陸", "心春", "新", "美月",
    "瑛太", "詩織",
]

# ============================================================
# エンジニア生成
# ============================================================

def generate_engineers() -> list[dict]:
    """50 名のエンジニアを生成。"""
    engineers = []
    eid = 1

    # --- L1: 20 名 (基本スキル 2-3) ---
    l1_skill_pool = ["helpdesk", "app_support", "monitoring", "network", "infra"]
    for i in range(20):
        skills = random.sample(l1_skill_pool, random.choice([2, 3]))
        shift = ["day"] * 10 + ["late"] * 6 + ["night"] * 4
        s = shift[i]
        engineers.append({
            "engineer_id": f"E{eid:03d}",
            "name": f"{LAST_NAMES[eid-1]} {FIRST_NAMES[eid-1]}",
            "tier": "L1",
            "skills": ",".join(skills),
            "max_concurrent": 6,
            "experience_years": random.randint(1, 3),
            "shift": s,
            "on_shift": s in ("day", "late"),  # T0=14:00
            "fatigue_level": round(random.uniform(0.0, 0.4), 2),
            "mentoring_eligible": False,
        })
        eid += 1

    # --- L2: 16 名 (中級スキル 3-4) ---
    l2_skill_pool = ["helpdesk", "app_support", "network", "database", "cloud",
                     "security", "infra", "monitoring", "container", "iot"]
    for i in range(16):
        skills = random.sample(l2_skill_pool, random.choice([3, 4]))
        shift = ["day"] * 8 + ["late"] * 5 + ["night"] * 3
        s = shift[i]
        engineers.append({
            "engineer_id": f"E{eid:03d}",
            "name": f"{LAST_NAMES[eid-1]} {FIRST_NAMES[eid-1]}",
            "tier": "L2",
            "skills": ",".join(skills),
            "max_concurrent": 4,
            "experience_years": random.randint(4, 8),
            "shift": s,
            "on_shift": s in ("day", "late"),
            "fatigue_level": round(random.uniform(0.1, 0.6), 2),
            "mentoring_eligible": random.random() < 0.4,
        })
        eid += 1

    # --- L3: 10 名 (専門スキル 4-5) ---
    l3_skill_pool = ["network", "database", "cloud", "security", "infra",
                     "container", "app_support", "ai_ml", "sap"]
    for i in range(10):
        skills = random.sample(l3_skill_pool, random.choice([4, 5]))
        shift = ["day"] * 5 + ["late"] * 3 + ["night"] * 2
        s = shift[i]
        engineers.append({
            "engineer_id": f"E{eid:03d}",
            "name": f"{LAST_NAMES[eid-1]} {FIRST_NAMES[eid-1]}",
            "tier": "L3",
            "skills": ",".join(skills),
            "max_concurrent": 3,
            "experience_years": random.randint(8, 15),
            "shift": s,
            "on_shift": s in ("day", "late"),
            "fatigue_level": round(random.uniform(0.2, 0.7), 2),
            "mentoring_eligible": True,
        })
        eid += 1

    # --- L4: 4 名 (アーキテクト, 全領域 5-6) ---
    l4_skill_pool = ["network", "database", "cloud", "security", "infra",
                     "container", "ai_ml", "sap", "app_support", "iot"]
    for i in range(4):
        skills = random.sample(l4_skill_pool, random.choice([5, 6]))
        shift = ["day"] * 3 + ["late"]
        s = shift[i]
        engineers.append({
            "engineer_id": f"E{eid:03d}",
            "name": f"{LAST_NAMES[eid-1]} {FIRST_NAMES[eid-1]}",
            "tier": "L4",
            "skills": ",".join(skills),
            "max_concurrent": 2,
            "experience_years": random.randint(15, 25),
            "shift": s,
            "on_shift": True,  # L4 は常時 on-call
            "fatigue_level": round(random.uniform(0.3, 0.8), 2),
            "mentoring_eligible": True,
        })
        eid += 1

    return engineers


# ============================================================
# チケット生成
# ============================================================

TICKET_TEMPLATES = {
    "incident_critical": {
        "priorities": ["P1"],
        "sla_hours": [4],
        "min_tiers": ["L2", "L3", "L3", "L4"],
    },
    "incident_high": {
        "priorities": ["P2"],
        "sla_hours": [12],
        "min_tiers": ["L2", "L2", "L3"],
    },
    "incident_mid": {
        "priorities": ["P3"],
        "sla_hours": [48],
        "min_tiers": ["L1", "L1", "L2"],
    },
    "incident_low": {
        "priorities": ["P4"],
        "sla_hours": [168],
        "min_tiers": ["L1", "L1"],
    },
    "service_request": {
        "priorities": ["P3", "P4"],
        "sla_hours": [48, 168],
        "min_tiers": ["L1", "L2"],
    },
    "change_standard": {
        "priorities": ["P3"],
        "sla_hours": [48],
        "min_tiers": ["L2", "L3"],
    },
    "change_emergency": {
        "priorities": ["P1", "P2"],
        "sla_hours": [4, 12],
        "min_tiers": ["L3", "L4"],
    },
}

TICKET_TITLES = {
    "database": [
        "本番DBサーバー応答なし", "DBレプリケーション遅延", "スロークエリ調査",
        "DB定期メンテナンス準備", "テスト環境DBリストア", "本番DB接続プール枯渇",
        "DBマイグレーション失敗", "バックアップジョブ失敗", "DBクラスタフェイルオーバー",
        "データ不整合検出（受注テーブル）", "DBストレージ逼迫（残3%）",
        "インデックス再構築要求", "DB監査ログ設定", "読み取りレプリカ同期遅延",
    ],
    "network": [
        "VPN接続断続的に切断", "ロードバランサー設定不整合", "DNS解決遅延",
        "ネットワークプリンターオフライン", "ファイアウォールルール誤設定",
        "BGPピアリング断", "コアスイッチCPU高負荷", "VLAN間通信不可",
        "WANリンクパケットロス", "SD-WAN経路異常", "ネットワーク構成図更新",
        "帯域制御ポリシー変更", "無線LAN認証失敗多発",
    ],
    "security": [
        "WAF誤検知によるアクセスブロック", "セキュリティ監査用ログ抽出",
        "退職者アカウント無効化", "新規SaaS SSO設定", "VPN証明書更新",
        "不審なログイン試行検知", "マルウェア感染疑い端末隔離",
        "脆弱性スキャン結果レビュー", "SIEM アラート調査",
        "権限昇格インシデント調査", "ゼロデイ脆弱性緊急パッチ",
        "SOC連携ルール更新", "フィッシングメール報告対応",
    ],
    "cloud": [
        "クラウドストレージ容量逼迫", "CI/CDパイプライン失敗", "クラウドコスト異常検知",
        "クラウドIAMポリシー棚卸し", "DR環境切替テスト",
        "Kubernetes Pod CrashLoopBackOff", "クラウドリージョン間レイテンシ増大",
        "Terraform state ロック解除", "クラウドAPI Rate Limit到達",
        "マルチクラウドVPN設定", "クラウド請求額30%超過アラート",
        "EKSノードグループスケーリング障害",
    ],
    "infra": [
        "認証基盤(LDAP)応答停止", "ストレージI/O遅延", "ジョブスケジューラ異常停止",
        "共有フォルダアクセス権不整合", "Webサーバーセキュリティパッチ適用",
        "ハイパーバイザーメモリ不足", "NTPサーバー時刻ずれ",
        "証明書自動更新失敗(Let's Encrypt)", "物理サーバーRAID警告",
        "UPS バッテリー交換アラート", "DC空調温度異常検知",
        "サーバーファームウェア更新",
    ],
    "app_support": [
        "決済APIタイムアウト多発", "経費精算システムログインエラー",
        "顧客向けAPIレスポンス遅延", "本番アプリメモリリーク",
        "勤怠管理システム打刻エラー", "社内ポータル表示崩れ",
        "APIゲートウェイレート制限誤設定", "バッチ処理遅延(月次集計)",
        "社内チャット通知遅延", "マイクロサービス間通信タイムアウト",
        "OAuth トークンリフレッシュ失敗", "WebSocket接続断",
        "GraphQL N+1 クエリ検出", "キャッシュ汚染疑い",
    ],
    "monitoring": [
        "監視アラート大量発報", "本番アプリサーバーCPU95%超過",
        "監視エージェント停止(5台)", "監視ダッシュボード新規作成",
        "アラート閾値チューニング", "Prometheus メトリクス欠損",
        "Grafana ダッシュボード障害", "ログ収集パイプライン遅延",
        "分散トレーシング設定", "SLI/SLO ダッシュボード構築",
    ],
    "helpdesk": [
        "プリンター印刷キュー滞留", "新入社員PC初期セットアップ",
        "新規アカウント発行", "古いPC入れ替え相談",
        "メール添付ファイルサイズ制限", "社内Wiki権限エラー",
        "リモートデスクトップ接続不可", "VDI環境遅延",
        "モバイルデバイス登録", "ソフトウェアライセンス管理",
    ],
    "container": [
        "Docker Registry ディスク不足", "Kubernetes CronJob 失敗",
        "コンテナイメージ脆弱性検出", "Helm チャートデプロイ失敗",
        "Service Mesh サイドカー障害", "イメージレジストリ認証エラー",
        "Pod リソース制限超過", "Istio Gateway 設定不整合",
    ],
    "ai_ml": [
        "ML推論APIレイテンシ劣化", "学習パイプラインGPUメモリ不足",
        "モデルサービング障害(TensorFlow Serving)", "特徴量ストア同期エラー",
        "A/Bテスト設定ミス(モデルバージョン)", "データドリフト検知アラート",
    ],
    "sap": [
        "SAP RFC接続エラー", "SAP バッチジョブ失敗(月次決算)",
        "SAP ユーザーロック解除(大量)", "SAP トランスポート移送失敗",
        "SAP HANA メモリアラート", "SAP BW クエリタイムアウト",
    ],
    "iot": [
        "IoTゲートウェイ通信断", "センサーデータ欠損アラート",
        "OTA ファームウェア更新失敗", "MQTT ブローカー過負荷",
    ],
}

STATUSES = ["in_progress", "blocked_vendor", "blocked_approval",
            "blocked_customer", "blocked_dependency", "unassigned"]

BLOCK_REASONS = ["blocked_vendor", "blocked_approval",
                 "blocked_customer", "blocked_dependency"]


def generate_tickets(engineers: list[dict]) -> list[dict]:
    """200 件のチケットを生成。"""
    tickets = []
    tid = 1

    # エンジニアIDリスト（on_shift のみアサイン対象）— 容量管理付き
    on_shift = [e for e in engineers if e["on_shift"]]
    on_shift_ids = [e["engineer_id"] for e in on_shift]
    # 容量トラッカー: 各エンジニアの残スロット
    remaining_cap = {
        e["engineer_id"]: e["max_concurrent"] - (1 if e.get("fatigue_level", 0) > 0.6 else 0)
        for e in on_shift
    }

    def pick_assignee() -> str:
        """容量に余裕のあるエンジニアをランダムに選ぶ。"""
        available = [eid for eid, cap in remaining_cap.items() if cap > 0]
        if not available:
            return ""
        eid = random.choice(available)
        remaining_cap[eid] -= 1
        return eid

    # スキル別チケット数のバランスを保つ
    skill_queue = []
    for skill in SKILLS:
        titles = TICKET_TITLES.get(skill, [])
        for t in titles:
            skill_queue.append((skill, t))
    random.shuffle(skill_queue)

    def pick_title(skill: str) -> str:
        titles = TICKET_TITLES.get(skill, [f"{skill}関連チケット"])
        return random.choice(titles)

    def make_created_at(hours_ago: float) -> str:
        """T0 = 2026-03-30 14:00 基準で hours_ago 前の時刻。"""
        base_h = 14.0
        h = base_h - hours_ago
        day = 30
        while h < 0:
            h += 24
            day -= 1
        hh = int(h)
        mm = int((h - hh) * 60)
        return f"2026-03-{day:02d} {hh:02d}:{mm:02d}"

    def make_sla_deadline(created: str, sla_hours: int) -> str:
        # simplified: just add hours
        parts = created.split()
        day = int(parts[0].split("-")[2])
        hh, mm = map(int, parts[1].split(":"))
        total_h = hh + sla_hours
        while total_h >= 24:
            total_h -= 24
            day += 1
        return f"2026-03-{day:02d} {total_h:02d}:{mm:02d}"

    # --- 分布: 50 unassigned, 30 blocked, 120 in_progress ---

    # ===== P1 Critical (8 件) =====
    p1_skills_multi = [
        # 3-skill swarming tickets
        (["database", "infra", "security"], "本番DBクラスタ完全停止＋データ整合性疑い", 3, "L2"),
        (["network", "security", "cloud"], "コアネットワーク障害＋不正アクセス疑い", 3, "L2"),
        (["cloud", "container", "monitoring"], "本番Kubernetesクラスタ全ノード異常", 3, "L2"),
        # 2-skill swarming
        (["database", "app_support"], "決済基盤DB障害＋API全断", 2, "L2"),
        (["infra", "network"], "認証基盤(LDAP)応答停止＋DNS連鎖障害", 2, "L2"),
        (["security", "infra"], "ランサムウェア検知＋封じ込め対応", 2, "L3"),
        # Single-skill P1
        (["cloud"], "本番リージョン接続不可", 1, "L2"),
        (["app_support"], "決済APIタイムアウト—全トランザクション失敗", 1, "L2"),
    ]
    for skills_req, title, max_assignees, min_tier in p1_skills_multi:
        hours_ago = random.uniform(0.5, 6.0)
        created = make_created_at(hours_ago)
        sla_h = 4
        deadline = make_sla_deadline(created, sla_h)
        sla_remaining = round(sla_h - hours_ago + random.uniform(-1, 1), 1)
        sla_remaining = max(0.5, sla_remaining)

        status = random.choice(["in_progress", "in_progress", "unassigned"])
        assigned = ""
        progress = 0
        if status == "in_progress":
            assigned = pick_assignee()
            progress = random.randint(10, 50)

        tickets.append({
            "ticket_id": f"TK{tid:03d}",
            "type": "incident_critical",
            "title": title,
            "required_skills": ";".join(skills_req),
            "priority": "P1",
            "status": status,
            "created_at": created,
            "sla_deadline": deadline,
            "sla_remaining_hours": sla_remaining,
            "assigned_to": assigned,
            "min_tier": min_tier,
            "progress_pct": progress,
            "estimated_remaining_hours_mean": round(random.uniform(2.0, 5.0), 1),
            "estimated_remaining_hours_std": round(random.uniform(1.0, 2.5), 1),
            "confidence": round(random.uniform(0.3, 0.6), 2),
            "max_assignees": max_assignees,
            "swarming_roles": ",".join(["lead", "support", "observer"][:max_assignees]) if max_assignees > 1 else "lead",
            "vip_customer": random.random() < 0.5,
            "dependency_group": "",
        })
        tid += 1

    # ===== P2 High (25 件) =====
    p2_skills = [
        "database", "network", "security", "cloud", "infra",
        "app_support", "monitoring", "container", "ai_ml",
    ]
    for i in range(25):
        if i < 8:
            # 2-skill tickets
            s1, s2 = random.sample(p2_skills, 2)
            skills_req = [s1, s2]
            max_assignees = 2
            title = f"{pick_title(s1)}＋{s2}連携対応"
        elif i < 10:
            # 3-skill tickets
            s1, s2, s3 = random.sample(p2_skills, 3)
            skills_req = [s1, s2, s3]
            max_assignees = 2
            title = f"複合障害: {s1}/{s2}/{s3}"
        else:
            skills_req = [random.choice(p2_skills)]
            max_assignees = 1
            title = pick_title(skills_req[0])

        hours_ago = random.uniform(1.0, 24.0)
        created = make_created_at(hours_ago)
        sla_h = 12
        deadline = make_sla_deadline(created, sla_h)
        sla_remaining = round(max(0.5, sla_h - hours_ago + random.uniform(-2, 4)), 1)

        status = random.choices(
            ["in_progress", "blocked_vendor", "blocked_customer", "unassigned"],
            weights=[50, 10, 10, 30],
        )[0]
        assigned = ""
        progress = 0
        if status in ("in_progress", "blocked_vendor", "blocked_customer"):
            assigned = pick_assignee()
            progress = random.randint(5, 60)

        min_tier = random.choice(["L2", "L2", "L3"])
        tickets.append({
            "ticket_id": f"TK{tid:03d}",
            "type": "incident_high",
            "title": title,
            "required_skills": ";".join(skills_req),
            "priority": "P2",
            "status": status,
            "created_at": created,
            "sla_deadline": deadline,
            "sla_remaining_hours": sla_remaining,
            "assigned_to": assigned,
            "min_tier": min_tier,
            "progress_pct": progress,
            "estimated_remaining_hours_mean": round(random.uniform(1.5, 5.0), 1),
            "estimated_remaining_hours_std": round(random.uniform(0.5, 2.0), 1),
            "confidence": round(random.uniform(0.4, 0.7), 2),
            "max_assignees": max_assignees,
            "swarming_roles": "lead,support" if max_assignees > 1 else "lead",
            "vip_customer": random.random() < 0.3,
            "dependency_group": "",
        })
        tid += 1

    # ===== P3 Mid (87 件) =====
    p3_skills = SKILLS
    for i in range(87):
        if i < 15:
            s1, s2 = random.sample(p3_skills[:8], 2)
            skills_req = [s1, s2]
            max_assignees = random.choice([1, 2])
            title = f"{pick_title(s1)}＋{s2}対応"
        elif i < 18:
            s1, s2, s3 = random.sample(p3_skills[:8], 3)
            skills_req = [s1, s2, s3]
            max_assignees = 2
            title = f"複合対応: {s1}/{s2}/{s3}"
        else:
            skill = random.choice(p3_skills)
            skills_req = [skill]
            max_assignees = 1
            title = pick_title(skill)

        ttype = random.choice(["incident_mid", "incident_mid", "service_request", "change_standard"])
        hours_ago = random.uniform(2.0, 72.0)
        created = make_created_at(hours_ago)
        sla_h = 48
        deadline = make_sla_deadline(created, sla_h)
        sla_remaining = round(max(1.0, sla_h - hours_ago + random.uniform(-5, 10)), 1)

        status = random.choices(
            ["in_progress", "blocked_vendor", "blocked_approval",
             "blocked_customer", "blocked_dependency", "unassigned"],
            weights=[30, 5, 5, 5, 5, 50],
        )[0]
        assigned = ""
        progress = 0
        if status not in ("unassigned",):
            assigned = pick_assignee()
            progress = random.randint(0, 80)

        min_tier = random.choice(["L1", "L1", "L2"])
        tickets.append({
            "ticket_id": f"TK{tid:03d}",
            "type": ttype,
            "title": title,
            "required_skills": ";".join(skills_req),
            "priority": "P3",
            "status": status,
            "created_at": created,
            "sla_deadline": deadline,
            "sla_remaining_hours": sla_remaining,
            "assigned_to": assigned,
            "min_tier": min_tier,
            "progress_pct": progress,
            "estimated_remaining_hours_mean": round(random.uniform(1.0, 6.0), 1),
            "estimated_remaining_hours_std": round(random.uniform(0.3, 2.0), 1),
            "confidence": round(random.uniform(0.4, 0.8), 2),
            "max_assignees": max_assignees,
            "swarming_roles": "lead,support" if max_assignees > 1 else "lead",
            "vip_customer": random.random() < 0.1,
            "dependency_group": "",
        })
        tid += 1

    # ===== P4 Low (80 件) =====
    for i in range(80):
        if i < 5:
            s1, s2 = random.sample(p3_skills[:8], 2)
            skills_req = [s1, s2]
            max_assignees = 1
            title = f"{pick_title(s1)}＋{s2}調査"
        else:
            skill = random.choice(p3_skills)
            skills_req = [skill]
            max_assignees = 1
            title = pick_title(skill)

        ttype = random.choice(["incident_low", "incident_low", "service_request"])
        hours_ago = random.uniform(12.0, 168.0)
        created = make_created_at(hours_ago)
        sla_h = 168
        deadline = make_sla_deadline(created, sla_h)
        sla_remaining = round(max(5.0, sla_h - hours_ago + random.uniform(-10, 20)), 1)

        status = random.choices(
            ["in_progress", "blocked_vendor", "unassigned"],
            weights=[25, 10, 65],
        )[0]
        assigned = ""
        progress = 0
        if status != "unassigned":
            assigned = pick_assignee()
            progress = random.randint(0, 70)

        tickets.append({
            "ticket_id": f"TK{tid:03d}",
            "type": ttype,
            "title": title,
            "required_skills": ";".join(skills_req),
            "priority": "P4",
            "status": status,
            "created_at": created,
            "sla_deadline": deadline,
            "sla_remaining_hours": sla_remaining,
            "assigned_to": assigned,
            "min_tier": "L1",
            "progress_pct": progress,
            "estimated_remaining_hours_mean": round(random.uniform(0.5, 4.0), 1),
            "estimated_remaining_hours_std": round(random.uniform(0.2, 1.5), 1),
            "confidence": round(random.uniform(0.5, 0.9), 2),
            "max_assignees": max_assignees,
            "swarming_roles": "lead",
            "vip_customer": False,
            "dependency_group": "",
        })
        tid += 1

    return tickets


# ============================================================
# チケット依存 DAG
# ============================================================

def generate_dependencies(tickets: list[dict]) -> list[dict]:
    """チケット間の依存関係を生成（~25 エッジ）。"""
    deps = []

    # LDAP 障害 (TK005) → 認証系がブロック
    # 最初の P1 infra チケットを root にする
    infra_p1 = [t for t in tickets if "LDAP" in t["title"] or
                ("infra" in t["required_skills"] and t["priority"] == "P1")]

    # 障害連鎖グループを作る
    dep_id = 1

    # グループ1: LDAP障害 → 認証依存チケット (5件)
    root1 = tickets[4]  # TK005: LDAP系
    root1["dependency_group"] = "DEP_LDAP"
    auth_dependent = [t for t in tickets[30:100]
                      if t["status"] == "unassigned" and
                      any(s in t["required_skills"] for s in ["app_support", "security"])][:5]
    for t in auth_dependent:
        t["dependency_group"] = "DEP_LDAP"
        t["status"] = "blocked_dependency"
        deps.append({
            "dep_id": f"D{dep_id:03d}",
            "blocker_ticket_id": root1["ticket_id"],
            "blocked_ticket_id": t["ticket_id"],
            "dependency_type": "blocks",
            "description": f"LDAP復旧まで{t['title']}は対応不可",
        })
        dep_id += 1

    # グループ2: ネットワークコア障害 → 3件
    net_tickets = [t for t in tickets if "network" in t["required_skills"]
                   and t["priority"] in ("P1", "P2")]
    if len(net_tickets) >= 2:
        root2 = net_tickets[0]
        root2["dependency_group"] = "DEP_NET"
        for t in net_tickets[1:4]:
            t["dependency_group"] = "DEP_NET"
            deps.append({
                "dep_id": f"D{dep_id:03d}",
                "blocker_ticket_id": root2["ticket_id"],
                "blocked_ticket_id": t["ticket_id"],
                "dependency_type": "blocks",
                "description": f"ネットワーク復旧後に{t['title']}を対応",
            })
            dep_id += 1

    # グループ3: DB障害 → データ系チケット (4件)
    db_tickets = [t for t in tickets if "database" in t["required_skills"]]
    if len(db_tickets) >= 3:
        root3 = db_tickets[0]
        root3["dependency_group"] = "DEP_DB"
        for t in db_tickets[1:5]:
            t["dependency_group"] = "DEP_DB"
            deps.append({
                "dep_id": f"D{dep_id:03d}",
                "blocker_ticket_id": root3["ticket_id"],
                "blocked_ticket_id": t["ticket_id"],
                "dependency_type": "blocks",
                "description": f"DB復旧後に{t['title']}を実施",
            })
            dep_id += 1

    # グループ4: セキュリティインシデント → パッチ適用の順序 (3件)
    sec_tickets = [t for t in tickets if "security" in t["required_skills"]
                   and t["type"] != "incident_critical"][:4]
    if len(sec_tickets) >= 3:
        # Chain: sec[0] → sec[1] → sec[2]
        for i in range(len(sec_tickets) - 1):
            sec_tickets[i]["dependency_group"] = "DEP_SEC"
            sec_tickets[i + 1]["dependency_group"] = "DEP_SEC"
            deps.append({
                "dep_id": f"D{dep_id:03d}",
                "blocker_ticket_id": sec_tickets[i]["ticket_id"],
                "blocked_ticket_id": sec_tickets[i + 1]["ticket_id"],
                "dependency_type": "sequence",
                "description": f"{sec_tickets[i]['title']}完了後に{sec_tickets[i+1]['title']}",
            })
            dep_id += 1

    # グループ5: クラウド移行系の順序依存 (4件)
    cloud_tickets = [t for t in tickets if "cloud" in t["required_skills"]
                     and t["priority"] in ("P3", "P4")][:5]
    if len(cloud_tickets) >= 3:
        root5 = cloud_tickets[0]
        root5["dependency_group"] = "DEP_CLOUD"
        for t in cloud_tickets[1:4]:
            t["dependency_group"] = "DEP_CLOUD"
            deps.append({
                "dep_id": f"D{dep_id:03d}",
                "blocker_ticket_id": root5["ticket_id"],
                "blocked_ticket_id": t["ticket_id"],
                "dependency_type": "preferred_order",
                "description": f"{root5['title']}を先にやると効率的",
            })
            dep_id += 1

    # 追加: 同一エンジニアが担当すべきペア (related)
    related_pairs = []
    for i in range(6):
        t1 = tickets[random.randint(30, 150)]
        t2 = tickets[random.randint(30, 150)]
        if t1["ticket_id"] != t2["ticket_id"]:
            deps.append({
                "dep_id": f"D{dep_id:03d}",
                "blocker_ticket_id": t1["ticket_id"],
                "blocked_ticket_id": t2["ticket_id"],
                "dependency_type": "related",
                "description": "同一エンジニアが担当すると効率的",
            })
            dep_id += 1

    return deps


# ============================================================
# 制約定義
# ============================================================

def generate_constraints() -> list[dict]:
    return [
        # Hard Constraints
        {"constraint_id": "HC01", "type": "skill_match",
         "description": "チケットの必要スキルをエンジニアが全て保有していること",
         "hard_or_soft": "hard", "weight": "", "details": "all(s in engineer.skills for s in ticket.required_skills)"},
        {"constraint_id": "HC02", "type": "tier_requirement",
         "description": "チケットの最低ティア要件を満たすこと",
         "hard_or_soft": "hard", "weight": "", "details": "engineer.tier >= ticket.min_tier"},
        {"constraint_id": "HC03", "type": "shift_available",
         "description": "アサイン先エンジニアが該当タイムステップで勤務中であること",
         "hard_or_soft": "hard", "weight": "", "details": "engineer.on_shift(time_period) == True"},
        {"constraint_id": "HC04", "type": "capacity_limit",
         "description": "同時担当チケット数が上限を超えないこと（疲労係数込み）",
         "hard_or_soft": "hard", "weight": "", "details": "current_load + new_load <= max_concurrent * (1 - fatigue_penalty)"},
        {"constraint_id": "HC05", "type": "swarming_roles",
         "description": "スワーミングチケットでは必要な役割（lead/support/observer）を全て充足",
         "hard_or_soft": "hard", "weight": "", "details": "lead は min_tier 以上、support は min_tier-1 以上"},
        {"constraint_id": "HC06", "type": "swarming_lead_unique",
         "description": "スワーミングチケットの lead は1人のみ",
         "hard_or_soft": "hard", "weight": "", "details": "count(role=lead) == 1 per swarming ticket"},
        {"constraint_id": "HC07", "type": "dependency_order",
         "description": "blocker チケットが完了/進行中でないと blocked チケットに着手不可",
         "hard_or_soft": "hard", "weight": "", "details": "blocks/sequence 依存が未解決なら unassigned のまま"},
        {"constraint_id": "HC08", "type": "escalation_cooldown",
         "description": "エスカレーション後30分は同チケットの再エスカレーション不可",
         "hard_or_soft": "hard", "weight": "", "details": "escalation_cooldown_minutes >= 30"},
        {"constraint_id": "HC09", "type": "pair_forbidden",
         "description": "禁止ペアのエンジニアを同一スワーミングチケットに同時アサインしない",
         "hard_or_soft": "hard", "weight": "", "details": "team_constraints の forbidden ペアを参照"},
        {"constraint_id": "HC10", "type": "l4_critical_only",
         "description": "L4 エンジニアは P1 または P2+VIP のチケットにのみアサイン可能",
         "hard_or_soft": "hard", "weight": "", "details": "ticket.priority in (P1) or (P2 and vip_customer)"},
        {"constraint_id": "HC11", "type": "multi_skill_coverage",
         "description": "マルチスキルチケットでは、スワーミングメンバー全体で全必要スキルをカバー",
         "hard_or_soft": "hard", "weight": "", "details": "union(member.skills) ⊇ ticket.required_skills"},
        {"constraint_id": "HC12", "type": "max_swarming_per_engineer",
         "description": "1人のエンジニアが同時に参加できるスワーミングは最大2件",
         "hard_or_soft": "hard", "weight": "", "details": "count(swarming_tickets) <= 2"},
        {"constraint_id": "HC13", "type": "night_shift_minimum",
         "description": "夜勤帯（T3）で最低3名のオンシフトエンジニアを維持",
         "hard_or_soft": "hard", "weight": "", "details": "count(on_shift at T3) >= 3"},
        {"constraint_id": "HC14", "type": "vip_response_time",
         "description": "VIP顧客チケットは受付後1時間以内にアサイン完了",
         "hard_or_soft": "hard", "weight": "", "details": "vip_customer and time_to_assign <= 1h"},
        {"constraint_id": "HC15", "type": "escalation_tier_up",
         "description": "エスカレーションは必ず現在の担当より上位ティアに行うこと",
         "hard_or_soft": "hard", "weight": "", "details": "escalation_target.tier > current_assignee.tier"},

        # Soft Constraints
        {"constraint_id": "SC01", "type": "sla_priority",
         "description": "SLA残時間が短いチケットを優先的にアサイン（非線形ペナルティ）",
         "hard_or_soft": "soft", "weight": "100",
         "details": "sla_penalties.csv の3段階ペナルティを適用"},
        {"constraint_id": "SC02", "type": "skill_proficiency",
         "description": "解決実績の多いスキル×エンジニア組合せを優先",
         "hard_or_soft": "soft", "weight": "70",
         "details": "resolution_history の平均解決時間と分散を考慮"},
        {"constraint_id": "SC03", "type": "load_balance",
         "description": "エンジニア間の負荷を均等化（疲労度加重）",
         "hard_or_soft": "soft", "weight": "50",
         "details": "effective_load = tickets * (1 + fatigue_level) の標準偏差を最小化"},
        {"constraint_id": "SC04", "type": "minimize_reassignment",
         "description": "既存アサインの変更を最小化",
         "hard_or_soft": "soft", "weight": "40",
         "details": "reassignment_count を最小化、引き継ぎコスト +30min を加算"},
        {"constraint_id": "SC05", "type": "tier_efficiency",
         "description": "可能な限り低いティアで解決（L3/L4を温存）",
         "hard_or_soft": "soft", "weight": "30",
         "details": "min_tier を満たす最低ティアを優先、L4温存は weight x2"},
        {"constraint_id": "SC06", "type": "uncertainty_robust",
         "description": "解決時間の不確実性を考慮したロバスト配置",
         "hard_or_soft": "soft", "weight": "60",
         "details": "CVaR(95%) で SLA 違反リスクを評価、高分散チケットは余裕を持たせる"},
        {"constraint_id": "SC07", "type": "mentoring_pair",
         "description": "スワーミングでジュニア(L1)とシニア(L3+)をペアにし育成機会を確保",
         "hard_or_soft": "soft", "weight": "15",
         "details": "observer ロールに L1 を配置、mentor に mentoring_eligible=True を配置"},
        {"constraint_id": "SC08", "type": "dependency_group_same_engineer",
         "description": "related 依存のチケットは同一エンジニアに集約",
         "hard_or_soft": "soft", "weight": "25",
         "details": "dependency_type=related のペアは同じ assigned_to を優先"},
        {"constraint_id": "SC09", "type": "future_capacity_reserve",
         "description": "将来タイムステップの予測到着分の容量を確保",
         "hard_or_soft": "soft", "weight": "35",
         "details": "time_periods.csv の predicted_arrivals に基づき余裕を残す"},
        {"constraint_id": "SC10", "type": "fatigue_avoidance",
         "description": "疲労度が高いエンジニアへの新規アサインを抑制",
         "hard_or_soft": "soft", "weight": "20",
         "details": "fatigue_level > 0.6 のエンジニアは新規アサインのペナルティ x2"},
    ]


# ============================================================
# 解決履歴
# ============================================================

def generate_resolution_history(engineers: list[dict]) -> list[dict]:
    """~1,500 件の解決履歴（分布推定用）。"""
    history = []
    hid = 1

    tier_speed = {"L1": 1.0, "L2": 0.7, "L3": 0.5, "L4": 0.4}
    skill_base_hours = {
        "helpdesk": 0.5, "app_support": 1.5, "monitoring": 1.2,
        "network": 2.0, "database": 2.0, "cloud": 1.8,
        "security": 2.5, "infra": 2.0, "container": 1.8,
        "ai_ml": 3.0, "sap": 3.5, "iot": 2.5,
    }

    for eng in engineers:
        skills = eng["skills"].split(",")
        tier = eng["tier"]
        exp = eng["experience_years"]

        # 各スキルで 5-10 件の履歴
        for skill in skills:
            n_records = random.randint(5, 10)
            base = skill_base_hours.get(skill, 2.0)
            speed = tier_speed[tier]
            exp_factor = max(0.5, 1.0 - exp * 0.02)

            for _ in range(n_records):
                hours = round(max(0.2,
                    base * speed * exp_factor * random.lognormvariate(0, 0.3)
                ), 2)
                # multi-skill 案件の場合は時間が長め
                is_multi = random.random() < 0.15
                if is_multi:
                    hours = round(hours * random.uniform(1.3, 2.0), 2)

                history.append({
                    "record_id": f"H{hid:04d}",
                    "engineer_id": eng["engineer_id"],
                    "skill": skill,
                    "resolution_hours": hours,
                    "was_multi_skill": is_multi,
                    "was_swarming": is_multi and random.random() < 0.4,
                    "role_in_swarming": random.choice(["lead", "support", ""]) if is_multi else "",
                    "priority": random.choice(["P1", "P2", "P3", "P3", "P4"]),
                    "outcome": random.choices(
                        ["resolved", "escalated", "resolved_with_workaround"],
                        weights=[70, 15, 15],
                    )[0],
                })
                hid += 1

    return history


# ============================================================
# エスカレーションルール
# ============================================================

def generate_escalation_rules() -> list[dict]:
    return [
        {"rule_id": "ESC01", "from_tier": "L1", "to_tier": "L2",
         "trigger_condition": "elapsed_without_progress >= 90min",
         "handoff_cost_minutes": 30,
         "description": "L1が90分進捗なしならL2にエスカレーション"},
        {"rule_id": "ESC02", "from_tier": "L2", "to_tier": "L3",
         "trigger_condition": "elapsed_without_progress >= 120min OR sla_remaining < 2h",
         "handoff_cost_minutes": 45,
         "description": "L2が120分進捗なし、またはSLA残2時間未満でL3へ"},
        {"rule_id": "ESC03", "from_tier": "L3", "to_tier": "L4",
         "trigger_condition": "sla_remaining < 1h AND priority == P1",
         "handoff_cost_minutes": 15,
         "description": "P1でSLA残1時間未満はL4に即エスカレーション（引き継ぎコスト最小）"},
        {"rule_id": "ESC04", "from_tier": "L1", "to_tier": "L3",
         "trigger_condition": "priority == P1 AND skill_match_confidence < 0.5",
         "handoff_cost_minutes": 30,
         "description": "P1でL1のスキル適合度が低い場合、L2をスキップしてL3へ"},
        {"rule_id": "ESC05", "from_tier": "any", "to_tier": "L4",
         "trigger_condition": "ticket.type == change_emergency",
         "handoff_cost_minutes": 15,
         "description": "緊急変更は直接L4が判断"},
    ]


# ============================================================
# SLA ペナルティ（非線形）
# ============================================================

def generate_sla_penalties() -> list[dict]:
    return [
        # P1
        {"priority": "P1", "stage": "warning", "threshold_hours_remaining": 2.0,
         "penalty_multiplier": 2.0, "description": "P1 SLA残2時間: ペナルティ2倍"},
        {"priority": "P1", "stage": "violation", "threshold_hours_remaining": 0.5,
         "penalty_multiplier": 5.0, "description": "P1 SLA残30分: ペナルティ5倍"},
        {"priority": "P1", "stage": "critical_violation", "threshold_hours_remaining": 0.0,
         "penalty_multiplier": 20.0, "description": "P1 SLA超過: ペナルティ20倍"},
        # P2
        {"priority": "P2", "stage": "warning", "threshold_hours_remaining": 4.0,
         "penalty_multiplier": 1.5, "description": "P2 SLA残4時間: ペナルティ1.5倍"},
        {"priority": "P2", "stage": "violation", "threshold_hours_remaining": 1.0,
         "penalty_multiplier": 4.0, "description": "P2 SLA残1時間: ペナルティ4倍"},
        {"priority": "P2", "stage": "critical_violation", "threshold_hours_remaining": 0.0,
         "penalty_multiplier": 10.0, "description": "P2 SLA超過: ペナルティ10倍"},
        # P3
        {"priority": "P3", "stage": "warning", "threshold_hours_remaining": 8.0,
         "penalty_multiplier": 1.2, "description": "P3 SLA残8時間: ペナルティ1.2倍"},
        {"priority": "P3", "stage": "violation", "threshold_hours_remaining": 2.0,
         "penalty_multiplier": 3.0, "description": "P3 SLA残2時間: ペナルティ3倍"},
        {"priority": "P3", "stage": "critical_violation", "threshold_hours_remaining": 0.0,
         "penalty_multiplier": 6.0, "description": "P3 SLA超過: ペナルティ6倍"},
        # P4
        {"priority": "P4", "stage": "warning", "threshold_hours_remaining": 24.0,
         "penalty_multiplier": 1.1, "description": "P4 SLA残24時間: ペナルティ1.1倍"},
        {"priority": "P4", "stage": "violation", "threshold_hours_remaining": 4.0,
         "penalty_multiplier": 2.0, "description": "P4 SLA残4時間: ペナルティ2倍"},
        {"priority": "P4", "stage": "critical_violation", "threshold_hours_remaining": 0.0,
         "penalty_multiplier": 4.0, "description": "P4 SLA超過: ペナルティ4倍"},
        # VIP 追加ペナルティ
        {"priority": "VIP", "stage": "any", "threshold_hours_remaining": -1,
         "penalty_multiplier": 1.5, "description": "VIP顧客チケットは全段階で追加1.5倍"},
    ]


# ============================================================
# タイムステップ
# ============================================================

def generate_time_periods() -> list[dict]:
    return [
        {
            "period_id": "T0", "time": "2026-03-30 14:00",
            "description": "現在（日勤+遅番が稼働中）",
            "shifts_active": "day,late",
            "available_engineers": 34,
            "predicted_new_tickets_p1": 1, "predicted_new_tickets_p2": 2,
            "predicted_new_tickets_p3": 5, "predicted_new_tickets_p4": 3,
            "prediction_confidence": 0.7,
            "blocked_unblock_probability": 0.1,
            "notes": "月曜午後、インシデント多め",
        },
        {
            "period_id": "T1", "time": "2026-03-30 16:00",
            "description": "+2h（日勤ラスト2時間）",
            "shifts_active": "day,late",
            "available_engineers": 34,
            "predicted_new_tickets_p1": 0, "predicted_new_tickets_p2": 1,
            "predicted_new_tickets_p3": 3, "predicted_new_tickets_p4": 2,
            "prediction_confidence": 0.6,
            "blocked_unblock_probability": 0.2,
            "notes": "日勤エンジニアの引き継ぎ準備開始",
        },
        {
            "period_id": "T2", "time": "2026-03-30 18:00",
            "description": "+4h（日勤終了、遅番のみ）",
            "shifts_active": "late",
            "available_engineers": 14,
            "predicted_new_tickets_p1": 0, "predicted_new_tickets_p2": 1,
            "predicted_new_tickets_p3": 2, "predicted_new_tickets_p4": 1,
            "prediction_confidence": 0.5,
            "blocked_unblock_probability": 0.05,
            "notes": "人数激減。P1エスカレーション対応に要注意",
        },
        {
            "period_id": "T3", "time": "2026-03-30 22:00",
            "description": "+8h（遅番→夜勤交代）",
            "shifts_active": "night",
            "available_engineers": 9,
            "predicted_new_tickets_p1": 0, "predicted_new_tickets_p2": 0,
            "predicted_new_tickets_p3": 1, "predicted_new_tickets_p4": 1,
            "prediction_confidence": 0.4,
            "blocked_unblock_probability": 0.02,
            "notes": "最少人数。重大障害発生時はL4 on-call 呼出",
        },
    ]


# ============================================================
# チーム制約（組織・政治）
# ============================================================

def generate_team_constraints(engineers: list[dict]) -> list[dict]:
    eids = [e["engineer_id"] for e in engineers]
    return [
        # 禁止ペア
        {"constraint_id": "TC01", "type": "forbidden_pair",
         "engineer_1": "E003", "engineer_2": "E007",
         "description": "過去のインシデント対応で意見対立。同一スワーミングに配置しない"},
        {"constraint_id": "TC02", "type": "forbidden_pair",
         "engineer_1": "E021", "engineer_2": "E025",
         "description": "コミュニケーションスタイルの不一致。同一チケット回避"},
        {"constraint_id": "TC03", "type": "forbidden_pair",
         "engineer_1": "E038", "engineer_2": "E042",
         "description": "同一チームのL3同士。障害時は別チケットに分散して冗長性確保"},

        # メンタリングペア
        {"constraint_id": "TC04", "type": "mentoring_pair",
         "engineer_1": "E037", "engineer_2": "E002",
         "description": "E037(L3)がE002(L1)を育成中。週2回以上のペア対応を推奨"},
        {"constraint_id": "TC05", "type": "mentoring_pair",
         "engineer_1": "E041", "engineer_2": "E010",
         "description": "E041(L3)がE010(L1)のセキュリティスキル育成中"},
        {"constraint_id": "TC06", "type": "mentoring_pair",
         "engineer_1": "E047", "engineer_2": "E015",
         "description": "E047(L4)がE015(L1)のクラウド基盤育成中"},

        # 専門チーム制約
        {"constraint_id": "TC07", "type": "team_coverage",
         "engineer_1": "", "engineer_2": "",
         "description": "セキュリティチーム(E011,E025,E038,E047)のうち最低1名はアサイン可能状態を維持"},
        {"constraint_id": "TC08", "type": "team_coverage",
         "engineer_1": "", "engineer_2": "",
         "description": "DB専門家(E021,E031,E037,E048)のうち最低1名はアサイン可能状態を維持"},

        # VIP 指名
        {"constraint_id": "TC09", "type": "vip_preference",
         "engineer_1": "E047", "engineer_2": "",
         "description": "VIP顧客A社の案件はE047(L4)がlead担当を強く希望"},
        {"constraint_id": "TC10", "type": "vip_preference",
         "engineer_1": "E041", "engineer_2": "",
         "description": "VIP顧客B社はE041(L3)との信頼関係あり。可能な限りアサイン"},

        # 新人制限
        {"constraint_id": "TC11", "type": "junior_restriction",
         "engineer_1": "", "engineer_2": "",
         "description": "経験1年以下(E001,E003,E005,E007)はP1単独アサイン不可。スワーミングのobserverは可"},
    ]


# ============================================================
# シナリオパラメータ (JSON)
# ============================================================

def generate_scenario_params() -> dict:
    return {
        "problem_name": "ticket_assignment_advanced",
        "description": "50エンジニア×200チケット×4タイムステップの全部盛りチケットアサイン最適化",
        "version": "1.0",
        "base_time": "2026-03-30T14:00:00",
        "time_horizon_hours": 8,

        "uncertainty": {
            "resolution_time": {
                "model": "lognormal",
                "description": "解決時間はエンジニア×スキルごとの対数正規分布に従う",
                "parameters_source": "resolution_history.csv から推定",
                "confidence_threshold": 0.5,
                "fallback": "カテゴリ平均 → 優先度別デフォルト",
            },
            "block_unblock": {
                "model": "geometric",
                "description": "ブロック解除はタイムステップごとの幾何分布",
                "per_period_probabilities": {
                    "blocked_vendor": {"T0": 0.1, "T1": 0.2, "T2": 0.05, "T3": 0.02},
                    "blocked_approval": {"T0": 0.3, "T1": 0.4, "T2": 0.1, "T3": 0.05},
                    "blocked_customer": {"T0": 0.15, "T1": 0.2, "T2": 0.1, "T3": 0.05},
                    "blocked_dependency": "ticket_dependencies.csv の blocker 完了に連動",
                },
            },
            "new_arrivals": {
                "model": "poisson",
                "description": "新チケット到着はポアソン過程。time_periods.csv の予測値がλ",
                "arrival_skill_distribution": {
                    "app_support": 0.20, "helpdesk": 0.15, "network": 0.12,
                    "cloud": 0.12, "database": 0.10, "security": 0.10,
                    "infra": 0.08, "monitoring": 0.06, "container": 0.04,
                    "ai_ml": 0.02, "sap": 0.01,
                },
                "multi_skill_probability": 0.15,
            },
        },

        "fatigue": {
            "model": "linear_degradation",
            "description": "疲労度に応じて解決時間が劣化",
            "formula": "effective_hours = base_hours * (1 + 0.5 * fatigue_level)",
            "fatigue_increase_per_ticket": 0.05,
            "recovery_per_idle_hour": 0.1,
        },

        "swarming": {
            "max_team_size": 3,
            "roles": {
                "lead": {"min_tier_offset": 0, "description": "min_tier以上。調査・判断を担当"},
                "support": {"min_tier_offset": -1, "description": "min_tier-1以上。復旧作業を担当"},
                "observer": {"min_tier_offset": -2, "description": "ティア制限なし。学習・記録を担当"},
            },
            "efficiency_bonus": {
                "2_person": 0.35,
                "3_person": 0.50,
                "description": "2人なら35%、3人なら50%の時間短縮（ただし人的コスト増）",
            },
        },

        "risk_evaluation": {
            "method": "CVaR",
            "confidence_level": 0.95,
            "description": "95% CVaR: 最悪5%のシナリオでの平均SLA違反数を最小化",
            "n_scenarios": 100,
            "scenario_seed": 42,
        },

        "optimization": {
            "solver": "CP-SAT",
            "time_limit_seconds": 120,
            "strategy": "two_stage_stochastic",
            "description": "第1段階: 現在の確定情報で最適化、第2段階: 不確実性シナリオで評価",
        },
    }


# ============================================================
# CSV / JSON 書き出し
# ============================================================

def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {path.name}: {len(rows)} rows")


def main() -> None:
    print("=== ticket_assignment_advanced データ生成 ===\n")

    engineers = generate_engineers()
    write_csv(OUT / "engineers.csv", engineers)

    tickets = generate_tickets(engineers)
    deps = generate_dependencies(tickets)
    write_csv(OUT / "tickets.csv", tickets)
    write_csv(OUT / "ticket_dependencies.csv", deps)

    constraints = generate_constraints()
    write_csv(OUT / "constraints.csv", constraints)

    history = generate_resolution_history(engineers)
    write_csv(OUT / "resolution_history.csv", history)

    escalation = generate_escalation_rules()
    write_csv(OUT / "escalation_rules.csv", escalation)

    penalties = generate_sla_penalties()
    write_csv(OUT / "sla_penalties.csv", penalties)

    periods = generate_time_periods()
    write_csv(OUT / "time_periods.csv", periods)

    team = generate_team_constraints(engineers)
    write_csv(OUT / "team_constraints.csv", team)

    params = generate_scenario_params()
    params_path = OUT / "scenario_params.json"
    with open(params_path, "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=2)
    print(f"  {params_path.name}: written")

    # サマリー
    print(f"\n=== サマリー ===")
    print(f"  エンジニア: {len(engineers)} 名")
    tiers = {}
    for e in engineers:
        tiers[e['tier']] = tiers.get(e['tier'], 0) + 1
    print(f"    {tiers}")
    print(f"  チケット: {len(tickets)} 件")
    by_priority = {}
    for t in tickets:
        by_priority[t['priority']] = by_priority.get(t['priority'], 0) + 1
    print(f"    {by_priority}")
    by_status = {}
    for t in tickets:
        by_status[t['status']] = by_status.get(t['status'], 0) + 1
    print(f"    {by_status}")
    multi = sum(1 for t in tickets if ";" in t["required_skills"])
    swarm = sum(1 for t in tickets if t["max_assignees"] > 1)
    print(f"    マルチスキル: {multi} 件, スワーミング対象: {swarm} 件")
    print(f"  依存関係: {len(deps)} エッジ")
    print(f"  解決履歴: {len(history)} 件")
    print(f"  制約: HC {sum(1 for c in constraints if c['hard_or_soft']=='hard')}"
          f" + SC {sum(1 for c in constraints if c['hard_or_soft']=='soft')}")


if __name__ == "__main__":
    main()
