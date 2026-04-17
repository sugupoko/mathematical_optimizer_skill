"""ticket_assignment_advanced 構造的改善。

目的関数の改善ではなく「問題の構造」を変えて容量ボトルネックを解消する。

打ち手1: ブロックチケットのスロット解放 (release_blocked=True)
  → blocked チケットはエンジニアのスロットを消費しないとみなす
  → L3: +8スロット, L2: +10スロット

打ち手2: L2→L1への既存チケット委譲 (reassign_l1_capable)
  → L2が持つ min_tier=L1 チケットを L1 に移す
  → L2: +8スロット解放

打ち手3: オフシフト L3 の呼び出し (call_in_l3)
  → E045, E046 を on_shift にする
  → L3: +6スロット追加

打ち手4: P1 スワーミングの observer 省略 (trim_observer)
  → 3人→2人チームで 3スロット節約

全部盛りで最大 +25 スロットの L2+ 容量確保。
"""

from __future__ import annotations

import csv
import json
import math
import random
import statistics
import time
from pathlib import Path

from ortools.sat.python import cp_model

DATA = Path(__file__).resolve().parent.parent.parent / "data"
RESULTS = Path(__file__).resolve().parent.parent / "results"

# ============================================================
# データ読み込み・ユーティリティ (improve.py から共通)
# ============================================================

def load_csv(name):
    with open(DATA / name, encoding="utf-8") as f: return list(csv.DictReader(f))

def load_json(name):
    with open(DATA / name, encoding="utf-8") as f: return json.load(f)

TIER_ORDER = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}
def tier_ge(a, b): return TIER_ORDER.get(a, 0) >= TIER_ORDER.get(b, 0)
def tier_val(t): return TIER_ORDER.get(t, 0)

class ResolutionEstimator:
    def __init__(self, history):
        self.personal, self.category = {}, {}
        for r in history:
            self.personal.setdefault((r["engineer_id"], r["skill"]), []).append(r["resolution_hours"])
            self.category.setdefault(r["skill"], []).append(r["resolution_hours"])
    def estimate(self, eid, skill, priority):
        k = (eid, skill)
        if k in self.personal and len(self.personal[k]) >= 3:
            d = self.personal[k]
            return statistics.mean(d), (statistics.stdev(d) if len(d)>1 else .5), min(.9, .7+.02*(len(d)-3))
        if skill in self.category:
            d = self.category[skill]
            return statistics.mean(d), (statistics.stdev(d) if len(d)>1 else 1.), .3
        return {"P1":4.,"P2":8.,"P3":24.,"P4":72.}.get(priority,24.), 5., .1

def load_all():
    engineers = load_csv("engineers.csv")
    tickets = load_csv("tickets.csv")
    deps = load_csv("ticket_dependencies.csv")
    history = load_csv("resolution_history.csv")
    penalties = load_csv("sla_penalties.csv")
    team = load_csv("team_constraints.csv")
    params = load_json("scenario_params.json")
    for e in engineers:
        e["skills"]=e["skills"].split(","); e["max_concurrent"]=int(e["max_concurrent"])
        e["experience_years"]=int(e["experience_years"]); e["on_shift"]=e["on_shift"]=="True"
        e["fatigue_level"]=float(e["fatigue_level"]); e["mentoring_eligible"]=e["mentoring_eligible"]=="True"
    for t in tickets:
        t["required_skills"]=t["required_skills"].split(";"); t["sla_remaining_hours"]=float(t["sla_remaining_hours"])
        t["progress_pct"]=int(t["progress_pct"]); t["estimated_remaining_hours_mean"]=float(t["estimated_remaining_hours_mean"])
        t["estimated_remaining_hours_std"]=float(t["estimated_remaining_hours_std"])
        t["confidence"]=float(t["confidence"]); t["max_assignees"]=int(t["max_assignees"])
        t["vip_customer"]=t["vip_customer"]=="True"
    for h in history: h["resolution_hours"]=float(h["resolution_hours"])
    for p in penalties: p["threshold_hours_remaining"]=float(p["threshold_hours_remaining"]); p["penalty_multiplier"]=float(p["penalty_multiplier"])
    return {"engineers":engineers,"tickets":tickets,"dependencies":deps,"history":history,"penalties":penalties,"team":team,"params":params}


