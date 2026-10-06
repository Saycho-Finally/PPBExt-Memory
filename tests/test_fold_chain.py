"""fold_chain 回归测试（2026-10-07 修复后补）。

背景：旧实现返回的一直是输入 id 的一到两份拷贝，从不返回真实折叠链；
循环体内还有 `for p in self.pages: pass` 死代码与无条件 break。
本测试锁定正确语义：链按**从旧到新**返回，且对链上任意一环给出同一结果。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memorycore import MemoryPage, MemoryStore, PageKind  # noqa: E402

RESULTS = []


def check(name, cond, note=""):
    s = "PASS" if cond else "FAIL"
    RESULTS.append((name, s))
    print(f"  [{s}] {name}" + (f" ---- {note}" if note else ""))


def build():
    s = MemoryStore()
    p1 = s.add(MemoryPage(kind=PageKind.PREFERENCE.value, content="喜欢 React"))
    p2 = s.add(MemoryPage(kind=PageKind.PREFERENCE.value, content="改用 Svelte",
                          supersedes=p1.page_id))
    p3 = s.add(MemoryPage(kind=PageKind.PREFERENCE.value, content="改回 React",
                          supersedes=p2.page_id))
    return s, [p1.page_id, p2.page_id, p3.page_id]


def test_chain():
    print("三条链：从旧到新")
    s, ids = build()
    for i, pid in enumerate(ids):
        got = s.fold_chain(pid)
        check(f"从任一环进入都得全链（第 {i + 1} 环）", got == ids, str(got))
    check("链不含重复 id", len(set(s.fold_chain(ids[1]))) == 3)


def test_edges():
    print("边界")
    s, ids = build()
    lone = s.add(MemoryPage(kind=PageKind.FACT.value, content="孤立页"))
    check("孤立页返回单元素链", s.fold_chain(lone.page_id) == [lone.page_id])
    check("未知 id 返回其自身", s.fold_chain("nope") == ["nope"])

    s2 = MemoryStore()
    a = s2.add(MemoryPage(kind=PageKind.FACT.value, content="A"))
    b = s2.add(MemoryPage(kind=PageKind.FACT.value, content="B", supersedes=a.page_id))
    check("两页链", s2.fold_chain(a.page_id) == [a.page_id, b.page_id])


def test_no_cycle():
    print("环保护")
    s = MemoryStore()
    a = s.add(MemoryPage(kind=PageKind.FACT.value, content="A"))
    b = s.add(MemoryPage(kind=PageKind.FACT.value, content="B", supersedes=a.page_id))
    # 人为造环：让 a 也声称取代 b
    a.supersedes = b.page_id
    got = s.fold_chain(a.page_id)
    check("成环不死循环且不重复", len(got) == len(set(got)), str(got))


if __name__ == "__main__":
    print("=" * 60)
    print("PPBExt-Memory：fold_chain 回归")
    print("=" * 60)
    test_chain()
    test_edges()
    test_no_cycle()
    print("=" * 60)
    n_pass = sum(1 for r in RESULTS if r[1] == "PASS")
    print(f"总计：{n_pass}/{len(RESULTS)} PASS")
    print("FOLD_CHAIN_OK" if n_pass == len(RESULTS) else "FOLD_CHAIN_FAIL")
    sys.exit(0 if n_pass == len(RESULTS) else 1)
