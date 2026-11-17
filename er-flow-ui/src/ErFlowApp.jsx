import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  NodeResizer,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

function quorumBadge(status, healthy, total) {
  const s = String(status || '').toLowerCase();
  if (s === 'healthy') {
    return { cls: 'status-ok', text: `🟢 ปกติ ${healthy}/${total}` };
  }
  if (s === 'degraded') {
    return { cls: 'status-warning', text: `🟡 Failover ${healthy}/${total}` };
  }
  if (s === 'quorum_lost') {
    return { cls: 'status-critical', text: `🔴 ล่ม ${healthy}/${total}` };
  }
  return { cls: 'status-nodata', text: `⚪ รอข้อมูล (${healthy}/${total})` };
}

function ClusterNode({ data, selected }) {
  const badge = quorumBadge(data.quorumStatus, data.healthyNodes, data.totalNodes);
  const zoneCls =
    data.colorTheme === 'beige'
      ? 'er-zone-beige'
      : data.colorTheme === 'blue'
      ? 'er-zone-blue'
      : 'er-zone-green';

  return (
    <div
      className={`er-flow-cluster-node ${zoneCls} ${selected ? 'selected' : ''}`}
      data-cluster-id={data.clusterId}
    >
      <NodeResizer
        minWidth={260}
        minHeight={160}
        isVisible={selected}
        lineStyle={{ borderColor: '#3b82f6', borderWidth: 1.5 }}
        handleStyle={{ width: 10, height: 10, borderRadius: 2, background: '#3b82f6' }}
      />
      <Handle type="target" position={Position.Top} id="c-top" className="er-flow-handle" />
      <Handle type="source" position={Position.Bottom} id="c-bottom" className="er-flow-handle" />
      <Handle type="target" position={Position.Left} id="c-left" className="er-flow-handle" />
      <Handle type="source" position={Position.Right} id="c-right" className="er-flow-handle" />

      <div className="er-zone-header">
        <strong className="er-zone-title-text">cluster: {data.name}</strong>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className={`status-badge ${badge.cls}`}>{badge.text}</span>
          <button
            type="button"
            className="er-dots-btn nodrag"
            title="แก้ไขคลัสเตอร์"
            onClick={(e) => {
              e.stopPropagation();
              if (window.openErEditModal) {
                window.openErEditModal('cluster', data.clusterId, data);
              }
            }}
          >
            ⋯
          </button>
        </div>
      </div>
      {data.isEmpty && (
        <div className="er-empty-cluster-hint">
          ลากเครื่อง VM มาวางในกรอบนี้ หรือกดปุ่ม <b>⋯</b> เพื่อจัดการ
        </div>
      )}
    </div>
  );
}

