#!/usr/bin/env python3
"""Generate Malloy sources for the BasicOps "244" tables.

IMPORTANT: 244 is NOT a workspace. It is the template/schema id shared by the data tables of ALL
workspaces. Every row carries CompanyId, which is the real workspace id; B_Company_244 holds one
row per workspace (its CompanyId is the workspace id, Name the workspace name).

BasicOps defines its data tables as metadata:
  * B_Table (CompanyId = 244) lists the tables. The physical table is
    B_<TableName>_244 when TableName is set, else B_Table_244_<Id>.
  * B_TableColumn lists the columns. The physical column is <ColumnName> when
    set, else c<Id>. Name is the readable label.

This script reads that metadata with the mysql CLI and writes
datasets/workspace/tables.malloy. Re-run it when the BasicOps schema changes:

    set -a; . ~/.config/malloyyo/rds.env; set +a
    export RDS_PASSWORD="$(cat ~/.config/malloyyo/rds_password)"
    python3 tools/generate_workspace.py

Rules:
  * Trashed rows (Trash is not null) are excluded in every source.
  * Text columns are hidden: only <name>_length is exposed, except for the
    tables in SHOW_TEXT (users, companies). Password columns are never exposed.
  * Single-reference columns (Type 6) become <name>_id plus a join_one.
  * Type 9 (one-to-many) and Type 8 (many-to-many) columns have a link table named
    <table>_<column id> with FromId (this row) and ToId (the referenced row). Each
    becomes a bridge source (<table>_<column>) joined to both sides. When every
    ToId appears once (a true one-to-many), the child also gets a join to its parent.
"""
import json
import os
import re
import subprocess
import sys

WORKSPACE = 244  # the template schema id used in table names, not a workspace
OUT = os.path.join(os.path.dirname(__file__), "..", "datasets", "workspace", "tables.malloy")

# B_Table.Id -> Malloy source name
TABLES = {
    3922: "users",
    3923: "clients",
    3924: "workspaces",
    3926: "comments",
    3927: "notes",
    3933: "sections",
    3934: "projects",
    3935: "roles",
    3936: "tasks",
    3937: "task_statuses",
    4301: "task_dependencies",
    4346: "teams",
    4428: "time_entries",
}
SINGULAR = {
    "users": "user", "clients": "client", "workspaces": "workspace", "comments": "comment", "notes": "note",
    "sections": "section", "projects": "project", "roles": "role", "tasks": "task",
    "task_statuses": "task_status", "task_dependencies": "task_dependency", "teams": "team",
    "time_entries": "time_entry",
}
DESC = "Rows from the BasicOps 244 table family, covering all workspaces."
AGENT = ("244 is NOT a workspace: it is the template schema shared by every workspace's data. Each row belongs to a "
         "workspace through workspace_id (CompanyId); join workspace for its name. Filter or group by workspace_id to analyse one workspace.")
SHOW_TEXT = {3922, 3924}  # users and companies show real text
PASSWORD_TYPE = 7

RESERVED = set("""
private public internal number string boolean date timestamp json default final include exclude test

accept aggregate all and as asc avg by calculate case cast count day declare desc dimension else end except
exclude extend false from group_by having hour import index is join_cross join_many join_one limit max measure
min minute month nest not now null on or order_by pick primary_key project query quarter rename run
second select source sum then timezone top true view week when where year
""".split())

NUMERIC = {"int", "bigint", "smallint", "tinyint", "mediumint", "double", "float", "decimal"}
TEXT = {"varchar", "char", "text", "tinytext", "mediumtext", "longtext"}
TIMES = {"datetime", "timestamp"}


def mysql(sql):
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    res = subprocess.run(["malloyyo", "sql", "rds", "-C", root, "-j", "-e", sql], capture_output=True, text=True)
    if res.returncode:
        sys.exit(res.stderr or res.stdout)
    start = min(i for i in (res.stdout.find("["), res.stdout.find("{")) if i >= 0)
    rows = json.loads(res.stdout[start:])
    # each row is a dict; keep column order, turn values into strings ("NULL" for null)
    return [["NULL" if v is None else str(v) for v in r.values()] for r in rows]


def slug(label, taken):
    s = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "col"
    if s[0].isdigit():
        s = "f_" + s
    if s in RESERVED:
        s += "_"
    base, i = s, 2
    while s in taken:
        s = f"{base}_{i}"
        i += 1
    taken.add(s)
    return s


