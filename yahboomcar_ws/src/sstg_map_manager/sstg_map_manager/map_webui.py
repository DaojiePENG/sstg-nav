"""
WebUI server for topological map visualization and management.
"""
import logging
import json
from typing import Dict, List
import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import rclpy
from rclpy.node import Node

from .topological_map import TopologicalMap


logger = logging.getLogger(__name__)


class MapWebUINode(Node):
    """ROS2 Node for WebUI server."""
    
    def __init__(self, topo_map: TopologicalMap, host: str = '0.0.0.0', port: int = 8000):
        super().__init__('map_webui_node')
        
        self.topo_map = topo_map
        self.host = host
        self.port = port
        
        self.declare_parameter('host', host)
        self.declare_parameter('port', port)
    
    def get_graph_data(self) -> Dict:
        """Get graph data for visualization."""
        nodes = []
        edges = []
        
        # Convert nodes
        for node in self.topo_map.get_all_nodes():
            nodes.append({
                'id': node.node_id,
                'label': f"Node {node.node_id}",
                'x': node.x,
                'y': node.y,
                'title': f"({node.x:.2f}, {node.y:.2f})",
                'room_type': node.semantic_info.room_type if node.semantic_info else 'unknown',
            })
        
        # Convert edges
        for u, v in self.topo_map.graph.edges():
            edges.append({
                'from': u,
                'to': v,
            })
        
        return {
            'nodes': nodes,
            'edges': edges,
        }


