import { useEffect, useRef, useState, useCallback } from 'react';
import * as d3 from 'd3';
import type { PaymentEvent, AgentSnapshot } from './AlgorandStream';
import { fetchState } from './AlgorandStream';

interface Props {
  events: PaymentEvent[];
  onNodeClick?: (addr: string) => void;
  onEdgeClick?: (event: PaymentEvent) => void;
  historicalRound?: number | null;
}

interface GraphNode extends d3.SimulationNodeDatum {
  id: string;
  tier: number;
  score: number;
  payments: number;
  blocked: number;
  policyStatus: string;
}

interface GraphLink extends d3.SimulationLinkDatum<GraphNode> {
  event: PaymentEvent;
  id: string;
}

const TIER_COLORS: Record<number, string> = {
  4: '#00BFFF', // Excellent
  3: '#00FF7F', // Good
  2: '#FFD700', // Caution
  1: '#FF4500', // Restricted
  0: '#FF0000', // Blacklisted
  [-1]: '#888888', // Expired
};

const TIER_LABELS: Record<number, string> = {
  4: 'EXCELLENT', 3: 'GOOD', 2: 'CAUTION',
  1: 'RESTRICTED', 0: 'BLACKLISTED', [-1]: 'EXPIRED',
};

function getTierForScore(score: number): number {
  if (score >= 800) return 4;
  if (score >= 600) return 3;
  if (score >= 400) return 2;
  if (score >= 200) return 1;
  return 0;
}

function getNodeColor(node: GraphNode): string {
  if (node.policyStatus === 'expired') return TIER_COLORS[-1];
  return TIER_COLORS[node.tier] || TIER_COLORS[2];
}

function getEdgeColor(type: string): string {
  switch (type) {
    case 'PAYMENT': return 'rgba(255,255,255,0.5)';
    case 'BLOCKED': return '#FF4444';
    case 'QUARANTINE': return '#FFD700';
    case 'WARNING': return '#FFD700';
    case 'DRIFT': return '#9B59B6';
    case 'EXPIRED': return '#888888';
    default: return 'rgba(255,255,255,0.3)';
  }
}