# ============================================================
# 構造的改善の適用
# ============================================================

def apply_structural_changes(data, *, release_blocked=False, reassign_l1=False, call_in_l3=False, trim_observer=False):
    """データを変更して容量を拡大する。元データは変更しない。"""
    import copy
    d = copy.deepcopy(data)

    changes = []

    # 打ち手1: blocked チケットのスロット解放
    if release_blocked:
        freed = {"L1":0,"L2":0,"L3":0,"L4":0}
        on_shift_ids = {e["engineer_id"]:e for e in d["engineers"] if e["on_shift"]}
        for t in d["tickets"]:
            if "blocked" in t["status"] and t["assigned_to"] in on_shift_ids:
                eng = on_shift_ids[t["assigned_to"]]
                # blocked チケットを「スロット非消費」にする = assigned_to をクリアせず status だけ記録
                # ソルバーの容量計算で blocked を除外する
                freed[eng["tier"]] += 1
        changes.append(f"打ち手1: blocked スロット解放 → {freed}")

    # 打ち手2: L2→L1 への委譲
    reassigned = []
    if reassign_l1:
        on_shift = [e for e in d["engineers"] if e["on_shift"]]
        load = {e["engineer_id"]:0 for e in on_shift}
        for t in d["tickets"]:
            if t["assigned_to"] and t["status"]!="resolved" and t["assigned_to"] in load:
                load[t["assigned_to"]] += 1

        for t in d["tickets"]:
            if t["status"]=="in_progress" and t["min_tier"]=="L1" and t["assigned_to"]:
                eng = next((e for e in on_shift if e["engineer_id"]==t["assigned_to"]), None)
                if eng and eng["tier"] in ("L2","L3","L4"):
                    l1_candidates = [e for e in on_shift if e["tier"]=="L1"
                                    and all(s in e["skills"] for s in t["required_skills"])
                                    and max(0, int(e["max_concurrent"])-load[e["engineer_id"]]) > 0]
                    if l1_candidates:
                        best = min(l1_candidates, key=lambda e: load[e["engineer_id"]])
                        old = t["assigned_to"]
                        t["assigned_to"] = best["engineer_id"]
                        load[old] -= 1
                        load[best["engineer_id"]] += 1
                        reassigned.append((t["ticket_id"], old, best["engineer_id"]))
        changes.append(f"打ち手2: L2→L1 委譲 {len(reassigned)}件")

    # 打ち手3: オフシフト L3 呼び出し
    called_in = []
    if call_in_l3:
        for e in d["engineers"]:
            if e["tier"] in ("L3",) and not e["on_shift"] and e["fatigue_level"] < 0.6:
                e["on_shift"] = True
                called_in.append(e["engineer_id"])
        changes.append(f"打ち手3: L3 呼出 {called_in}")

    # 打ち手4: P1 observer 省略
    trimmed = []
    if trim_observer:
        for t in d["tickets"]:
            if t["priority"]=="P1" and t["max_assignees"]==3:
                t["max_assignees"] = 2
                t["swarming_roles"] = "lead,support"
                trimmed.append(t["ticket_id"])
        changes.append(f"打ち手4: observer 省略 {trimmed}")

    return d, changes


# ============================================================
# ソルバー (改善B ベース + 構造変更)
# ============================================================

