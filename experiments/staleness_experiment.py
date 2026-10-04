"""staleness 折叠实测：三策略对照（naive 追加 / delete 删除 / fold 折叠）。

场景：用户偏好演化 12 轮（含精化、改口、回退、冲突），每轮组装记忆并测量：
  1. 正确性：当前有效偏好是否可见（assembled 文本含最新偏好）
  2. 陈旧暴露：已失效偏好是否仍出现在组装文本（naive 会累积）
  3. 冲突度：组装文本同时含矛盾偏好的比例
  4. 缓存代价：与上一轮组装文本的前缀重合度（fold 应最高）
  5. 审计完整性：能否回答"当前偏好是怎么演化来的"（折叠链 vs 删除的丢失）

零 API 成本（纯机制对比）。LLM 侧回答验证等 key（见文末设计）。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.environ.get("ADDENDA_DECIDE_ROOT", "../../addenda-decide"))

from memorycore import (MemoryController, MemoryPage, MemoryStore,  # noqa: E402
                        PageKind, PromptComposer)

# ---- 偏好演化序列（12 轮，含精化/改口/回退/并行偏好）----
EVOLUTION = [
    ("preference", "喜欢用 React 写前端", "t1"),
    ("preference", "喜欢用 React 写前端", "t1"),                      # 重复（NOOP 场景）
    ("preference", "喜欢用 React 和 TypeScript", "t2"),              # 精化
    ("preference", "改用 Svelte，觉得更简洁", "t3"),                  # 改口
    ("fact", "项目代号 Aurora", "t1"),                          # 非偏好事实
    ("preference", "Svelte 的响应式写法很顺手", "t4"),                # 同向补充
    ("preference", "还是回 React 吧，生态更全", "t5"),                # 回退
    ("fact", "部署在东京区", "t2"),
    ("preference", "React 的 hooks 需要多练习", "t6"),                # 精化（当前偏好）
    ("lesson", "前端选型不要只看简洁度", "t5"),                  # 教训页
    ("preference", "接受 Vue 用于小型项目", "t7"),                    # 并行偏好（非矛盾）
    ("preference", "React 是主力，Vue 只做小工具", "t8"),              # 收敛
]

CUR_PREF_MARKERS = [
    (1, "React"), (4, "Svelte"), (7, "React"), (12, "React"),
]


def strategy_naive(store, kind, content, prov):
    """朴素：全部追加，无失效机制。"""
    return store.add(MemoryPage(kind=kind, content=content, provenance=prov))


def strategy_delete(store, kind, content, prov):
    """删除式：新偏好到来时物理删除同 kind 的旧页（append-only 破坏）。"""
    if kind == PageKind.PREFERENCE.value:
        store.pages = [p for p in store.pages if p.kind != kind]
    return store.add(MemoryPage(kind=kind, content=content, provenance=prov))


def strategy_fold(store, kind, content, prov, ctl_holder):
    """折叠式（默认判定器：字符级 Jaccard）。"""
    ctl = ctl_holder["ctl"]
    return ctl.ingest(PageKind(kind), content, provenance=prov)


TOPIC_WORDS = ["React", "Svelte", "Vue", "TypeScript"]


def topic_similarity(a: str, b: str) -> float:
    """语义判定器的代理实现（零成本）：提取技术主题词比对——
    模拟"嵌入/LLM 判定能给语义相反的偏好高分"。真实实验用 LLM 判定（待 key）。"""
    ta = {w for w in TOPIC_WORDS if w in a}
    tb = {w for w in TOPIC_WORDS if w in b}
    if not ta or not tb:
        return 0.0
    # 同主题（都提到同一框架）→ 高相似（视为可取代/精化关系）
    return 0.8 if (ta & tb) else 0.0   # UPDATE 区间（0.5-0.92）触发折叠而非 NOOP


def strategy_fold_sem(store, kind, content, prov, ctl_holder):
    """折叠式（语义判定器）：验证判定器升级后折叠生效。"""
    ctl = ctl_holder["ctl"]
    return ctl.ingest(PageKind(kind), content, provenance=prov)


def run_strategy(name, ingest_fn) -> dict:
    store = MemoryStore()
    comp = PromptComposer(kind_budgets={"preference": 400, "decision": 200,
                                        "fact": 300, "lesson": 200},
                          stability_threshold=0.5)
    ctl_holder = {}
    if name in ("fold", "fold_sem"):
        dc = None
        try:
            from decisioncore import DecisionCore
            dc = DecisionCore()
        except ImportError:
            pass
        sim = topic_similarity if name == "fold_sem" else None
        ctl_holder["ctl"] = MemoryController(store, dc=dc, similarity_fn=sim)

    rows = []
    prev_text = None
    for i, (kind, content, prov) in enumerate(EVOLUTION, 1):
        if name == "naive":
            ingest_fn(store, kind, content, prov)
        elif name == "delete":
            ingest_fn(store, kind, content, prov)
        else:
            ingest_fn(store, kind, content, prov, ctl_holder)

        folded = [x for x in store.pages if x.lifecycle == 'folded']
        r = comp.compose(store.active_pages(), folded_pages=folded)
        # 指标（诚实口径）：
        #   cur_visible：当前有效偏好（本轮 content 若是 preference）在组装文本中
        #   conflicting：组装文本同时含"当前偏好"与任一"已被取代的偏好"（冲突暴露）
        pref_so_far = [(k, c) for k, c, _ in EVOLUTION[:i] if k == "preference"]
        cur_content = content if kind == "preference" else (
            pref_so_far[-1][1] if pref_so_far else "")
        visible = bool(cur_content) and cur_content in r.text
        # 冲突检测：组装文本中出现的 preference 内容集合里，既有当前又有旧
        shown = [c for k, c in pref_so_far if c in r.text]
        conflicting = visible and any(c != cur_content for c in shown)
        rows.append({
            "turn": i, "kind": kind, "cur": cur_content[:12],
            "cur_visible": visible, "conflicting": conflicting,
            "n_pref_shown": len(set(shown)),
            "prefix_overlap": r.prefix_overlap, "stable": r.stable,
            "tokens": r.tokens, "n_active": len(store.active_pages()),
        })
        prev_text = r.text

    # 汇总
    pref_rows = [x for x in rows if x["kind"] == "preference"]
    n_cur_ok = sum(1 for x in pref_rows if x["cur_visible"])
    n_conflict = sum(1 for x in pref_rows if x["conflicting"])
    overlaps = [x["prefix_overlap"] for x in rows if x["prefix_overlap"] is not None]
    avg_overlap = sum(overlaps) / len(overlaps) if overlaps else 0
    # 审计：能否回答"当前偏好取代了什么"（fold 需折叠链；naive 全留但无标记；
    # delete 物理删除即不可追）
    stats = store.stats()
    if name in ("fold", "fold_sem"):
        audit_ok = stats["fold_pages"] >= 1     # 折叠链存在即可追
    elif name == "naive":
        audit_ok = True                          # 全保留（但需人工分辨时效）
    else:
        audit_ok = False
    return {
        "strategy": name,
        "cur_visible_rate": round(n_cur_ok / max(len(pref_rows), 1), 3),
        "conflict_turns": n_conflict,
        "avg_prefix_overlap": round(avg_overlap, 3),
        "final_active_pages": rows[-1]["n_active"],
        "final_tokens": rows[-1]["tokens"],
        "fold_pages": stats["fold_pages"],
        "audit_recoverable": audit_ok,
        "sim_cache_hits": (ctl_holder["ctl"].cache_hits
                           if name.startswith("fold") else 0),
        "rows": rows,
    }


def main() -> None:
    print("=" * 72)
    print("staleness 折叠实验：三策略对照（12 轮偏好演化，零 API 成本）")
    print("=" * 72)
    results = []
    for name, fn in [("naive", strategy_naive), ("delete", strategy_delete),
                     ("fold", strategy_fold), ("fold_sem", strategy_fold_sem)]:
        r = run_strategy(name, fn)
        results.append(r)
        print(f"\n[{name}] 当前偏好可见率={r['cur_visible_rate']} "
              f"冲突轮数={r['conflict_turns']} "
              f"平均前缀重合={r['avg_prefix_overlap']} "
              f"活跃页={r['final_active_pages']} 折叠页={r['fold_pages']} "
              f"审计可追={r['audit_recoverable']}")

    print("\n" + "=" * 72)
    print("对照总表")
    print("=" * 72)
    print(f"{'策略':8s} {'偏好可见':>8s} {'冲突轮':>6s} {'前缀重合':>8s} "
          f"{'活跃页':>6s} {'折叠页':>6s} {'审计':>5s}")
    for r in results:
        print(f"{r['strategy']:8s} {r['cur_visible_rate']:>8.2f} "
              f"{r['conflict_turns']:>6d} {r['avg_prefix_overlap']:>8.2f} "
              f"{r['final_active_pages']:>6d} {r['fold_pages']:>6d} "
              f"{'✓' if r['audit_recoverable'] else '✗':>5s}")

    import json
    out = {"meta": {"turns": len(EVOLUTION), "zero_api": True},
           "results": [{k: v for k, v in r.items() if k != "rows"} for r in results],
           "detail": {r["strategy"]: r["rows"] for r in results}}
    os.makedirs("results", exist_ok=True)
    with open("results/staleness_experiment.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nSAVED results/staleness_experiment.json")

    # ---- LLM 侧验证设计（等 key）----
    print("""
LLM 侧验证设计（待 key，预算 < $0.1）：
  在每轮组装后，向模型提问"用户当前偏好什么前端框架？"
  - 期望：fold 策略下回答正确率最高（旧偏好已失效声明）
  - naive 策略：模型可能纠结于多版本偏好（陈旧干扰）
  - delete 策略：回答正确但无法追问"怎么演化的"（审计缺失）
  指标：回答正确率 × 追问可答率（双维）。""")


if __name__ == "__main__":
    main()
