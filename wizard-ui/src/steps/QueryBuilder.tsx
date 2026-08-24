import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  Handle,
  Position,
  addEdge,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type Connection,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { SchemaTable } from "../duckdb";
import { findRelationship, joinableTables } from "./relationships";
import { buildSql, QueryNode, QueryEdge } from "./buildSql";

// Data carried on each React Flow node.
interface TableNodeData {
  table: string;
  alias: string;
  columns: { name: string; type: string }[];
  selected: Set<string>;
  where: string;
  onToggle: (col: string) => void;
  onWhere: (v: string) => void;
  [key: string]: unknown;
}

// A table node: title + column checkboxes + a WHERE box. Handles on both sides
// so joins can be drawn either direction.
function TableNode({ data }: NodeProps<Node<TableNodeData>>) {
  return (
    <div className="qb-node">
      <Handle type="target" position={Position.Left} />
      <div className="qb-node-title">
        {data.table} <span className="qb-alias">{data.alias}</span>
      </div>
      <div className="qb-node-cols">
        {data.columns.map((c) => (
          <label key={c.name} className="qb-col">
            <input
              type="checkbox"
              checked={data.selected.has(c.name)}
              onChange={() => data.onToggle(c.name)}
            />
            <span className="qb-col-name">{c.name}</span>
            <span className="qb-col-type">{c.type}</span>
          </label>
        ))}
      </div>
      <input
        className="qb-where"
        placeholder="WHERE … (optional)"
        value={data.where}
        onChange={(e) => data.onWhere(e.target.value)}
      />
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { table: TableNode };

interface Props {
  schema: SchemaTable[];
  onRun: (sql: string) => void;
  running: boolean;
  // A set of tables to preload onto the canvas (auto-connected by their joins),
  // e.g. when a report-gallery card is "opened in builder". Changing the token
  // re-seeds; the tables are the join skeleton, an editable starting point (the
  // builder can't express the aggregation/window a report query may use).
  seed?: { tables: string[]; token: number };
}

function BuilderInner({ schema, onRun, running, seed }: Props) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<TableNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [aliasSeq, setAliasSeq] = useState(0);
  // per-node UI state (selected columns + where), keyed by node id
  const [colState, setColState] = useState<Record<string, Set<string>>>({});
  const [whereState, setWhereState] = useState<Record<string, string>>({});

  const schemaByName = useMemo(
    () => new Map(schema.map((t) => [t.name, t])),
    [schema]
  );

  const toggleCol = useCallback((nodeId: string, col: string) => {
    setColState((prev) => {
      const set = new Set(prev[nodeId] ?? []);
      if (set.has(col)) set.delete(col);
      else set.add(col);
      return { ...prev, [nodeId]: set };
    });
  }, []);

  const setWhere = useCallback((nodeId: string, v: string) => {
    setWhereState((prev) => ({ ...prev, [nodeId]: v }));
  }, []);

  // Add a table node to the canvas.
  const addTable = useCallback(
    (table: string) => {
      const t = schemaByName.get(table);
      if (!t) return;
      const id = `${table}-${aliasSeq}`;
      const alias = `t${aliasSeq}`;
      setAliasSeq((n) => n + 1);
      setColState((prev) => ({ ...prev, [id]: new Set<string>() }));
      setWhereState((prev) => ({ ...prev, [id]: "" }));
      const newNode: Node<TableNodeData> = {
        id,
        type: "table",
        position: { x: 40 + nodes.length * 40, y: 40 + nodes.length * 30 },
        data: {
          table,
          alias,
          columns: t.columns,
          selected: new Set<string>(),
          where: "",
          onToggle: (col: string) => toggleCol(id, col),
          onWhere: (v: string) => setWhere(id, v),
        },
      };
      setNodes((nds) => nds.concat(newNode));
    },
    [schemaByName, aliasSeq, nodes.length, setNodes, toggleCol, setWhere]
  );

  // Only allow an edge if the two tables have a known relationship.
  const onConnect = useCallback(
    (conn: Connection) => {
      const src = nodes.find((n) => n.id === conn.source);
      const tgt = nodes.find((n) => n.id === conn.target);
      if (!src || !tgt) return;
      const rel = findRelationship(src.data.table, tgt.data.table);
      if (!rel) return; // silently reject invalid joins
      setEdges((eds) =>
        addEdge({ ...conn, label: rel.map(([a]) => a).join(", ") }, eds)
      );
    },
    [nodes, setEdges]
  );

  // Seed the canvas from a report-gallery card: replace the graph with the given
  // tables laid out in a row and auto-connected wherever a curated join exists.
  const lastSeed = useRef(-1);
  useEffect(() => {
    if (!seed || seed.token === lastSeed.current) return;
    lastSeed.current = seed.token;

    const seededNodes: Node<TableNodeData>[] = [];
    const idByTable: Record<string, string> = {};
    seed.tables.forEach((table, i) => {
      const t = schemaByName.get(table);
      if (!t) return;
      const id = `${table}-seed${seed.token}-${i}`;
      const alias = `t${i}`;
      idByTable[table] = id;
      seededNodes.push({
        id,
        type: "table",
        position: { x: 30 + i * 250, y: 40 },
        data: {
          table,
          alias,
          columns: t.columns,
          selected: new Set<string>(),
          where: "",
          onToggle: (col: string) => toggleCol(id, col),
          onWhere: (v: string) => setWhere(id, v),
        },
      });
    });

    const seededEdges: Edge[] = [];
    for (let i = 1; i < seed.tables.length; i++) {
      const prev = seed.tables[i - 1];
      const cur = seed.tables[i];
      const rel = findRelationship(prev, cur);
      if (rel && idByTable[prev] && idByTable[cur]) {
        seededEdges.push({
          id: `e-${idByTable[prev]}-${idByTable[cur]}`,
          source: idByTable[prev],
          target: idByTable[cur],
          label: rel.map(([a]) => a).join(", "),
        });
      }
    }

    setColState(Object.fromEntries(seededNodes.map((n) => [n.id, new Set<string>()])));
    setWhereState(Object.fromEntries(seededNodes.map((n) => [n.id, ""])));
    setAliasSeq(seed.tables.length);
    setNodes(seededNodes);
    setEdges(seededEdges);
  }, [seed, schemaByName, setNodes, setEdges, toggleCol, setWhere]);

  // Fold the live UI state (selected cols, where) into the nodes for the build.
  const queryNodes: QueryNode[] = nodes.map((n) => ({
    id: n.id,
    table: n.data.table,
    alias: n.data.alias,
    columns: [...(colState[n.id] ?? [])],
    where: whereState[n.id] ?? "",
  }));
  const queryEdges: QueryEdge[] = edges.map((e) => ({
    source: e.source,
    target: e.target,
  }));
  const built = buildSql(queryNodes, queryEdges);

  // Reflect selected-column state back onto the rendered nodes (checkbox state).
  const displayNodes = nodes.map((n) => ({
    ...n,
    data: {
      ...n.data,
      selected: colState[n.id] ?? new Set<string>(),
      where: whereState[n.id] ?? "",
    },
  }));

  return (
    <div className="qb">
      <div className="qb-palette">
        <div className="qb-palette-head">Add table</div>
        {schema.map((t) => (
          <button
            key={t.name}
            className="chip-btn"
            onClick={() => addTable(t.name)}
            title={`joins: ${joinableTables(t.name).join(", ") || "—"}`}
          >
            + {t.name}
          </button>
        ))}
      </div>

      <div className="qb-canvas">
        <ReactFlow
          nodes={displayNodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodeTypes={nodeTypes}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls />
        </ReactFlow>
      </div>

      <div className="qb-sql">
        {built.errors.length > 0 ? (
          <div className="qb-hint">{built.errors.join(" ")}</div>
        ) : (
          <pre className="qb-sql-pre">{built.sql}</pre>
        )}
        <button
          className="primary"
          disabled={!built.sql || running}
          onClick={() => built.sql && onRun(built.sql)}
        >
          {running ? "Running…" : "Run this query"}
        </button>
      </div>
    </div>
  );
}

export function QueryBuilder(props: Props) {
  return (
    <ReactFlowProvider>
      <BuilderInner {...props} />
    </ReactFlowProvider>
  );
}