def create_fastapi_app(topo_map: TopologicalMap) -> FastAPI:
    """Create FastAPI application."""
    app = FastAPI(title="SSTG Map Manager WebUI")
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    @app.get("/", response_class=HTMLResponse)
    async def get_root():
        """Serve main HTML page."""
        return get_html_content()
    
    @app.get("/api/graph")
    async def get_graph():
        """Get graph data for visualization."""
        nodes = []
        edges = []
        
        # Convert nodes
        for node in topo_map.get_all_nodes():
            nodes.append({
                'id': node.node_id,
                'label': f"Node {node.node_id}",
                'x': node.x,
                'y': node.y,
                'title': f"({node.x:.2f}, {node.y:.2f})",
                'room_type': node.semantic_info.room_type if node.semantic_info else 'unknown',
            })
        
        # Convert edges
        for u, v in topo_map.graph.edges():
            edges.append({
                'from': u,
                'to': v,
            })
        
        return {
            'nodes': nodes,
            'edges': edges,
            'metadata': {
                'node_count': topo_map.get_node_count(),
                'edge_count': topo_map.get_edge_count(),
            }
        }
    
    @app.get("/api/node/{node_id}")
    async def get_node(node_id: int):
        """Get details of a specific node."""
        node = topo_map.get_node(node_id)
        if not node:
            raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
        
        return node.to_dict()
    
    @app.post("/api/node")
    async def create_node(data: Dict):
        """Create a new node."""
        x = data.get('x', 0.0)
        y = data.get('y', 0.0)
        theta = data.get('theta', 0.0)
        
        node = topo_map.create_node(x, y, theta)
        return node.to_dict()
    
    @app.delete("/api/node/{node_id}")
    async def delete_node(node_id: int):
        """Delete a node."""
        success = topo_map.delete_node(node_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
        
        return {"success": True, "message": f"Node {node_id} deleted"}
    
    @app.post("/api/edge")
    async def create_edge(data: Dict):
        """Create an edge between two nodes."""
        from_id = data.get('from')
        to_id = data.get('to')
        distance = data.get('distance', 0.0)
        
        success = topo_map.add_edge(from_id, to_id, distance)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to add edge")
        
        return {"success": True}
    
    @app.delete("/api/edge")
    async def delete_edge(data: Dict):
        """Delete an edge between two nodes."""
        from_id = data.get('from')
        to_id = data.get('to')
        
        success = topo_map.remove_edge(from_id, to_id)
        if not success:
            raise HTTPException(status_code=404, detail="Edge not found")
        
        return {"success": True}
    
    @app.post("/api/save")
    async def save_map():
        """Save the current map."""
        success = topo_map.save_to_file()
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save map")
        
        return {"success": True, "message": "Map saved"}
    
    return app


def get_html_content() -> str:
    """Get HTML content for the WebUI."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>SSTG Map Manager</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: Arial, sans-serif;
                background: #f5f5f5;
            }
            
            #container {
                display: flex;
                height: 100vh;
            }
            
            #canvas {
                flex: 1;
                background: #fff;
                position: relative;
            }
            
            #sidebar {
                width: 300px;
                background: #2c3e50;
                color: #fff;
                padding: 20px;
                overflow-y: auto;
            }
            
            #sidebar h2 {
                margin-bottom: 20px;
                border-bottom: 2px solid #3498db;
                padding-bottom: 10px;
            }
            
            .node-info {
                background: #34495e;
                padding: 15px;
                margin-bottom: 10px;
                border-radius: 5px;
                cursor: pointer;
            }
            
            .node-info:hover {
                background: #3498db;
            }
            
            .stats {
                background: #34495e;
                padding: 15px;
                border-radius: 5px;
                margin-bottom: 20px;
            }
            
            .stat-item {
                display: flex;
                justify-content: space-between;
                margin-bottom: 10px;
            }
            
            button {
                background: #3498db;
                color: white;
                border: none;
                padding: 10px 15px;
                border-radius: 5px;
                cursor: pointer;
                margin-bottom: 5px;
                width: 100%;
            }
            
            button:hover {
                background: #2980b9;
            }
            
            #status {
                text-align: center;
                padding: 10px;
                background: #ecf0f1;
                color: #2c3e50;
            }
        </style>
    </head>
    <body>
        <div id="container">
            <div id="canvas">
                <svg id="graph-svg" width="100%" height="100%"></svg>
            </div>
            <div id="sidebar">
                <h2>Map Info</h2>
                <div class="stats" id="stats">
                    <div class="stat-item">
                        <span>Nodes:</span>
                        <span id="node-count">0</span>
                    </div>
                    <div class="stat-item">
                        <span>Edges:</span>
                        <span id="edge-count">0</span>
                    </div>
                </div>
                
                <h2>Actions</h2>
                <button onclick="saveMap()">Save Map</button>
                <button onclick="clearSelection()">Clear Selection</button>
                
                <h2>Nodes</h2>
                <div id="nodes-list"></div>
            </div>
        </div>
        <div id="status">Ready</div>
        
        <script>
            let graphData = {};
            let selectedNode = null;
            
            async function loadGraph() {
                try {
                    const response = await fetch('/api/graph');
                    graphData = await response.json();
                    updateStats();
                    renderGraph();
                    updateNodesList();
                } catch (e) {
                    console.error('Error loading graph:', e);
                    document.getElementById('status').textContent = 'Error loading map';
                }
            }
            
            function updateStats() {
                document.getElementById('node-count').textContent = graphData.metadata?.node_count || 0;
                document.getElementById('edge-count').textContent = graphData.metadata?.edge_count || 0;
            }
            
            function renderGraph() {
                const svg = document.getElementById('graph-svg');
                svg.innerHTML = '';
                
                const padding = 50;
                const width = svg.clientWidth - 2 * padding;
                const height = svg.clientHeight - 2 * padding;
                
                // Draw edges
                if (graphData.edges) {
                    graphData.edges.forEach(edge => {
                        const fromNode = graphData.nodes.find(n => n.id === edge.from);
                        const toNode = graphData.nodes.find(n => n.id === edge.to);
                        
                        if (fromNode && toNode) {
                            const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                            line.setAttribute('x1', fromNode.x + padding);
                            line.setAttribute('y1', fromNode.y + padding);
                            line.setAttribute('x2', toNode.x + padding);
                            line.setAttribute('y2', toNode.y + padding);
                            line.setAttribute('stroke', '#95a5a6');
                            line.setAttribute('stroke-width', '2');
                            svg.appendChild(line);
                        }
                    });
                }
                
                // Draw nodes
                if (graphData.nodes) {
                    graphData.nodes.forEach(node => {
                        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                        circle.setAttribute('cx', node.x + padding);
                        circle.setAttribute('cy', node.y + padding);
                        circle.setAttribute('r', '15');
                        circle.setAttribute('fill', selectedNode?.id === node.id ? '#e74c3c' : '#3498db');
                        circle.setAttribute('cursor', 'pointer');
                        circle.onclick = () => selectNode(node.id);
                        circle.onmouseover = () => circle.setAttribute('fill', '#2980b9');
                        circle.onmouseout = () => {
                            if (selectedNode?.id !== node.id) {
                                circle.setAttribute('fill', '#3498db');
                            }
                        };
                        svg.appendChild(circle);
                        
                        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                        text.setAttribute('x', node.x + padding);
                        text.setAttribute('y', node.y + padding + 5);
                        text.setAttribute('text-anchor', 'middle');
                        text.setAttribute('fill', 'white');
                        text.setAttribute('font-size', '12');
                        text.textContent = node.id;
                        svg.appendChild(text);
                    });
                }
            }
            
            function updateNodesList() {
                const list = document.getElementById('nodes-list');
                list.innerHTML = '';
                
                if (graphData.nodes) {
                    graphData.nodes.forEach(node => {
                        const div = document.createElement('div');
                        div.className = 'node-info';
                        div.textContent = `Node ${node.id} (${node.room_type})`;
                        div.onclick = () => selectNode(node.id);
                        list.appendChild(div);
                    });
                }
            }
            
            function selectNode(nodeId) {
                selectedNode = graphData.nodes.find(n => n.id === nodeId);
                renderGraph();
            }
            
            function clearSelection() {
                selectedNode = null;
                renderGraph();
            }
            
            async function saveMap() {
                try {
                    const response = await fetch('/api/save', { method: 'POST' });
                    if (response.ok) {
                        document.getElementById('status').textContent = 'Map saved successfully';
                    }
                } catch (e) {
                    document.getElementById('status').textContent = 'Error saving map';
                }
            }
            
            // Auto-refresh every 2 seconds
            setInterval(loadGraph, 2000);
            
            // Initial load
            loadGraph();
        </script>
    </body>
    </html>
    """


def main(args=None):
    """Main entry point for WebUI."""
    # Create FastAPI app
    topo_map = TopologicalMap(map_file='/tmp/topological_map.json')
    app = create_fastapi_app(topo_map)
    
    # Run uvicorn
    logger.info("Starting Map WebUI on http://0.0.0.0:8000")
    uvicorn.run(app, host='0.0.0.0', port=8000, log_level='info')


if __name__ == '__main__':
    main()
