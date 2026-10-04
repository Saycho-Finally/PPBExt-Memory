"""PPBExt-Memory 核心测试：页生命周期 / 组装确定性 / 前缀稳定性 / 折叠 / 决策审计。"""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.environ.get("ADDENDA_DECIDE_ROOT", "../../addenda-decide"))

from memorycore import (MemoryController, MemoryPage, MemoryStore,  # noqa: E402
                        PageKind, PromptComposer)

RESULTS = []


def check(name, cond, note=""):
    s = "PASS" if cond else "FAIL"
    RESULTS.append((name, s))
    print(f"  [{s}] {name}" + (f" —— {note}" if note else ""))


def test_pages():
    print("页与页库（append-only）")
    store = MemoryStore()
    p1 = store.add(MemoryPage(kind=PageKind.PREFERENCE.value, content="偏好中文回复"))
    store.add(MemoryPage(kind=PageKind.FACT.value, content="项目叫 Addenda"))
    check("页 id 确定性", p1.page_id == MemoryPage(
        kind=PageKind.PREFERENCE.value, content="偏好中文回复").finalize().page_id)
    check("重复内容同 id", store.add(MemoryPage(
        kind=PageKind.PREFERENCE.value, content="偏好中文回复")).page_id == p1.page_id)
    check("active 计数", len(store.active_pages()) == 3)


def test_fold():
    print("折叠（staleness 的 append-only 解）")
    store = MemoryStore()
    old = store.add(MemoryPage(kind=PageKind.PREFERENCE.value, content="喜欢 React"))
    store.fold(old.page_id, reason="偏好更新为 Svelte")
    check("折叠后旧页退出组装", old.page_id not in
          [p.page_id for p in store.active_pages()])
    check("旧页仍在库中（append-only）",
          any(p.page_id == old.page_id for p in store.pages))
    check("折叠页记账", store.stats()["fold_pages"] == 1)


def test_composer_determinism():
    print("组装确定性 + 前缀稳定性")
    store = MemoryStore()
    kinds = [PageKind.PREFERENCE, PageKind.PREFERENCE, PageKind.FACT,
             PageKind.FACT, PageKind.LESSON]
    for i, c in enumerate(["偏好A", "偏好B", "事实X", "事实Y", "教训Z"]):
        store.add(MemoryPage(kind=kinds[i].value, content=c))
    pages = store.active_pages()
    r1 = PromptComposer().compose(pages)
    shuffled = pages[:]
    random.shuffle(shuffled)
    r2 = PromptComposer().compose(shuffled)
    check("顺序无关的确定性组装", r1.text == r2.text)
    store.add(MemoryPage(kind=PageKind.LESSON.value, content="教训W"))
    comp = PromptComposer()
    comp.compose(pages)   # 建立 last_text
    r3 = comp.compose(store.active_pages())
    check("增量追加后前缀重合度高", r3.prefix_overlap is not None and
          r3.prefix_overlap >= 0.5, f"overlap={r3.prefix_overlap:.2f}")
    comp3 = PromptComposer(stability_threshold=0.99)
    allp = store.active_pages()
    comp3.compose(allp[:1])
    r4 = comp3.compose(allp[1:])
    check("重组装触发稳定性检查", r4.stable is False and r4.prefix_overlap < 0.99)
    comp4 = PromptComposer(kind_budgets={"preference": 5, "decision": 0,
                                         "fact": 5, "lesson": 0})
    r5 = comp4.compose(store.active_pages())
    check("预算裁剪生效", r5.tokens <= 10, f"tokens={r5.tokens}")


def test_controller():
    print("控制器：ADD/UPDATE/NOOP/FOLD + 决策审计")
    store = MemoryStore()
    dc = None
    try:
        from decisioncore import DecisionCore
        dc = DecisionCore()
        print("    （DecisionCore 已接入，审计启用）")
    except ImportError:
        print("    （DecisionCore 不可用，降级模式）")
    ctl = MemoryController(store, dc=dc)
    a1 = ctl.ingest(PageKind.PREFERENCE, "偏好中文回复")
    check("ADD", a1.op == "add")
    a2 = ctl.ingest(PageKind.PREFERENCE, "偏好中文回复")
    check("NOOP（重复）", a2.op == "noop")
    a3 = ctl.ingest(PageKind.PREFERENCE, "偏好中文回复，简洁优先")
    check("UPDATE（折叠旧页）", a3.op == "update" and
          store.stats()["fold_pages"] == 1)
    a4 = ctl.fold(a3.page_id, reason="用户改回旧偏好")
    check("显式 FOLD", a4.op == "fold")
    if dc is not None:
        check("决策审计落账", all(a.decision_id for a in ctl.actions),
              f"{sum(1 for a in ctl.actions if a.decision_id)}/{len(ctl.actions)}"
              " 有 decision_id")
    rep = ctl.report()
    check("控制器报告", rep["n_actions"] == 4 and "store" in rep)


if __name__ == "__main__":
    print("=" * 60)
    print("PPBExt-Memory 核心测试")
    print("=" * 60)
    test_pages()
    test_fold()
    test_composer_determinism()
    test_controller()
    print("=" * 60)
    n_pass = sum(1 for r in RESULTS if r[1] == "PASS")
    print(f"总计：{n_pass}/{len(RESULTS)} PASS")
    print("MEMORY_OK" if n_pass == len(RESULTS) else "MEMORY_FAIL")