function VmNode({ data, selected }) {
  const hdrCls =
    data.role === 'db'
      ? 'er-hdr-purple'
      : data.role === 'web' || data.role === 'lb'
      ? 'er-hdr-red'
      : 'er-hdr-blue';
  const online = Boolean(data.isHealthy);

  return (
    <div
      id={`er-node-${data.agentId}`}
      className={`er-flow-vm-node ${selected ? 'selected' : ''}`}
      data-agent-id={data.agentId}
      data-agent-host={data.hostname}
      data-agent-role={data.role}
      data-cluster-id={data.clusterId || ''}
    >
      <Handle type="target" position={Position.Left} id="vm-in" className="er-flow-handle" />
      <Handle type="source" position={Position.Right} id="vm-out" className="er-flow-handle" />

      <div className={`er-entity-header ${hdrCls}`}>
        <span className="er-vm-title-text">{data.agentId}</span>
        <button
          type="button"
          className="er-hdr-dots nodrag"
          title="แก้ไขเครื่อง VM"
          onClick={(e) => {
            e.stopPropagation();
            if (window.openErEditModal) {
              window.openErEditModal('vm', data.agentId, data);
            }
          }}
        >
          ⋯
        </button>
      </div>
      <div className="er-entity-rows">
        <div className="er-entity-row">
          <span className="er-col-name">🔑 _host</span>
          <span className="er-col-type" title={data.hostname}>
            {data.hostnameShort}
          </span>
        </div>
        <div className="er-entity-row">
          <span className="er-col-name">⚡ status</span>
          <span
            className="er-col-type"
            style={{ color: online ? '#16a34a' : '#dc2626', fontWeight: 700 }}
          >
            {online ? 'ONLINE' : 'OFFLINE'}
          </span>
        </div>
        <div className="er-entity-row">
          <span className="er-col-name">📊 metrics</span>
          <span className="er-col-type">{data.sourceCount} log files</span>
        </div>
        <div className="er-entity-row">
          <span className="er-col-name">
            🔌 {data.role} <b style={{ color: '#d97706' }}>{'{}'}</b>
          </span>
          <span className="er-col-type">link 👁</span>
        </div>
        <div className="er-entity-footer">
          <a
            className="node-link-sm nodrag"
            href={`/website?website_id=${encodeURIComponent(data.websiteId)}&agent_id=${encodeURIComponent(
              data.agentId
            )}`}
          >
            ดู Log →
          </a>
        </div>
      </div>
    </div>
  );
}

const nodeTypes = {
  cluster: ClusterNode,
  vm: VmNode,
};

function findContainingCluster(absPos, allNodes) {
  const cx = absPos.x + 115;
  const cy = absPos.y + 85;
  for (const n of allNodes) {
    if (n.type !== 'cluster') continue;
    const w = n.measured?.width || n.style?.width || 380;
    const h = n.measured?.height || n.style?.height || 220;
    if (cx >= n.position.x && cx <= n.position.x + w && cy >= n.position.y && cy <= n.position.y + h) {
      return n;
    }
  }
  return null;
}