def solve_with_structure(data, *, release_blocked=False, time_limit=120):
    engineers = [e for e in data["engineers"] if e["on_shift"]]
    tickets = data["tickets"]
    penalties = data["penalties"]
    deps = data["dependencies"]
    team = data["team"]
    estimator = ResolutionEstimator(data["history"])

    to_assign = [t for t in tickets if t["status"]=="unassigned"]
    # blocked_dependency 除外
    blocked_dep = set()
    for d in deps:
        if d["dependency_type"] in ("blocks","sequence"):
            blocker = next((t for t in tickets if t["ticket_id"]==d["blocker_ticket_id"]),None)
            if blocker and blocker["status"]!="resolved":
                blocked_dep.add(d["blocked_ticket_id"])
    to_assign = [t for t in to_assign if t["ticket_id"] not in blocked_dep]

    # 負荷計算 (release_blocked で blocked を除外)
    load = {e["engineer_id"]:0 for e in engineers}
    for t in tickets:
        if t["assigned_to"] and t["assigned_to"] in load:
            if t["status"]=="resolved":
                continue
            if release_blocked and "blocked" in t["status"]:
                continue
            load[t["assigned_to"]] += 1

    forbidden = set()
    for tc in team:
        if tc["type"]=="forbidden_pair" and tc["engineer_1"] and tc["engineer_2"]:
            forbidden.add((tc["engineer_1"],tc["engineer_2"]))
            forbidden.add((tc["engineer_2"],tc["engineer_1"]))

    n_eng = len(engineers)
    priority_weight = {"P1":50,"P2":20,"P3":5,"P4":1}

    model = cp_model.CpModel()

    x = {}
    swarming_tickets, single_tickets = [], []
    for t_idx, ticket in enumerate(to_assign):
        if ticket["max_assignees"] > 1:
            swarming_tickets.append((t_idx, ticket))
            roles = ticket["swarming_roles"].split(",")
            for r_idx in range(len(roles)):
                for e_idx in range(n_eng):
                    x[t_idx,e_idx,r_idx] = model.new_bool_var(f"x_{t_idx}_{e_idx}_{r_idx}")
        else:
            single_tickets.append((t_idx, ticket))
            for e_idx in range(n_eng):
                x[t_idx,e_idx,0] = model.new_bool_var(f"x_{t_idx}_{e_idx}")

    # HC01: スキル
    for t_idx, ticket in single_tickets:
        for e_idx, eng in enumerate(engineers):
            if not all(s in eng["skills"] for s in ticket["required_skills"]):
                model.add(x[t_idx,e_idx,0]==0)

    # HC02: ティア
    for t_idx, ticket in single_tickets:
        for e_idx, eng in enumerate(engineers):
            if not tier_ge(eng["tier"], ticket["min_tier"]):
                model.add(x[t_idx,e_idx,0]==0)

    for t_idx, ticket in swarming_tickets:
        roles = ticket["swarming_roles"].split(",")
        for r_idx, role in enumerate(roles):
            for e_idx, eng in enumerate(engineers):
                if role=="lead" and not tier_ge(eng["tier"], ticket["min_tier"]):
                    model.add(x[t_idx,e_idx,r_idx]==0)
                elif role=="support":
                    if tier_val(eng["tier"]) < max(1, tier_val(ticket["min_tier"])-1):
                        model.add(x[t_idx,e_idx,r_idx]==0)

    # HC05/06: スワーミングロール
    for t_idx, ticket in swarming_tickets:
        roles = ticket["swarming_roles"].split(",")
        lead_vars = [x[t_idx,e_idx,0] for e_idx in range(n_eng)]
        for r_idx in range(len(roles)):
            model.add(sum(x[t_idx,e_idx,r_idx] for e_idx in range(n_eng)) <= 1)
        for r_idx in range(1, len(roles)):
            model.add(sum(x[t_idx,e_idx,r_idx] for e_idx in range(n_eng)) <= sum(lead_vars))
        for e_idx in range(n_eng):
            model.add(sum(x[t_idx,e_idx,r_idx] for r_idx in range(len(roles))) <= 1)

    # HC11: マルチスキルカバレッジ
    for t_idx, ticket in swarming_tickets:
        roles = ticket["swarming_roles"].split(",")
        la = model.new_bool_var(f"la_{t_idx}")
        lv = [x[t_idx,e_idx,0] for e_idx in range(n_eng)]
        model.add(sum(lv)>=1).only_enforce_if(la)
        model.add(sum(lv)==0).only_enforce_if(la.Not())
        for skill in ticket["required_skills"]:
            caps = [x[t_idx,e_idx,r] for r in range(len(roles)) for e_idx,eng in enumerate(engineers) if skill in eng["skills"]]
            if caps:
                model.add(sum(caps)>=1).only_enforce_if(la)

    # 単一チケット <= 1
    for t_idx, ticket in single_tickets:
        model.add(sum(x[t_idx,e_idx,0] for e_idx in range(n_eng)) <= 1)

    # HC04: 容量
    for e_idx, eng in enumerate(engineers):
        fp = 2 if eng["fatigue_level"]>0.8 else (1 if eng["fatigue_level"]>0.6 else 0)
        cap = max(0, eng["max_concurrent"] - load.get(eng["engineer_id"],0) - fp)
        all_v = []
        for t_idx,_ in single_tickets: all_v.append(x[t_idx,e_idx,0])
        for t_idx,ticket in swarming_tickets:
            for r_idx in range(len(ticket["swarming_roles"].split(","))):
                all_v.append(x[t_idx,e_idx,r_idx])
        model.add(sum(all_v) <= cap)

    # HC09: 禁止ペア
    for t_idx, ticket in swarming_tickets:
        roles = ticket["swarming_roles"].split(",")
        for e1 in range(n_eng):
            for e2 in range(e1+1, n_eng):
                if (engineers[e1]["engineer_id"], engineers[e2]["engineer_id"]) in forbidden:
                    for r1 in range(len(roles)):
                        for r2 in range(len(roles)):
                            if r1!=r2:
                                model.add(x[t_idx,e1,r1]+x[t_idx,e2,r2]<=1)

    # HC10: L4
    for t_idx, ticket in single_tickets+swarming_tickets:
        is_sw = ticket["max_assignees"]>1
        for e_idx, eng in enumerate(engineers):
            if eng["tier"]=="L4":
                ok = ticket["priority"]=="P1" or (ticket["priority"]=="P2" and ticket["vip_customer"])
                if not ok:
                    if is_sw:
                        for r in range(len(ticket["swarming_roles"].split(","))):
                            model.add(x[t_idx,e_idx,r]==0)
                    else:
                        model.add(x[t_idx,e_idx,0]==0)

    # HC12: スワーミング同時参加 <= 2
    for e_idx in range(n_eng):
        parts = []
        for t_idx, ticket in swarming_tickets:
            roles = ticket["swarming_roles"].split(",")
            p = model.new_bool_var(f"sp_{t_idx}_{e_idx}")
            rv = [x[t_idx,e_idx,r] for r in range(len(roles))]
            model.add(sum(rv)>=1).only_enforce_if(p)
            model.add(sum(rv)==0).only_enforce_if(p.Not())
            parts.append(p)
        if parts:
            model.add(sum(parts)<=2)

    # P1 割当保証
    for t_idx, ticket in single_tickets:
        if ticket["priority"]=="P1":
            eligible = [e_idx for e_idx,eng in enumerate(engineers)
                       if all(s in eng["skills"] for s in ticket["required_skills"]) and tier_ge(eng["tier"],ticket["min_tier"])]
            if eligible:
                model.add(sum(x[t_idx,e_idx,0] for e_idx in eligible)>=1)

    # 目的関数 (改善Bベース: ロバスト + 依存ボーナス)
    dep_bonus_cache = {}
    for d in deps:
        bid = d["blocker_ticket_id"]
        bt = next((t for t in tickets if t["ticket_id"]==d["blocked_ticket_id"]),None)
        if bt:
            dep_bonus_cache[bid] = dep_bonus_cache.get(bid,0) + {"P1":200,"P2":100,"P3":30,"P4":10}.get(bt["priority"],10)

    obj = []
    for t_idx, ticket in single_tickets:
        pw = priority_weight[ticket["priority"]]
        sla = ticket["sla_remaining_hours"]
        sla_s = 500 if sla<=0.5 else int(200*(2./max(.1,sla))) if sla<=2 else int(100*(8./max(.1,sla))) if sla<=8 else 10
        if ticket["vip_customer"]: sla_s=int(sla_s*1.5)
        db = dep_bonus_cache.get(ticket["ticket_id"],0)
        for e_idx, eng in enumerate(engineers):
            s = sla_s*pw
            m,sd,c = estimator.estimate(eng["engineer_id"],ticket["required_skills"][0],ticket["priority"])
            s += max(0,int((1./max(.1,m))*50*c))
            fm = 1.+.5*eng["fatigue_level"]
            s += max(0,int((1./max(.1,sd*fm))*40))
            s -= (tier_val(eng["tier"])-tier_val(ticket["min_tier"]))*10
            if eng["fatigue_level"]>.6: s-=30
            s += max(0,20-load.get(eng["engineer_id"],0)*4)
            s += db
            obj.append(x[t_idx,e_idx,0]*max(0,s))

    for t_idx, ticket in swarming_tickets:
        pw = priority_weight[ticket["priority"]]
        sla = ticket["sla_remaining_hours"]
        sla_s = 500 if sla<=0.5 else int(200*(2./max(.1,sla))) if sla<=2 else int(100*(8./max(.1,sla))) if sla<=8 else 10
        if ticket["vip_customer"]: sla_s=int(sla_s*1.5)
        db = dep_bonus_cache.get(ticket["ticket_id"],0)
        roles = ticket["swarming_roles"].split(",")
        for r_idx, role in enumerate(roles):
            rw = {"lead":1.,"support":.6,"observer":.2}.get(role,.5)
            for e_idx, eng in enumerate(engineers):
                s = int(sla_s*pw*rw)
                if role=="lead":
                    m,sd,c = estimator.estimate(eng["engineer_id"],ticket["required_skills"][0],ticket["priority"])
                    s += max(0,int((1./max(.1,m))*40*c))
                    s += max(0,int((1./max(.1,sd*(1.+.5*eng["fatigue_level"])))*30))
                if role=="observer" and eng["tier"]=="L1": s+=15
                if eng["fatigue_level"]>.6: s-=20
                s += int(db*rw)
                obj.append(x[t_idx,e_idx,r_idx]*max(0,s))

    model.maximize(sum(obj))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 8
    start = time.time()
    status = solver.solve(model)
    wall = time.time()-start

    sn = {cp_model.OPTIMAL:"OPTIMAL",cp_model.FEASIBLE:"FEASIBLE",cp_model.INFEASIBLE:"INFEASIBLE"}.get(status,"UNKNOWN")

    assignments = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for t_idx, ticket in single_tickets:
            for e_idx, eng in enumerate(engineers):
                if solver.value(x[t_idx,e_idx,0]):
                    assignments[ticket["ticket_id"]] = {"engineer_id":eng["engineer_id"],"role":"lead","engineer_name":eng["name"],"engineer_tier":eng["tier"]}
        for t_idx, ticket in swarming_tickets:
            roles = ticket["swarming_roles"].split(",")
            tm = []
            for r_idx, role in enumerate(roles):
                for e_idx, eng in enumerate(engineers):
                    if solver.value(x[t_idx,e_idx,r_idx]):
                        tm.append({"engineer_id":eng["engineer_id"],"role":role,"engineer_name":eng["name"],"engineer_tier":eng["tier"]})
            if tm:
                assignments[ticket["ticket_id"]] = tm

    return {
        "assignments": assignments,
        "solver_info": {"status":sn,"objective":solver.objective_value if status in (cp_model.OPTIMAL,cp_model.FEASIBLE) else None,
                       "wall_time":round(wall,2),"num_variables":len(x),"num_constraints":len(model.proto.constraints)},
        "assigned_count": len(assignments),
        "unassigned_count": len(to_assign)-len(assignments),
    }