export default function NetworkGraph({ events, onNodeClick, onEdgeClick, historicalRound }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const simRef = useRef<d3.Simulation<GraphNode, GraphLink> | null>(null);
  const [dimensions, setDimensions] = useState({ width: 600, height: 400 });
  const [agentMap, setAgentMap] = useState<Record<string, AgentSnapshot>>({});

  // Fetch agent data for historical mode
  useEffect(() => {
    if (historicalRound && historicalRound > 0) {
      fetchState(historicalRound).then(state => {
        if (state.agents) setAgentMap(state.agents);
      }).catch(() => {});
    }
  }, [historicalRound]);

  // Track container size
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const observer = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) {
        setDimensions({ width, height });
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Build + render graph
  useEffect(() => {
    const svg = d3.select(svgRef.current);
    const { width, height } = dimensions;

    svg.selectAll('*').remove();
    svg.attr('width', width).attr('height', height);

    if (events.length === 0) return;

    // Build nodes from events + agentMap
    const nodesMap = new Map<string, GraphNode>();

    events.forEach(ev => {
      if (ev.sender && !nodesMap.has(ev.sender)) {
        const snap = agentMap[ev.sender];
        nodesMap.set(ev.sender, {
          id: ev.sender,
          tier: snap ? getTierForScore(snap.reputation_score) : 2,
          score: snap?.reputation_score ?? 500,
          payments: snap?.payments_made ?? 0,
          blocked: snap?.payments_blocked ?? 0,
          policyStatus: snap?.policy_status ?? 'active',
        });
      }
    });

    // Update counters from events
    events.forEach(ev => {
      const node = nodesMap.get(ev.sender);
      if (node) {
        if (ev.type === 'BLOCKED' || ev.type === 'QUARANTINE') {
          node.blocked++;
        } else {
          node.payments++;
        }
      }
    });

    const nodes = Array.from(nodesMap.values());
    if (nodes.length === 0) return;

    // Build links (last 100 events to keep graph manageable)
    const recentEvents = events.slice(-100);
    const links: GraphLink[] = [];

    recentEvents.forEach((ev, i) => {
      const sourceId = ev.sender;
      // For visualization: connect to a "hub" if we can't detect receiver
      // Use the second most common sender as receiver, or first different node
      const receiver = ev.receiver || (
        nodes.length > 1
          ? nodes.find(n => n.id !== sourceId)?.id || sourceId
          : sourceId
      );

      if (receiver !== sourceId && nodesMap.has(sourceId)) {
        // Ensure receiver node exists
        if (!nodesMap.has(receiver)) {
          nodesMap.set(receiver, {
            id: receiver,
            tier: 3, score: 600, payments: 0, blocked: 0, policyStatus: 'active',
          });
        }

        links.push({
          source: sourceId,
          target: receiver,
          event: ev,
          id: `${ev.tx_id || i}`,
        });
      }
    });

    // If only one node, add an AXIOM CORE hub
    if (nodes.length === 1) {
      const coreNode: GraphNode = {
        id: 'AXIOM_CORE',
        tier: 4, score: 1000, payments: 0, blocked: 0, policyStatus: 'active',
      };
      nodesMap.set('AXIOM_CORE', coreNode);
      nodes.push(coreNode);

      recentEvents.forEach((ev, i) => {
        links.push({
          source: ev.sender,
          target: 'AXIOM_CORE',
          event: ev,
          id: `core-${ev.tx_id || i}`,
        });
      });
    }

    const allNodes = Array.from(nodesMap.values());

    // SVG defs
    const defs = svg.append('defs');

    // Glow filter
    const filter = defs.append('filter').attr('id', 'glow');
    filter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'blur');
    const feMerge = filter.append('feMerge');
    feMerge.append('feMergeNode').attr('in', 'blur');
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic');

    // Big glow for nodes
    const bigGlow = defs.append('filter').attr('id', 'bigGlow');
    bigGlow.append('feGaussianBlur').attr('stdDeviation', '6').attr('result', 'blur');
    const bm = bigGlow.append('feMerge');
    bm.append('feMergeNode').attr('in', 'blur');
    bm.append('feMergeNode').attr('in', 'SourceGraphic');

    // Container group
    const g = svg.append('g');

    // Links
    const linkGroup = g.append('g').attr('class', 'links');
    const linkElements = linkGroup.selectAll<SVGLineElement, GraphLink>('line')
      .data(links.slice(-50)) // limit visible edges
      .enter()
      .append('line')
      .attr('stroke', d => getEdgeColor(d.event.type))
      .attr('stroke-width', d => {
        if (d.event.type === 'BLOCKED' || d.event.type === 'QUARANTINE') return 1;
        return Math.min(2, Math.max(0.5, d.event.amount / 1000000));
      })
      .attr('stroke-dasharray', d => {
        if (d.event.type === 'BLOCKED') return '4,4';
        if (d.event.type === 'QUARANTINE') return '6,3';
        return 'none';
      })
      .attr('opacity', 0.6)
      .style('cursor', 'pointer')
      .on('click', (_, d) => onEdgeClick?.(d.event));

    // Nodes
    const nodeGroup = g.append('g').attr('class', 'nodes');
    const nodeElements = nodeGroup.selectAll<SVGGElement, GraphNode>('g')
      .data(allNodes)
      .enter()
      .append('g')
      .style('cursor', 'pointer')
      .on('click', (_, d) => onNodeClick?.(d.id));

    // Outer glow ring
    nodeElements.append('circle')
      .attr('r', 20)
      .attr('fill', 'none')
      .attr('stroke', d => getNodeColor(d))
      .attr('stroke-width', 1)
      .attr('opacity', 0.3)
      .attr('filter', 'url(#bigGlow)');

    // Main node circle
    nodeElements.append('circle')
      .attr('r', d => d.id === 'AXIOM_CORE' ? 14 : 10)
      .attr('fill', d => getNodeColor(d))
      .attr('filter', 'url(#glow)')
      .attr('opacity', 0.9);

    // Node labels
    nodeElements.append('text')
      .attr('dy', d => (d.id === 'AXIOM_CORE' ? 26 : 22))
      .attr('text-anchor', 'middle')
      .attr('fill', 'rgba(255,255,255,0.6)')
      .attr('font-size', '9px')
      .attr('font-family', 'JetBrains Mono, monospace')
      .text(d => d.id === 'AXIOM_CORE' ? 'AXIOM' : d.id.slice(0, 8) + '...');

    // Score labels
    nodeElements.append('text')
      .attr('dy', d => (d.id === 'AXIOM_CORE' ? 36 : 32))
      .attr('text-anchor', 'middle')
      .attr('fill', d => getNodeColor(d))
      .attr('font-size', '8px')
      .attr('font-family', 'JetBrains Mono, monospace')
      .attr('opacity', 0.7)
      .text(d => d.id === 'AXIOM_CORE' ? '' : `T${d.tier} · ${d.score}`);

    // Force simulation
    const simulation = d3.forceSimulation<GraphNode>(allNodes)
      .force('link', d3.forceLink<GraphNode, GraphLink>(links.slice(-50))
        .id(d => d.id)
        .distance(100))
      .force('charge', d3.forceManyBody().strength(-200))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide(35))
      .on('tick', () => {
        linkElements
          .attr('x1', d => (d.source as GraphNode).x || 0)
          .attr('y1', d => (d.source as GraphNode).y || 0)
          .attr('x2', d => (d.target as GraphNode).x || 0)
          .attr('y2', d => (d.target as GraphNode).y || 0);

        nodeElements.attr('transform', d =>
          `translate(${d.x || 0},${d.y || 0})`
        );
      });

    simRef.current = simulation;

    // Animate traveling payment dots for recent events
    const recentPayments = recentEvents.filter(e =>
      e.type === 'PAYMENT' && links.some(l => l.event.tx_id === e.tx_id)
    ).slice(-5);

    recentPayments.forEach((ev, i) => {
      const link = links.find(l => l.event.tx_id === ev.tx_id);
      if (!link) return;

      setTimeout(() => {
        const dot = g.append('circle')
          .attr('r', 3)
          .attr('fill', '#ffffff')
          .attr('filter', 'url(#glow)')
          .attr('opacity', 1);

        // Animate along a rough path
        dot.transition()
          .duration(1000)
          .attrTween('cx', () => {
            const s = link.source as GraphNode;
            const t = link.target as GraphNode;
            return (tt: number) => String((s.x || 0) + ((t.x || 0) - (s.x || 0)) * tt);
          })
          .attrTween('cy', () => {
            const s = link.source as GraphNode;
            const t = link.target as GraphNode;
            return (tt: number) => String((s.y || 0) + ((t.y || 0) - (s.y || 0)) * tt);
          })
          .attr('opacity', 0)
          .remove();
      }, i * 200);
    });

    // Add drag
    nodeElements.call(
      d3.drag<SVGGElement, GraphNode>()
        .on('start', (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on('drag', (event, d) => {
          d.fx = event.x;
          d.fy = event.y;
        })
        .on('end', (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null;
          d.fy = null;
        })
    );

    return () => {
      simulation.stop();
    };
  }, [events, dimensions, agentMap, historicalRound, onNodeClick, onEdgeClick]);

  return (
    <div className="graph-container" ref={containerRef}>
      <svg ref={svgRef} />
      {events.length === 0 && (
        <div className="graph-empty">
          <div className="pulse-ring" />
          <span>AWAITING EVENTS</span>
          <span style={{ fontSize: 10, opacity: 0.5 }}>
            Connect backend → ws://localhost:8000/ws/events
          </span>
        </div>
      )}
    </div>
  );
}