function buildInitialGraph(payload, savedLayout) {
  const websiteId = payload.websiteId || 'website_1';
  const clusters = Array.isArray(payload.clusters) ? payload.clusters : [];
  const agents = Array.isArray(payload.agents) ? payload.agents : [];
  const relations = Array.isArray(payload.relations) ? payload.relations : [];
  const savedNodes = (savedLayout && savedLayout.nodes) || {};

  const nodes = [];
  const nodeById = {};
  agents.forEach((a) => {
    nodeById[a.agentId] = a;
  });

  const clusteredIds = new Set();
  const themes = ['beige', 'blue', 'green'];

  clusters.forEach((c, idx) => {
    const cid = c.clusterId;
    const nodeId = `cluster:${cid}`;
    const members = Array.isArray(c.memberIds) ? c.memberIds : [];
    members.forEach((m) => clusteredIds.add(m));

    const defaultW = Math.max(300, members.length * 265 + 45);
    const defaultH = 250;
    const defaultX = 32;
    const defaultY = 24 + idx * 285;
    const saved = savedNodes[nodeId];

    nodes.push({
      id: nodeId,
      type: 'cluster',
      zIndex: 0,
      position: saved ? { x: saved.x, y: saved.y } : { x: defaultX, y: defaultY },
      style: {
        width: (saved && saved.width) || defaultW,
        height: (saved && saved.height) || defaultH,
      },
      data: {
        clusterId: cid,
        name: c.name || cid,
        quorumStatus: c.quorumStatus || 'nodata',
        healthyNodes: c.healthyNodes ?? 0,
        totalNodes: c.totalNodes ?? members.length,
        memberIds: members,
        colorTheme: themes[idx % themes.length],
        isEmpty: members.length === 0,
      },
    });

    members.forEach((mid, mIdx) => {
      const info = nodeById[mid] || {
        agentId: mid,
        role: 'db',
        hostname: mid,
        isHealthy: true,
        sourceCount: 0,
      };
      const vmNodeId = `vm:${mid}`;
      const vmSaved = savedNodes[vmNodeId];
      const relX = vmSaved ? vmSaved.x : 22 + mIdx * 255;
      const relY = vmSaved ? vmSaved.y : 52;
      const hostStr = String(info.hostname || mid);

      nodes.push({
        id: vmNodeId,
        type: 'vm',
        zIndex: 10,
        parentId: nodeId,
        extent: 'parent',
        position: { x: relX, y: relY },
        data: {
          websiteId,
          agentId: mid,
          role: info.role || 'app',
          hostname: hostStr,
          hostnameShort: hostStr.length > 20 ? hostStr.slice(0, 18) + '..' : hostStr,
          isHealthy: Boolean(info.isHealthy),
          sourceCount: info.sourceCount || 0,
          clusterId: cid,
        },
      });
    });
  });

  const unclustered = agents.filter((a) => !clusteredIds.has(a.agentId));
  unclustered.forEach((info, uIdx) => {
    const mid = info.agentId;
    const vmNodeId = `vm:${mid}`;
    const vmSaved = savedNodes[vmNodeId];
    const hostStr = String(info.hostname || mid);
    const defaultX = 36 + (uIdx % 4) * 260;
    const defaultY = 28 + clusters.length * 285 + Math.floor(uIdx / 4) * 215;

    nodes.push({
      id: vmNodeId,
      type: 'vm',
      zIndex: 10,
      position: vmSaved ? { x: vmSaved.x, y: vmSaved.y } : { x: defaultX, y: defaultY },
      data: {
        websiteId,
        agentId: mid,
        role: info.role || 'app',
        hostname: hostStr,
        hostnameShort: hostStr.length > 20 ? hostStr.slice(0, 18) + '..' : hostStr,
        isHealthy: Boolean(info.isHealthy),
        sourceCount: info.sourceCount || 0,
        clusterId: '',
      },
    });
  });

  const resolveFlowNodeId = (rawId) => {
    if (!rawId) return null;
    if (String(rawId).startsWith('cluster:')) return rawId;
    const byVm = nodes.find((n) => n.id === `vm:${rawId}`);
    if (byVm) return byVm.id;
    const byCluster = nodes.find((n) => n.id === `cluster:${rawId}`);
    if (byCluster) return byCluster.id;
    return null;
  };

  const edges = [];
  relations.forEach((rel, idx) => {
    const src = resolveFlowNodeId(rel.source_id);
    const dst = resolveFlowNodeId(rel.target_id);
    if (!src || !dst || src === dst) return;
    const isPeer = String(rel.relation_type || '').toUpperCase() === 'PEER_SYNC';
    edges.push({
      id: rel.relation_id || `edge_${idx}_${src}_${dst}`,
      source: src,
      target: dst,
      type: 'smoothstep',
      animated: isPeer,
      label: isPeer ? '⇄ sync' : rel.port ? `:${rel.port}` : 'route',
      style: {
        stroke: isPeer ? '#7c3aed' : '#334155',
        strokeWidth: 2.2,
        strokeDasharray: isPeer ? '5,4' : undefined,
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: isPeer ? '#7c3aed' : '#334155',
      },
      data: { relationId: rel.relation_id || '' },
    });
  });

  return { nodes, edges };
}

function autoArrangeCurrentNodes(currentNodes) {
  const clusters = currentNodes.filter((n) => n.type === 'cluster');
  const vms = currentNodes.filter((n) => n.type === 'vm');
  const next = [];

  let curY = 24;
  clusters.forEach((c) => {
    const members = vms.filter((v) => v.parentId === c.id);
    const cW = Math.max(320, members.length * 265 + 45);
    const cH = 250;
    next.push({
      ...c,
      position: { x: 32, y: curY },
      style: { ...c.style, width: cW, height: cH },
      data: { ...c.data, isEmpty: members.length === 0 },
    });
    members.forEach((m, mIdx) => {
      next.push({
        ...m,
        position: { x: 22 + mIdx * 255, y: 52 },
      });
    });
    curY += cH + 36;
  });

  const standaloneVms = vms.filter((v) => !v.parentId);
  standaloneVms.forEach((v, idx) => {
    next.push({
      ...v,
      position: {
        x: 36 + (idx % 4) * 260,
        y: curY + Math.floor(idx / 4) * 215,
      },
    });
  });
  return next;
}

