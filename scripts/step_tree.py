"""从 STEP 装配文件中抽取父子结构树（产品结构）—— 层级 ground truth 生成器

纯 Python，无第三方依赖。解析 PRODUCT / PRODUCT_DEFINITION_FORMATION /
PRODUCT_DEFINITION / NEXT_ASSEMBLY_USAGE_OCCURRENCE 四类实体，
构建 总成 -> 子总成 -> 零件 的树。

用法:
  python step_tree.py <file.stp> [out.json]     # 抽取树, 打印并(可选)存 JSON
  python step_tree.py --compare gt.json pred.json   # 拿你的模型输出和 GT 对比打分
"""

import json
import re
import sys
from collections import Counter

WANTED = {
    "PRODUCT",
    "PRODUCT_DEFINITION_FORMATION",
    "PRODUCT_DEFINITION",
    "NEXT_ASSEMBLY_USAGE_OCCURRENCE",
}


def split_args(s):
    """按顶层逗号切分参数，正确处理引号与嵌套括号。"""
    args, buf, depth, inq = [], [], 0, False
    for ch in s:
        if inq:
            buf.append(ch)
            if ch == "'":
                inq = False
        elif ch == "'":
            inq = True
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        args.append(tail)
    return args


def extract_entities(text):
    """返回 {entity_id: (type, [args])}，只解析 WANTED 中的类型。"""
    ents = {}
    pat = re.compile(r"#(\d+)\s*=\s*([A-Z0-9_]+)\s*\(")
    n = len(text)
    for m in pat.finditer(text):
        etype = m.group(2)
        if etype not in WANTED:
            continue
        j = m.end()
        depth, inq = 1, False
        while j < n and depth > 0:
            c = text[j]
            if inq:
                if c == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 1  # '' 转义引号
                    else:
                        inq = False
            elif c == "'":
                inq = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            j += 1
        ents[m.group(1)] = (etype, split_args(text[m.end(): j - 1]))
    return ents