def esc(label):
    return label.replace('"', "'").replace("\n", " ")


def main():
    ids = ",".join(str(i) for i in TABLES)
    meta = {int(r[0]): (None if r[1] == "NULL" else r[1])
            for r in mysql(f"select Id, TableName from B_Table where CompanyId={WORKSPACE} and Trash is null and Id in ({ids})")}
    missing = set(TABLES) - set(meta)
    if missing:
        sys.exit(f"not found in B_Table for company {WORKSPACE}: {sorted(missing)}")
    phys_name = {tid: (f"B_{tn}_{WORKSPACE}" if tn else f"B_Table_{WORKSPACE}_{tid}") for tid, tn in meta.items()}
    names = ",".join(f"'{n}'" for n in phys_name.values())
    phys = {}
    for t, c, dt in mysql(f"select table_name, column_name, data_type from information_schema.columns "
                          f"where table_schema='BasicOps' and table_name in ({names})"):
        phys.setdefault(t, {})[c] = dt
    cols = mysql(f"select TableId, Id, Name, Type, ColumnName, ReferenceId from B_TableColumn "
                 f"where TableId in ({ids}) and Trash is null order by TableId, Position, Id")

    # link tables for Type 9 / Type 8 columns
    colinfo = {(int(c[0]), int(c[1])): c for c in cols}
    cand = {k: f"{phys_name[k[0]]}_{k[1]}" for k, c in colinfo.items()
            if int(c[3]) in (8, 9) and c[5] != "NULL" and int(c[5]) in TABLES}
    existing = set()
    if cand:
        lt = ",".join(f"'{n}'" for n in cand.values())
        existing = {r[0] for r in mysql(f"select table_name from information_schema.tables where table_schema='BasicOps' and table_name in ({lt})")}
    link_taken = set()
    links = []  # dicts: name, table, parent, child, one_to_many
    for (ptid, cid), tn in cand.items():
        if tn not in existing:
            print(f"no link table {tn}", file=sys.stderr)
            continue
        c = colinfo[(ptid, cid)]
        one = False
        if int(c[3]) == 9:
            n, d = mysql(f"select count(*), count(distinct ToId) from {tn}")[0]
            one = n == d
        links.append(dict(name=slug(f"{TABLES[ptid]} {c[2]}", link_taken), table=tn, parent=TABLES[ptid],
                          child=TABLES[int(c[5])], label=c[2], one=one))
    child_joins = {}  # child source -> list of link dicts that give it a parent join
    for lk in links:
        if lk["one"]:
            child_joins.setdefault(lk["child"], []).append(lk)

    out = ["// GENERATED by tools/generate_workspace.py from B_Table / B_TableColumn. Do not edit by hand.",
           f"// 244 is the template schema, not a workspace: each row's workspace is its CompanyId (workspace_id). Trashed rows excluded. Text hidden (length only) except users and companies.", ""]
    enriched = []
    takens = {}
    for tid, src in TABLES.items():
        table = phys_name[tid]
        have = phys.get(table)
        if not have:
            print(f"skip {src}: physical table {table} not found", file=sys.stderr)
            continue
        taken = {"id", "created", "updated", "user_id", "workspace_id", "workspace", "row_count"} | set(have)
        dims, joins = [], []
        dims.append("    id is `Id`")
        if "Created" in have:
            dims.append("    created is `Created`")
        if "Updated" in have:
            dims.append("    updated is `Updated`")
        if "UserId" in have:
            dims.append("    user_id is `UserId`")
        if "CompanyId" in have:
            dims += ['    #" The workspace this row belongs to (CompanyId). 244 in the table name is only the template.',
                     "    workspace_id is `CompanyId`"]
        for ttid, cid, label, ctype, cname, ref in (c for c in cols if int(c[0]) == tid):
            pcol = cname if cname != "NULL" else f"c{cid}"
            dt = have.get(pcol)
            col = f"`{pcol}`"
            if dt is None or int(ctype) == PASSWORD_TYPE:
                continue
            name = slug(label, taken)
            note = f'    #" {esc(label)}'
            if dt in TEXT:
                if tid in SHOW_TEXT:
                    dims += [note, f"    {name} is {col}"]
                else:
                    dims += [f'    #" Length of "{esc(label)}" (text hidden)', f"    {name}_length is length({col}::string)"]
            elif dt in NUMERIC and int(ctype) == 6 and ref != "NULL" and int(ref) in TABLES:
                idname = slug(label + " id", taken)
                dims += [note, f"    {idname} is {col}"]
                joins.append((name, TABLES[int(ref)], idname))
            elif dt in NUMERIC:
                dims += [note, f"    {name} is {col}"]
            elif dt in TIMES:
                dims += [note, f"    {name} is {col}"]
            elif dt == "date":
                dims += [note, f"    {name} is {col}"]
            elif dt == "bit":
                dims += [note, f"    {name} is coalesce({col}::number, 0) = 1"]
        trash = "where: `Trash` is null\n  " if "Trash" in have else ""
        out += [f'#" {DESC} Table "{esc(src)}" ({table}). Trashed rows excluded.',
                f'#(agent) {AGENT}',
                f'source: raw_{src} is rds.table("{table}") extend {{',
                "  primary_key: id",
                f"  {trash}".rstrip(),
                "  dimension:", *["  " + d for d in dims],
                "  measure:",
                f"    row_count is count()",
                "}", ""]
        enriched.append((src, joins))
        takens[src] = taken

    # bridge (link table) sources
    out.append("// Link tables for one-to-many (Type 9) and many-to-many (Type 8) columns.")
    for lk in links:
        kind = "one-to-many" if lk["one"] else "many-to-many or non-unique"
        out += [f'#" {kind} link: {lk["parent"]} "{esc(lk["label"])}" -> {lk["child"]} ({lk["table"]}). from_id is the {lk["parent"]} row, to_id the {lk["child"]} row.',
                f'source: raw_{lk["name"]} is rds.table("{lk["table"]}") extend {{',
                "  dimension:", "    from_id is `FromId`", "    to_id is `ToId`", "    created is `Created`",
                "  measure:", "    row_count is count()", "}"]
        same = lk["parent"] == lk["child"]
        pn = "parent" if same else SINGULAR[lk["parent"]]
        cn = "child" if same else SINGULAR[lk["child"]]
        out += [f'source: {lk["name"]} is raw_{lk["name"]} extend {{',
                f'  join_one: {pn} is raw_{lk["parent"]} on from_id = {pn}.id',
                f'  join_one: {cn} is raw_{lk["child"]} on to_id = {cn}.id', "}", ""]

    out.append("// Row sources. Joins go to enriched sources only where the target has no joins of its own (no cycles).")
    t6 = {src: joins for src, joins in enriched}
    ordered = sorted(enriched, key=lambda e: bool(e[1]))
    for src, joins in ordered:
        lines = []
        used = {j[0] for j in joins}
        for name, target, key in joins:
            tgt = target if (not t6.get(target) and target != src) else f"raw_{target}"
            lines.append(f"  join_one: {name} is {tgt} on {key} = {name}.id")
        for lk in child_joins.get(src, []):
            same = lk["parent"] == src
            base = "parent" if same else SINGULAR[lk["parent"]]
            nm, k = base, 2
            while nm in used or nm in takens[src]:
                nm = f"{base}_{k}"
                k += 1
            used.add(nm)
            lines.append(f'  join_one: {nm}_link is raw_{lk["name"]} on id = {nm}_link.to_id')
            lines.append(f'  join_one: {nm} is raw_{lk["parent"]} on {nm}_link.from_id = {nm}.id')
        if src != "workspaces" and "CompanyId" in phys.get(phys_name[next(t for t, n in TABLES.items() if n == src)], {}):
            lines.insert(0, "  join_one: workspace is raw_workspaces on workspace_id = workspace.workspace_id")
        desc = (f'#" {DESC}\n#(agent) {AGENT}' if src != "workspaces" else
                '#" One row per workspace (B_Company_244), with its name and settings.\n'
                '#(agent) workspace_id is the id of the workspace; every other table carries it as workspace_id (CompanyId). 244 is only the template schema, not a workspace.')
        if lines:
            out += [desc, f"source: {src} is raw_{src} extend {{", *lines, "}", ""]
        else:
            out += [desc, f"source: {src} is raw_{src}", ""]
    out = [l for l in out if l is not None]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write("\n".join(out) + "\n")
    print(f"wrote {os.path.normpath(OUT)}: {len(enriched)} sources")


if __name__ == "__main__":
    main()