function ErFlowInner({ payload }) {
  const websiteId = payload.websiteId || 'website_1';
  const storageKey = `alm_xyflow_${websiteId}`;
  const wrapperRef = useRef(null);
  const { screenToFlowPosition, fitView, getViewport } = useReactFlow();

  const savedLayout = useMemo(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }, [storageKey]);

  const initial = useMemo(() => buildInitialGraph(payload, savedLayout), [payload, savedLayout]);
  const [nodes, setNodes, onNodesChange] = useNodesState(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges);
  const [selectedEdgeId, setSelectedEdgeId] = useState('');

  const persistLayout = useCallback(
    (nextNodes, explicitViewport) => {
      try {
        const map = {};
        nextNodes.forEach((n) => {
          map[n.id] = {
            x: Math.round(n.position.x),
            y: Math.round(n.position.y),
            width: n.measured?.width || n.style?.width || undefined,
            height: n.measured?.height || n.style?.height || undefined,
          };
        });
        const vp = explicitViewport || getViewport();
        localStorage.setItem(storageKey, JSON.stringify({ nodes: map, viewport: vp }));
      } catch {}
    },
    [storageKey, getViewport]
  );

  useEffect(() => {
    const t = setTimeout(() => persistLayout(nodes), 150);
    return () => clearTimeout(t);
  }, [nodes, persistLayout]);

  const onNodeDragStop = useCallback(
    async (_, draggedNode) => {
      if (draggedNode.type !== 'vm') {
        persistLayout(nodes);
        return;
      }

      let absPos = { ...draggedNode.position };
      if (draggedNode.parentId) {
        const oldParent = nodes.find((n) => n.id === draggedNode.parentId);
        if (oldParent) {
          absPos = {
            x: oldParent.position.x + draggedNode.position.x,
            y: oldParent.position.y + draggedNode.position.y,
          };
        }
      }

      const targetCluster = findContainingCluster(absPos, nodes);
      const newParentId = targetCluster ? targetCluster.id : undefined;

      if (newParentId && newParentId !== draggedNode.parentId) {
        const cid = targetCluster.data.clusterId;
        const relPos = {
          x: Math.max(12, absPos.x - targetCluster.position.x),
          y: Math.max(48, absPos.y - targetCluster.position.y),
        };
        setNodes((nds) =>
          nds.map((n) => {
            if (n.id === draggedNode.id) {
              return {
                ...n,
                parentId: newParentId,
                extent: 'parent',
                position: relPos,
                data: { ...n.data, clusterId: cid },
              };
            }
            if (n.id === newParentId) {
              return { ...n, data: { ...n.data, isEmpty: false } };
            }
            return n;
          })
        );
        await fetch('/api/agents/assign', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            agent_id: draggedNode.data.agentId,
            website_id: websiteId,
            agent_role: draggedNode.data.role || 'app',
            hostname: draggedNode.data.hostname || draggedNode.data.agentId,
            cluster_id: cid,
            upsert_if_missing: true,
          }),
        });
      }
      persistLayout(nodes);
    },
    [nodes, websiteId, setNodes, persistLayout]
  );

  const onConnect = useCallback(
    async (params) => {
      if (!params.source || !params.target || params.source === params.target) return;
      const rawSrc = params.source.replace(/^(vm:|cluster:)/, '');
      const rawDst = params.target.replace(/^(vm:|cluster:)/, '');
      const relType = rawSrc.startsWith('db') && rawDst.startsWith('db') ? 'PEER_SYNC' : 'ROUTE_TO';

      const res = await fetch('/api/relations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          website_id: websiteId,
          source_id: rawSrc,
          target_id: rawDst,
          relation_type: relType,
        }),
      });
      const created = await res.json().catch(() => ({}));
      const relId = created.relation_id || `rel_${Date.now()}`;
      const isPeer = relType === 'PEER_SYNC';

      setEdges((eds) => [
        ...eds,
        {
          id: relId,
          source: params.source,
          target: params.target,
          sourceHandle: params.sourceHandle,
          targetHandle: params.targetHandle,
          type: 'smoothstep',
          animated: isPeer,
          label: isPeer ? '⇄ sync' : 'route',
          style: {
            stroke: isPeer ? '#7c3aed' : '#334155',
            strokeWidth: 2.2,
            strokeDasharray: isPeer ? '5,4' : undefined,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: isPeer ? '#7c3aed' : '#334155',
          },
          data: { relationId: relId },
        },
      ]);
    },
    [websiteId, setEdges]
  );

  const onNodesDelete = useCallback(async (deleted) => {
    for (const node of deleted) {
      if (node.type === 'cluster' && node.data?.clusterId) {
        await fetch('/api/clusters/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cluster_id: node.data.clusterId }),
        });
      } else if (node.type === 'vm' && node.data?.agentId) {
        await fetch('/api/agents/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ agent_id: node.data.agentId }),
        });
      }
    }
  }, []);

  const onEdgesDelete = useCallback(async (deleted) => {
    for (const edge of deleted) {
      const relId = edge.data?.relationId || edge.id;
      if (relId && !String(relId).startsWith('edge_')) {
        await fetch(`/api/relations/${encodeURIComponent(relId)}`, { method: 'DELETE' });
      }
    }
    setSelectedEdgeId('');
  }, []);

  const deleteSelectedEdge = useCallback(async () => {
    if (!selectedEdgeId) return;
    const target = edges.find((e) => e.id === selectedEdgeId);
    if (target) {
      await onEdgesDelete([target]);
      setEdges((eds) => eds.filter((e) => e.id !== selectedEdgeId));
    }
    setSelectedEdgeId('');
  }, [selectedEdgeId, edges, onEdgesDelete, setEdges]);

  const onDrop = useCallback(
    async (e) => {
      e.preventDefault();
      const pType = e.dataTransfer.getData('palette_type');
      if (!pType) return;
      const position = screenToFlowPosition({ x: e.clientX, y: e.clientY });

      if (pType === 'cluster') {
        const count = nodes.filter((n) => n.type === 'cluster').length + 1;
        const defaultName = `Cluster ใหม่ #${count}`;
        const res = await fetch('/api/clusters', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            website_id: websiteId,
            name: defaultName,
            cluster_type: 'ha_cluster',
            quorum_min: 2,
          }),
        });
        const created = await res.json().catch(() => ({}));
        const cid = created.cluster_id || `cluster_new_${Date.now()}`;
        setNodes((nds) => [
          ...nds,
          {
            id: `cluster:${cid}`,
            type: 'cluster',
            zIndex: 0,
            position,
            style: { width: 380, height: 220 },
            data: {
              clusterId: cid,
              name: defaultName,
              quorumStatus: 'nodata',
              healthyNodes: 0,
              totalNodes: 0,
              memberIds: [],
              colorTheme: 'green',
              isEmpty: true,
            },
          },
        ]);
      } else {
        let idx = nodes.filter((n) => n.type === 'vm').length + 1;
        while (nodes.some((n) => n.id === `vm:vm_${idx}`)) {
          idx += 1;
        }
        const vmName = `vm_${idx}`;
        const targetCluster = findContainingCluster(
          { x: position.x - 115, y: position.y - 85 },
          nodes
        );
        const clusterId = targetCluster ? targetCluster.data.clusterId : '';
        const finalPos = targetCluster
          ? {
              x: Math.max(12, position.x - targetCluster.position.x - 110),
              y: Math.max(48, position.y - targetCluster.position.y - 60),
            }
          : position;

        await fetch('/api/agents/assign', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            agent_id: vmName,
            website_id: websiteId,
            agent_role: 'app',
            hostname: `${vmName}.local`,
            cluster_id: clusterId,
            upsert_if_missing: true,
          }),
        });

        setNodes((nds) => {
          const updated = targetCluster
            ? nds.map((n) =>
                n.id === targetCluster.id ? { ...n, data: { ...n.data, isEmpty: false } } : n
              )
            : nds;
          return [
            ...updated,
            {
              id: `vm:${vmName}`,
              type: 'vm',
              zIndex: 10,
              parentId: targetCluster ? targetCluster.id : undefined,
              extent: targetCluster ? 'parent' : undefined,
              position: finalPos,
              data: {
                websiteId,
                agentId: vmName,
                role: 'app',
                hostname: `${vmName}.local`,
                hostnameShort: `${vmName}.local`,
                isHealthy: true,
                sourceCount: 0,
                clusterId,
              },
            },
          ];
        });
      }
    },
    [nodes, screenToFlowPosition, setNodes, websiteId]
  );

  useEffect(() => {
    window.erFlowActions = {
      resetLayout: () => {
        setNodes((cur) => autoArrangeCurrentNodes(cur));
        setTimeout(() => fitView({ padding: 0.15 }), 60);
      },
      removeNode: (nodeId) => {
        setNodes((nds) => nds.filter((n) => n.id !== nodeId && n.parentId !== nodeId));
        setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
      },
      fitView: () => fitView({ padding: 0.15 }),
    };
  }, [setNodes, setEdges, fitView]);

  return (
    <div
      ref={wrapperRef}
      style={{ width: '100%', height: '100%', position: 'relative' }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
    >
      {selectedEdgeId && (
        <button
          type="button"
          className="close-btn-sm"
          onClick={deleteSelectedEdge}
          style={{
            position: 'absolute',
            top: 12,
            right: 12,
            zIndex: 20,
            fontSize: 13.5,
            padding: '6px 12px',
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
          }}
        >
          🗑️ ลบเส้นที่เลือก
        </button>
      )}
      <ReactFlow
        nodes={nodes}
        edges={edges.map((e) =>
          e.id === selectedEdgeId
            ? { ...e, style: { ...e.style, stroke: '#dc2626', strokeWidth: 3.4 } }
            : e
        )}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodesDelete={onNodesDelete}
        onNodeDragStop={onNodeDragStop}
        onMoveEnd={(_, vp) => persistLayout(nodes, vp)}
        onConnect={onConnect}
        onEdgesDelete={onEdgesDelete}
        onEdgeClick={(_, edge) => setSelectedEdgeId((prev) => (prev === edge.id ? '' : edge.id))}
        onPaneClick={() => setSelectedEdgeId('')}
        defaultViewport={savedLayout?.viewport}
        fitView={!savedLayout?.viewport}
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.25}
        maxZoom={1.8}
        deleteKeyCode={['Backspace', 'Delete']}
      >
        <Background gap={18} size={1.2} />
        <Controls showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          nodeStrokeWidth={2}
          style={{ width: 150, height: 100, borderRadius: 6 }}
        />
      </ReactFlow>
    </div>
  );
}

export function mountErFlow() {
  const rootEl = document.getElementById('er-xyflow-root');
  if (!rootEl) return;
  const raw = rootEl.getAttribute('data-er-payload') || '{}';
  let payload = {};
  try {
    payload = JSON.parse(raw);
  } catch {
    payload = {};
  }
  const { createRoot } = require('react-dom/client');
  const root = createRoot(rootEl);
  root.render(
    <ReactFlowProvider>
      <ErFlowInner payload={payload} />
    </ReactFlowProvider>
  );
}
