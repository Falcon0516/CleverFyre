import React, { useEffect, useRef } from 'react';
import * as d3 from 'd3';
import type { PaymentEvent } from './AlgorandStream';

interface NetworkGraphProps {
  events: PaymentEvent[];
  onNodeClick: (addr: string) => void;
  onEdgeClick: (txId: string) => void;
  historicalRound: number | null;
}

export const NetworkGraph: React.FC<NetworkGraphProps> = ({ events, onNodeClick, onEdgeClick, historicalRound }) => {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current) return;
    const width = 800;
    const height = 800;
    const svg = d3.select(svgRef.current)
      .attr('viewBox', `0 0 ${width} ${height}`)
      .attr('width', '100%')
      .attr('height', '100%');
    
    svg.selectAll('*').remove();

    const defs = svg.append('defs');
    
    const shadowFilter = defs.append('filter').attr('id', 'drop-shadow-graph');
    shadowFilter.append('feGaussianBlur').attr('in', 'SourceAlpha').attr('stdDeviation', 4);
    shadowFilter.append('feOffset').attr('dx', 0).attr('dy', 4).attr('result', 'offsetblur');
    shadowFilter.append('feFlood').attr('flood-color', 'rgba(0, 0, 0, 0.1)');
    shadowFilter.append('feComposite').attr('in2', 'offsetblur').attr('operator', 'in');
    const feMerge = shadowFilter.append('feMerge');
    feMerge.append('feMergeNode');
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic');

    const providerGradient = defs.append('radialGradient').attr('id', 'provider-grad');
    providerGradient.append('stop').attr('offset', '0%').attr('stop-color', '#ffffff');
    providerGradient.append('stop').attr('offset', '100%').attr('stop-color', '#f1f5f9');

    const nodesMap = new Map();
    nodesMap.set('API_PROVIDER', { id: 'API_PROVIDER', type: 'provider', group: 1 });
    
    events.forEach(ev => {
      let tier = 'EXCELLENT';
      if (ev.sender.startsWith('MMM')) tier = 'CAUTION';
      if (ev.sender.startsWith('ZZZ')) tier = 'RESTRICTED';
      if (ev.sender.length < 8) tier = 'EXPIRED'; 
      
      if (!nodesMap.has(ev.sender)) {
        nodesMap.set(ev.sender, { id: ev.sender, type: 'agent', group: 2, tier });
      }
    });
    
    const links = events.map((ev, i) => ({
      source: ev.sender,
      target: 'API_PROVIDER',
      id: ev.tx_id + '-' + i,
      eventType: ev.type
    }));
    
    const nodes = Array.from(nodesMap.values());
    
    const simulation = d3.forceSimulation(nodes as any)
      .force('link', d3.forceLink(links).id((d: any) => d.id).distance(220))
      .force('charge', d3.forceManyBody().strength(-800))
      .force('collide', d3.forceCollide().radius(50))
      .force('center', d3.forceCenter(width / 2, height / 2));

    const linkContainer = svg.append('g').attr('class', 'links');
    const nodeContainer = svg.append('g').attr('class', 'nodes');

    // Curved edges
    const link = linkContainer.selectAll('path')
      .data(links)
      .enter().append('path')
      .attr('fill', 'none')
      .attr('stroke', d => {
        if (d.eventType === 'BLOCK') return '#ef4444';
        if (d.eventType === 'QUARANTINE') return '#f59e0b';
        if (d.eventType === 'CONSENSUS_PENDING') return '#8b5cf6';
        if (d.eventType === 'DRIFT') return '#8b5cf6';
        return 'rgba(14, 165, 233, 0.4)';
      })
      .attr('stroke-width', 4)
      .attr('stroke-dasharray', d => {
        if (d.eventType === 'BLOCK') return '8,8';
        if (d.eventType === 'QUARANTINE') return '8,8';
        if (d.eventType === 'CONSENSUS_PENDING') return '15,10';
        return '0';
      })
      .attr('class', d => {
        if (d.eventType === 'QUARANTINE') return 'pulse-slow interactive';
        if (d.eventType === 'CONSENSUS_PENDING') return 'dash-rotate interactive';
        return 'interactive';
      })
      .style('cursor', 'pointer')
      .on('click', (e, d) => onEdgeClick(d.id.split('-')[0]));

    const node = nodeContainer.selectAll('g')
      .data(nodes)
      .enter().append('g')
      .attr('class', 'interactive')
      .style('cursor', 'pointer')
      .on('click', (e, d) => onNodeClick(d.id));

    const getColor = (tier: string) => {
      if (tier === 'EXCELLENT') return '#0ea5e9';
      if (tier === 'GOOD') return '#10b981';
      if (tier === 'CAUTION') return '#f59e0b';
      if (tier === 'RESTRICTED') return '#ef4444';
      if (tier === 'BLACKLISTED') return '#ef4444';
      if (tier === 'EXPIRED') return '#94a3b8';
      return '#0ea5e9';
    };

    // Outer aura
    node.append('circle')
      .attr('r', d => d.id === 'API_PROVIDER' ? 45 : 30)
      .attr('fill', 'none')
      .attr('stroke', d => d.id === 'API_PROVIDER' ? '#cbd5e1' : getColor(d.tier))
      .attr('stroke-width', 8)
      .attr('opacity', 0.2)
      .style('filter', 'blur(6px)')
      .attr('class', d => {
        if (d.tier === 'CAUTION') return 'pulse-slow';
        if (d.tier === 'RESTRICTED') return 'pulse-fast';
        return '';
      });

    // Inner node solid body
    node.append('circle')
      .attr('r', d => d.id === 'API_PROVIDER' ? 30 : 20)
      .attr('fill', d => d.id === 'API_PROVIDER' ? 'url(#provider-grad)' : 'white')
      .attr('stroke', d => d.id === 'API_PROVIDER' ? '#94a3b8' : getColor(d.tier))
      .attr('stroke-width', 4)
      .style('filter', 'url(#drop-shadow-graph)')
      .on('mouseover', function() { d3.select(this).transition().duration(200).attr('r', (d: any) => d.id === 'API_PROVIDER' ? 35 : 24) })
      .on('mouseout', function() { d3.select(this).transition().duration(200).attr('r', (d: any) => d.id === 'API_PROVIDER' ? 30 : 20) });

    node.append('text')
      .text(d => d.id === 'API_PROVIDER' ? 'AXIOM CORE' : d.id.substring(0, 6))
      .attr('text-anchor', 'middle')
      .attr('dy', d => d.id === 'API_PROVIDER' ? 55 : 45)
      .attr('fill', '#475569')
      .style('font-family', 'var(--font-sans)')
      .style('font-weight', '700')
      .style('font-size', '12px');

    simulation.on('tick', () => {
      link.attr('d', (d: any) => {
        const dx = d.target.x - d.source.x;
        const dy = d.target.y - d.source.y;
        const dr = Math.sqrt(dx * dx + dy * dy) * 1.5; 
        return `M${d.source.x},${d.source.y}A${dr},${dr} 0 0,1 ${d.target.x},${d.target.y}`;
      });
      node.attr('transform', (d: any) => `translate(${d.x},${d.y})`);
    });

    setTimeout(() => {
      link.each(function(d: any) {
        if(d.eventType !== 'PAYMENT') return;
        const path = this as SVGPathElement;
        const l = path.getTotalLength();
        if (l === 0) return;
        
        svg.append('circle')
          .attr('r', 6)
          .attr('fill', '#0ea5e9')
          .style('filter', 'url(#drop-shadow-graph)')
          .transition()
          .duration(1200)
          .ease(d3.easeCubicInOut)
          .attrTween('transform', () => {
            return function(t) {
              const p = path.getPointAtLength(t * l);
              return `translate(${p.x},${p.y})`;
            };
          })
          .remove();
      });
    }, 100);

  }, [events, historicalRound]);

  return (
    <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <svg ref={svgRef}></svg>
    </div>
  );
};
