// Compile the visual query graph (table nodes + join edges) into a SELECT.
//
// Nodes carry which columns to select and an optional per-node WHERE fragment.
// Edges carry the join between two tables (columns from the relationship map).
// The result runs through the same duckdb-wasm path the SQL console uses.

import { findRelationship } from "./relationships";

export interface QueryNode {
  id: string; // React Flow node id
  table: string; // table name
  alias: string; // SQL alias (t0, t1, …) — stable per node
  columns: string[]; // selected columns (empty ⇒ none from this node)
  where?: string; // raw WHERE fragment for this table (optional)
}

export interface QueryEdge {
  source: string; // node id
  target: string; // node id
}

export interface BuildResult {
  sql: string | null;
  errors: string[];
}

// Order the nodes into a JOIN chain: start from a root, then attach any node
// that shares an edge with something already placed. Returns null if the edges
// don't form a connected graph over the selected nodes.
function orderNodes(
  nodes: QueryNode[],
  edges: QueryEdge[]
): { node: QueryNode; joinTo?: QueryNode }[] | null {
  if (nodes.length === 0) return [];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const adj = new Map<string, string[]>();
  for (const n of nodes) adj.set(n.id, []);
  for (const e of edges) {
    if (adj.has(e.source) && adj.has(e.target)) {
      adj.get(e.source)!.push(e.target);
      adj.get(e.target)!.push(e.source);
    }
  }
  const placed = new Set<string>();
  const order: { node: QueryNode; joinTo?: QueryNode }[] = [];
  const root = nodes[0];
  order.push({ node: root });
  placed.add(root.id);
  // BFS attaching neighbors
  const queue = [root.id];
  while (queue.length) {
    const cur = queue.shift()!;
    for (const nb of adj.get(cur) || []) {
      if (!placed.has(nb)) {
        placed.add(nb);
        order.push({ node: byId.get(nb)!, joinTo: byId.get(cur)! });
        queue.push(nb);
      }
    }
  }
  if (placed.size !== nodes.length) return null; // disconnected
  return order;
}

export function buildSql(
  nodes: QueryNode[],
  edges: QueryEdge[],
  limit = 100
): BuildResult {
  const errors: string[] = [];
  if (nodes.length === 0) {
    return { sql: null, errors: ["Add a table to start."] };
  }

  const ordered = orderNodes(nodes, edges);
  if (ordered === null) {
    return {
      sql: null,
      errors: ["Every table must be connected by a join (no islands)."],
    };
  }

  // SELECT list: alias-qualified selected columns. If nothing is ticked
  // anywhere, fall back to the first table's *.
  const selects: string[] = [];
  for (const n of nodes) {
    for (const c of n.columns) selects.push(`${n.alias}.${c}`);
  }
  const selectClause =
    selects.length > 0 ? selects.join(", ") : `${nodes[0].alias}.*`;

  // FROM + JOINs
  const first = ordered[0].node;
  const fromParts = [`FROM ${first.table} AS ${first.alias}`];
  for (let i = 1; i < ordered.length; i++) {
    const { node, joinTo } = ordered[i];
    if (!joinTo) {
      errors.push(`${node.table} is not joined to anything.`);
      continue;
    }
    const on = findRelationship(joinTo.table, node.table);
    if (!on) {
      errors.push(
        `No known join between ${joinTo.table} and ${node.table}.`
      );
      continue;
    }
    const conds = on
      .map(([lc, rc]) => `${joinTo.alias}.${lc} = ${node.alias}.${rc}`)
      .join(" AND ");
    fromParts.push(`JOIN ${node.table} AS ${node.alias} ON ${conds}`);
  }

  // WHERE: AND the per-node fragments (already user-authored SQL fragments).
  const wheres = nodes
    .filter((n) => n.where && n.where.trim())
    .map((n) => `(${n.where!.trim()})`);

  if (errors.length) return { sql: null, errors };

  let sql = `SELECT ${selectClause}\n${fromParts.join("\n")}`;
  if (wheres.length) sql += `\nWHERE ${wheres.join(" AND ")}`;
  sql += `\nLIMIT ${limit};`;
  return { sql, errors: [] };
}