def evaluate_scenarios(data, assignments, n_scenarios=100):
    tickets = {t["ticket_id"]:t for t in data["tickets"]}
    est = ResolutionEstimator(data["history"])
    params = data["params"]
    random.seed(42)
    violations_list = []
    for _ in range(n_scenarios):
        v = 0
        for tid, a in assignments.items():
            t = tickets.get(tid)
            if not t: continue
            if isinstance(a, list):
                lead = next((m for m in a if m["role"]=="lead"),None)
                if not lead: continue
                eid = lead["engineer_id"]; bonus = params["swarming"]["efficiency_bonus"].get(f"{len(a)}_person",0)
            else:
                eid = a["engineer_id"]; bonus = 0
            m,sd,_ = est.estimate(eid, t["required_skills"][0], t["priority"])
            eng = next((e for e in data["engineers"] if e["engineer_id"]==eid),None)
            if eng: fm=1.+.5*eng["fatigue_level"]; m*=fm; sd*=fm
            m *= (1.-bonus)
            if sd>0 and m>0:
                s2=math.log(1+(sd/m)**2); mu=math.log(m)-s2/2
                sampled=random.lognormvariate(mu,math.sqrt(s2))
            else: sampled=m
            if sampled > t["sla_remaining_hours"]: v+=1
        violations_list.append(v)
    violations_list.sort(reverse=True)
    w5 = violations_list[:max(1,n_scenarios//20)]
    return {"mean":round(statistics.mean(violations_list),1),"median":statistics.median(violations_list),
            "min":min(violations_list),"max":max(violations_list),"cvar_95":round(statistics.mean(w5),1)}


# ============================================================
# メイン
# ============================================================

def main():
    data = load_all()
    RESULTS.mkdir(parents=True, exist_ok=True)

    print("="*60)
    print("  構造的改善: 容量ボトルネック解消")
    print("="*60)

    scenarios = [
        {"name":"S1: blocked解放のみ",          "release_blocked":True, "reassign_l1":False,"call_in_l3":False,"trim_observer":False},
        {"name":"S2: L2→L1委譲のみ",            "release_blocked":False,"reassign_l1":True, "call_in_l3":False,"trim_observer":False},
        {"name":"S3: blocked解放+L2→L1委譲",     "release_blocked":True, "reassign_l1":True, "call_in_l3":False,"trim_observer":False},
        {"name":"S4: S3+L3呼出",                "release_blocked":True, "reassign_l1":True, "call_in_l3":True, "trim_observer":False},
        {"name":"S5: 全部盛り(S4+observer省略)", "release_blocked":True, "reassign_l1":True, "call_in_l3":True, "trim_observer":True},
    ]

    all_results = {}
    for sc in scenarios:
        name = sc.pop("name")
        print(f"\n{'='*40}")
        print(f"  {name}")
        print(f"{'='*40}")

        d, changes = apply_structural_changes(data, **sc)
        for c in changes:
            print(f"  {c}")

        result = solve_with_structure(d, release_blocked=sc.get("release_blocked",False))
        print(f"  Status: {result['solver_info']['status']} ({result['solver_info']['wall_time']}s)")
        print(f"  割当: {result['assigned_count']} / 未割当: {result['unassigned_count']}")

        ev = evaluate_scenarios(d, result["assignments"]) if result["assignments"] else {}
        result["scenario_evaluation"] = ev
        if ev:
            print(f"  CVaR(95%): {ev['cvar_95']}, 平均違反: {ev['mean']}, 最大: {ev['max']}")

        # P1/P2
        assigned_ids = set(result["assignments"].keys())
        unassigned = [t for t in d["tickets"] if t["status"]=="unassigned"]
        for p in ["P1","P2"]:
            total = sum(1 for t in unassigned if t["priority"]==p)
            done = sum(1 for t in unassigned if t["priority"]==p and t["ticket_id"] in assigned_ids)
            print(f"  {p}: {done}/{total}")

        # P1 詳細
        for t in unassigned:
            if t["priority"]=="P1" and t["ticket_id"] in assigned_ids:
                a = result["assignments"][t["ticket_id"]]
                if isinstance(a,list):
                    ms = ", ".join(f'{m["engineer_name"]}({m["engineer_tier"]},{m["role"]})' for m in a)
                    print(f"    {t['ticket_id']}: [{ms}]")
                else:
                    print(f"    {t['ticket_id']}: {a['engineer_name']}({a['engineer_tier']})")

        all_results[name] = {
            "solver_info": result["solver_info"],
            "assigned_count": result["assigned_count"],
            "unassigned_count": result["unassigned_count"],
            "scenario_evaluation": ev,
            "changes": changes,
        }

    with open(RESULTS / "improve_structural_results.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n  結果を {RESULTS/'improve_structural_results.json'} に保存")


if __name__ == "__main__":
    main()