def decode_step_text(s):
    """解码 STEP 字符串转义: \\X2\\XXXX...\\X0\\ (UCS-2)、\\X\\XX (单字节)、去除断行。"""
    def ucs2(m):
        body = m.group(1)
        try:
            return "".join(chr(int(body[i:i + 4], 16)) for i in range(0, len(body), 4))
        except ValueError:
            return m.group(0)
    s = re.sub(r"\\X2\\([0-9A-Fa-f]*)\\X0\\", ucs2, s)
    s = re.sub(r"\\X\\([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), s)
    s = s.replace("\\X\\", "")
    s = re.sub(r"[\r\n]+", "", s)  # 导出器长行断行
    return s.strip()


def deref(arg):
    m = re.match(r"#(\d+)", arg or "")
    return m.group(1) if m else None


def build_tree(path):
    text = open(path, encoding="latin-1").read()
    ents = extract_entities(text)

    prod_name = {}   # product_id -> (id_str, name)
    pdf2prod = {}    # formation_id -> product_id
    pd2pdf = {}      # product_definition_id -> formation_id
    edges = []       # (nauo_id, parent_pd, child_pd)

    for eid, (t, a) in ents.items():
        if t == "PRODUCT":
            pid = decode_step_text(a[0].strip("'"))
            prod_name[eid] = (pid, decode_step_text(a[1].strip("'")) or pid)
        elif t == "PRODUCT_DEFINITION_FORMATION":
            r = deref(a[2] if len(a) > 2 else None)
            if r:
                pdf2prod[eid] = r
        elif t == "PRODUCT_DEFINITION":
            r = deref(a[2] if len(a) > 2 else None)
            if r:
                pd2pdf[eid] = r
        elif t == "NEXT_ASSEMBLY_USAGE_OCCURRENCE":
            if len(a) >= 5:
                p, c = deref(a[3]), deref(a[4])
                if p and c:
                    edges.append((eid, p, c))

    def pd2product(pd):
        pdf = pd2pdf.get(pd)
        return pdf2prod.get(pdf) if pdf else None

    children = {}   # parent_product -> [(nauo_id, child_product)]
    child_set = set()
    for nauo, p_pd, c_pd in edges:
        p, c = pd2product(p_pd), pd2product(c_pd)
        if p and c:
            children.setdefault(p, []).append((nauo, c))
            child_set.add(c)

    roots = [pid for pid in prod_name if pid in children and pid not in child_set]
    if not roots:
        raise SystemExit("错误: 没找到装配根节点（此文件可能不含 NEXT_ASSEMBLY_USAGE_OCCURRENCE 结构）")

    def make_node(pid):
        _, name = prod_name.get(pid, ("?", pid))
        kids = children.get(pid, [])
        # 同名子件合并，记数量
        merged = {}
        for nauo, c in kids:
            cname = prod_name.get(c, (c, c))[1]
            merged.setdefault(cname, []).append(c)
        node = {
            "name": name,
            "qty": 1,
            "children": [],
        }
        for cname, clist in merged.items():
            if clist[0] in children:  # 子件本身是子装配 -> 递归
                sub = make_node(clist[0])
                sub["qty"] = len(clist)
                node["children"].append(sub)
            else:  # 叶子零件
                node["children"].append({"name": cname, "qty": len(clist), "children": []})
        node["children"].sort(key=lambda x: x["name"])
        return node

    return [make_node(r) for r in roots], len(edges), len(prod_name)


def render(node, indent=0):
    line = "  " * indent + ("- " if indent else "") + node["name"]
    if node["qty"] > 1:
        line += f"  ×{node['qty']}"
    print(line)
    for ch in node["children"]:
        render(ch, indent + 1)


# ---------- compare ----------

def flatten_edges(node, parent, acc):
    for ch in node["children"]:
        acc[(parent, ch["name"])] += ch["qty"]
        flatten_edges(ch, ch["name"], acc)


def load_one_root(obj, label):
    if isinstance(obj, list):
        if len(obj) != 1:
            raise SystemExit(f"{label}: 期望单个根节点的 JSON 树, 实际 {len(obj)} 个根")
        obj = obj[0]
    if "name" not in obj or "children" not in obj:
        raise SystemExit(f"{label}: JSON 缺少 name/children 字段, 不符合树格式")
    return obj


def compare(gt_file, pred_file):
    gt = load_one_root(json.load(open(gt_file, encoding="utf-8")), gt_file)
    pred = load_one_root(json.load(open(pred_file, encoding="utf-8")), pred_file)
    gt_edges, pred_edges = Counter(), Counter()
    flatten_edges(gt, gt["name"], gt_edges)
    flatten_edges(pred, pred["name"], pred_edges)

    tp = sum((gt_edges & pred_edges).values())
    gp, pp = sum(gt_edges.values()), sum(pred_edges.values())
    p = tp / pp if pp else 0.0
    r = tp / gp if gp else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0

    print(f"GT 边数(含数量): {gp}   预测边数: {pp}   命中: {tp}")
    print(f"父子边 P={p:.3f}  R={r:.3f}  F1={f1:.3f}")

    missing = gt_edges - pred_edges
    extra = pred_edges - gt_edges
    if missing:
        print(f"\n漏掉的父子关系 {len(missing)} 种:")
        for (a, b), q in sorted(missing.items()):
            print(f"  - {a} -> {b}  ×{q}")
    if extra:
        print(f"\n多出来的父子关系 {len(extra)} 种:")
        for (a, b), q in sorted(extra.items()):
            print(f"  + {a} -> {b}  ×{q}")


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "--compare":
        compare(sys.argv[2], sys.argv[3])
        return
    if len(sys.argv) < 2:
        print(__doc__)
        return
    path = sys.argv[1]
    trees, n_edges, n_products = build_tree(path)
    print(f"文件: {path}   产品数: {n_products}   装配关系(NAUO): {n_edges}   根: {len(trees)}\n")
    for t in trees:
        render(t)
    if len(sys.argv) >= 3:
        json.dump(trees, open(sys.argv[2], "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print(f"\n已保存: {sys.argv[2]}")


if __name__ == "__main__":
    main()
