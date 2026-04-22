"""
WebUI server for topological map visualization and management.
"""
import logging
import json
from typing import Dict, List
import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import rclpy
from rclpy.node import Node

from .topological_map import TopologicalMap
from .topological_node import SemanticInfo, SemanticObject


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
                'theta': node.theta,
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
                'theta': node.theta,
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
                'map_file': topo_map.map_file or 'Not specified'
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
        """Create a new node with full semantic info."""
        # Basic pose info
        x = data.get('x', 0.0)
        y = data.get('y', 0.0)
        theta = data.get('theta', 0.0)
        
        # Create base node
        node = topo_map.create_node(x, y, theta)
        
        # Add semantic info if provided
        semantic_data = data.get('semantic_info', {})
        if semantic_data:
            room_type = semantic_data.get('room_type', '')
            confidence = semantic_data.get('confidence', 0.0)
            description = semantic_data.get('description', '')
            objects_data = semantic_data.get('objects', [])
            
            objects = []
            for obj_data in objects_data:
                obj = SemanticObject(
                    name=obj_data.get('name', ''),
                    position=obj_data.get('position', ''),
                    quantity=obj_data.get('quantity', 1),
                    confidence=obj_data.get('confidence', 0.0)
                )
                objects.append(obj)
            
            semantic_info = SemanticInfo(
                room_type=room_type,
                confidence=confidence,
                objects=objects,
                description=description
            )
            topo_map.update_semantic(node.node_id, semantic_info)
        
        # Add panorama paths if provided
        panorama_paths = data.get('panorama_paths', {})
        for angle, path in panorama_paths.items():
            topo_map.add_panorama_image(node.node_id, angle, path)
        
        return node.to_dict()
    
    @app.put("/api/node/{node_id}")
    async def update_node(node_id: int, data: Dict):
        """Update an existing node's information."""
        node = topo_map.get_node(node_id)
        if not node:
            raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
        
        # Update pose if provided
        pose_data = data.get('pose', {})
        if pose_data:
            node.x = pose_data.get('x', node.x)
            node.y = pose_data.get('y', node.y)
            node.theta = pose_data.get('theta', node.theta)
        
        # Update semantic info if provided
        semantic_data = data.get('semantic_info', {})
        if semantic_data:
            room_type = semantic_data.get('room_type', node.semantic_info.room_type if node.semantic_info else '')
            confidence = semantic_data.get('confidence', node.semantic_info.confidence if node.semantic_info else 0.0)
            description = semantic_data.get('description', node.semantic_info.description if node.semantic_info else '')
            objects_data = semantic_data.get('objects', [])
            
            objects = []
            for obj_data in objects_data:
                obj = SemanticObject(
                    name=obj_data.get('name', ''),
                    position=obj_data.get('position', ''),
                    quantity=obj_data.get('quantity', 1),
                    confidence=obj_data.get('confidence', 0.0)
                )
                objects.append(obj)
            
            semantic_info = SemanticInfo(
                room_type=room_type,
                confidence=confidence,
                objects=objects,
                description=description
            )
            topo_map.update_semantic(node_id, semantic_info)
        
        # Update panorama paths if provided
        panorama_paths = data.get('panorama_paths', {})
        for angle, path in panorama_paths.items():
            topo_map.add_panorama_image(node_id, angle, path)
        
        node.last_updated = data.get('last_updated', node.last_updated)
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
        
        return {
            "success": True, 
            "message": f"Map saved to {topo_map.map_file}",
            "map_file": topo_map.map_file
        }
    
    @app.post("/api/load")
    async def load_map(data: Dict = None):
        """Load a map from file."""
        file_path = data.get('file_path', topo_map.map_file) if data else topo_map.map_file
        if not file_path:
            raise HTTPException(status_code=400, detail="No map file path specified")
        
        success = topo_map.load_from_file(file_path)
        if not success:
            raise HTTPException(status_code=500, detail=f"Failed to load map from {file_path}")
        
        return {
            "success": True, 
            "message": f"Map loaded from {file_path}",
            "map_file": file_path
        }
    
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
                width: 450px;
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
            
            .form-group {
                margin-bottom: 15px;
            }
            
            label {
                display: block;
                margin-bottom: 5px;
                font-weight: bold;
            }
            
            input, select, textarea {
                width: 100%;
                padding: 8px;
                border-radius: 4px;
                border: 1px solid #ddd;
                background: #fff;
                color: #333;
            }
            
            .node-details {
                background: #34495e;
                padding: 15px;
                border-radius: 5px;
                margin-bottom: 20px;
                display: none;
            }
            
            .object-item {
                background: #2c3e50;
                padding: 10px;
                border-radius: 4px;
                margin-bottom: 8px;
            }
            
            .map-file-info {
                font-size: 0.9em;
                color: #bdc3c7;
                margin-top: 5px;
            }
            
            .action-buttons {
                display: flex;
                gap: 10px;
                margin-bottom: 15px;
            }
            
            .action-buttons button {
                flex: 1;
                margin-bottom: 0;
            }
            
            .object-form {
                background: #34495e;
                padding: 10px;
                border-radius: 5px;
                margin-bottom: 10px;
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
                    <div class="stat-item">
                        <span>Map File:</span>
                        <span id="map-file">Not specified</span>
                    </div>
                    <div class="map-file-info" id="map-file-path"></div>
                </div>
                
                <div class="action-buttons">
                    <button onclick="saveMap()">Save Map</button>
                    <button onclick="loadMap()">Load Map</button>
                </div>
                
                <h2>Edge Control</h2>
                <div class="stats">
                    <div class="form-group">
                        <label>From Node ID</label>
                        <input type="number" id="edge-from" placeholder="Node ID">
                    </div>
                    <div class="form-group">
                        <label>To Node ID</label>
                        <input type="number" id="edge-to" placeholder="Node ID">
                    </div>
                    <div class="form-group">
                        <label>Distance (optional)</label>
                        <input type="number" id="edge-distance" step="0.01" value="0.0">
                    </div>
                    <div class="action-buttons">
                        <button onclick="createEdge()">Add Edge</button>
                        <button onclick="deleteEdge()" style="background:#e74c3c">Delete Edge</button>
                    </div>
                </div>
                
                <h2>Create Node</h2>
                <div class="stats">
                    <div class="form-group">
                        <label>X Coordinate</label>
                        <input type="number" id="new-node-x" step="0.01" value="0.0">
                    </div>
                    <div class="form-group">
                        <label>Y Coordinate</label>
                        <input type="number" id="new-node-y" step="0.01" value="0.0">
                    </div>
                    <div class="form-group">
                        <label>Theta (deg)</label>
                        <input type="number" id="new-node-theta" step="1" value="0">
                    </div>
                    <div class="form-group">
                        <label>Room Type</label>
                        <input type="text" id="new-node-room-type" placeholder="e.g. living_room">
                    </div>
                    <div class="form-group">
                        <label>Room Confidence</label>
                        <input type="number" id="new-node-confidence" step="0.01" min="0" max="1" value="0.0">
                    </div>
                    <div class="form-group">
                        <label>Description</label>
                        <textarea id="new-node-description" rows="2"></textarea>
                    </div>
                    <div class="form-group">
                        <label>Object Name</label>
                        <input type="text" id="new-object-name" placeholder="e.g. table">
                    </div>
                    <div class="form-group">
                        <label>Object Position</label>
                        <input type="text" id="new-object-position" placeholder="e.g. center">
                    </div>
                    <button onclick="createNewNode()">Create Node</button>
                </div>
                
                <h2>Selected Node</h2>
                <div class="node-details" id="selected-node-details">
                    <div class="form-group">
                        <label>Node ID</label>
                        <input type="text" id="node-id-display" readonly>
                    </div>
                    <div class="form-group">
                        <label>X Coordinate</label>
                        <input type="number" id="node-x" step="0.01">
                    </div>
                    <div class="form-group">
                        <label>Y Coordinate</label>
                        <input type="number" id="node-y" step="0.01">
                    </div>
                    <div class="form-group">
                        <label>Theta (deg)</label>
                        <input type="number" id="node-theta" step="1">
                    </div>
                    <div class="form-group">
                        <label>Room Type</label>
                        <input type="text" id="node-room-type">
                    </div>
                    <div class="form-group">
                        <label>Room Confidence</label>
                        <input type="number" id="node-confidence" step="0.01" min="0" max="1">
                    </div>
                    <div class="form-group">
                        <label>Description</label>
                        <textarea id="node-description" rows="2"></textarea>
                    </div>

                    <h4>Objects (Editable)</h4>
                    <div id="node-objects-list"></div>
                    
                    <div class="object-form">
                        <div class="form-group">
                            <label>Add/Edit Object</label>
                            <input type="hidden" id="edit-object-index" value="-1">
                        </div>
                        <div class="form-group">
                            <label>Object Name</label>
                            <input type="text" id="edit-object-name" placeholder="Name">
                        </div>
                        <div class="form-group">
                            <label>Position</label>
                            <input type="text" id="edit-object-position" placeholder="Position">
                        </div>
                        <div class="form-group">
                            <label>Quantity</label>
                            <input type="number" id="edit-object-quantity" min="1" value="1">
                        </div>
                        <div class="form-group">
                            <label>Confidence</label>
                            <input type="number" id="edit-object-confidence" step="0.01" min="0" max="1" value="1.0">
                        </div>
                        <div class="action-buttons">
                            <button onclick="saveObject()">Save Object</button>
                            <button onclick="deleteSelectedObject()" style="background:#e74c3c">Delete Object</button>
                        </div>
                    </div>

                    <div class="action-buttons">
                        <button onclick="updateSelectedNode()">Update Node</button>
                        <button onclick="deleteSelectedNode()" style="background: #e74c3c;">Delete Node</button>
                    </div>
                </div>
                
                <h2>Nodes</h2>
                <div id="nodes-list"></div>
            </div>
        </div>
        <div id="status">Ready</div>
        
        <script>
            let graphData = {};
            let selectedNode = null;
            let mapFilePath = '';
            
            async function loadGraph() {
                try {
                    const response = await fetch('/api/graph');
                    graphData = await response.json();
                    updateStats();
                    renderGraph();
                    updateNodesList();
                    mapFilePath = graphData.metadata?.map_file || 'Not specified';
                    document.getElementById('map-file').textContent = mapFilePath.split('/').pop() || mapFilePath;
                    document.getElementById('map-file-path').textContent = mapFilePath;
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
                
                // Draw nodes (as arrows with theta direction)
                if (graphData.nodes) {
                    graphData.nodes.forEach(node => {
                        const nodeX = node.x + padding;
                        const nodeY = node.y + padding;
                        const thetaRad = (node.theta || 0) * Math.PI / 180;
                        
                        // Arrow size and shape
                        const arrowSize = 16;
                        const arrowPoints = [
                            [0, -arrowSize/2],          
                            [arrowSize, 0],             
                            [0, arrowSize/2],           
                            [arrowSize/3, 0]            
                        ];
                        
                        // Rotate arrow points based on theta
                        const rotatedPoints = arrowPoints.map(([x, y]) => {
                            const rotatedX = x * Math.cos(thetaRad) - y * Math.sin(thetaRad);
                            const rotatedY = x * Math.sin(thetaRad) + y * Math.cos(thetaRad);
                            return [nodeX + rotatedX, nodeY + rotatedY];
                        });
                        
                        // Create arrow polygon
                        const arrow = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
                        arrow.setAttribute('points', rotatedPoints.map(p => p.join(',')).join(' '));
                        arrow.setAttribute('fill', selectedNode?.id === node.id ? '#e74c3c' : '#3498db');
                        arrow.setAttribute('cursor', 'pointer');
                        arrow.onclick = () => selectNode(node.id);
                        arrow.onmouseover = () => {
                            if (selectedNode?.id !== node.id) {
                                arrow.setAttribute('fill', '#2980b9');
                            }
                        };
                        arrow.onmouseout = () => {
                            if (selectedNode?.id !== node.id) {
                                arrow.setAttribute('fill', '#3498db');
                            }
                        };
                        svg.appendChild(arrow);
                        
                        // Add node ID text
                        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                        text.setAttribute('x', nodeX);
                        text.setAttribute('y', nodeY + arrowSize + 6);
                        text.setAttribute('text-anchor', 'middle');
                        text.setAttribute('fill', '#2c3e50');
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
            
            async function selectNode(nodeId) {
                try {
                    const response = await fetch(`/api/node/${nodeId}`);
                    selectedNode = await response.json();
                    
                    // Show node details
                    document.getElementById('selected-node-details').style.display = 'block';
                    
                    // Populate form fields
                    document.getElementById('node-id-display').value = selectedNode.id;
                    document.getElementById('node-x').value = selectedNode.pose.x;
                    document.getElementById('node-y').value = selectedNode.pose.y;
                    document.getElementById('node-theta').value = selectedNode.pose.theta;
                    
                    const semanticInfo = selectedNode.semantic_info || {};
                    document.getElementById('node-room-type').value = semanticInfo.room_type || '';
                    document.getElementById('node-confidence').value = semanticInfo.confidence || 0.0;
                    document.getElementById('node-description').value = semanticInfo.description || '';
                    
                    // Populate objects list
                    renderObjectsList();
                    renderGraph();
                } catch (e) {
                    console.error('Error loading node details:', e);
                    document.getElementById('status').textContent = 'Error loading node details';
                }
            }
            
            function renderObjectsList() {
                const list = document.getElementById('node-objects-list');
                list.innerHTML = '';
                const objects = (selectedNode.semantic_info?.objects || []);
                
                objects.forEach((obj, index) => {
                    const div = document.createElement('div');
                    div.className = 'object-item';
                    div.style.cursor = 'pointer';
                    div.onclick = () => editObject(index);
                    div.innerHTML = `
                        <div><strong>${index + 1}. ${obj.name}</strong></div>
                        <div>Position: ${obj.position}</div>
                        <div>Qty: ${obj.quantity} | Conf: ${obj.confidence.toFixed(2)}</div>
                    `;
                    list.appendChild(div);
                });
            }
            
            function editObject(index) {
                const obj = selectedNode.semantic_info.objects[index];
                document.getElementById('edit-object-index').value = index;
                document.getElementById('edit-object-name').value = obj.name;
                document.getElementById('edit-object-position').value = obj.position;
                document.getElementById('edit-object-quantity').value = obj.quantity;
                document.getElementById('edit-object-confidence').value = obj.confidence;
            }
            
            function saveObject() {
                if (!selectedNode) return;
                
                const index = parseInt(document.getElementById('edit-object-index').value);
                const obj = {
                    name: document.getElementById('edit-object-name').value.trim(),
                    position: document.getElementById('edit-object-position').value.trim(),
                    quantity: parseInt(document.getElementById('edit-object-quantity').value) || 1,
                    confidence: parseFloat(document.getElementById('edit-object-confidence').value) || 1.0
                };
                
                if (!obj.name) {
                    alert('Please enter object name');
                    return;
                }
                
                if (!selectedNode.semantic_info) selectedNode.semantic_info = { objects: [] };
                if (index === -1) {
                    selectedNode.semantic_info.objects.push(obj);
                } else {
                    selectedNode.semantic_info.objects[index] = obj;
                }
                
                renderObjectsList();
                clearObjectForm();
                document.getElementById('status').textContent = 'Object saved';
            }
            
            function deleteSelectedObject() {
                if (!selectedNode) return;
                const index = parseInt(document.getElementById('edit-object-index').value);
                if (index === -1) return;
                
                selectedNode.semantic_info.objects.splice(index, 1);
                renderObjectsList();
                clearObjectForm();
                document.getElementById('status').textContent = 'Object deleted';
            }
            
            function clearObjectForm() {
                document.getElementById('edit-object-index').value = -1;
                document.getElementById('edit-object-name').value = '';
                document.getElementById('edit-object-position').value = '';
                document.getElementById('edit-object-quantity').value = 1;
                document.getElementById('edit-object-confidence').value = 1.0;
            }
            
            function clearSelection() {
                selectedNode = null;
                document.getElementById('selected-node-details').style.display = 'none';
                clearObjectForm();
                renderGraph();
            }
            
            async function saveMap() {
                try {
                    const response = await fetch('/api/save', { method: 'POST' });
                    const result = await response.json();
                    if (response.ok) {
                        document.getElementById('status').textContent = result.message;
                        mapFilePath = result.map_file;
                        document.getElementById('map-file').textContent = mapFilePath.split('/').pop() || mapFilePath;
                        document.getElementById('map-file-path').textContent = mapFilePath;
                    }
                } catch (e) {
                    document.getElementById('status').textContent = 'Error saving map';
                }
            }
            
            async function loadMap() {
                try {
                    const filePath = prompt('Enter map file path (leave empty for default):', mapFilePath);
                    if (!filePath) return;
                    
                    const response = await fetch('/api/load', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ file_path: filePath })
                    });
                    
                    const result = await response.json();
                    if (response.ok) {
                        document.getElementById('status').textContent = result.message;
                        loadGraph();
                    }
                } catch (e) {
                    document.getElementById('status').textContent = 'Error loading map';
                }
            }
            
            async function createNewNode() {
                try {
                    const newNodeData = {
                        x: parseFloat(document.getElementById('new-node-x').value) || 0.0,
                        y: parseFloat(document.getElementById('new-node-y').value) || 0.0,
                        theta: parseFloat(document.getElementById('new-node-theta').value) || 0.0,
                        semantic_info: {
                            room_type: document.getElementById('new-node-room-type').value,
                            confidence: parseFloat(document.getElementById('new-node-confidence').value) || 0.0,
                            description: document.getElementById('new-node-description').value,
                            objects: []
                        },
                        panorama_paths: {}
                    };
                    
                    const objName = document.getElementById('new-object-name').value.trim();
                    if (objName) {
                        newNodeData.semantic_info.objects.push({
                            name: objName,
                            position: document.getElementById('new-object-position').value.trim() || 'unknown',
                            quantity: 1,
                            confidence: 1.0
                        });
                    }
                    
                    const response = await fetch('/api/node', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(newNodeData)
                    });
                    
                    if (response.ok) {
                        document.getElementById('status').textContent = 'Node created successfully';
                        loadGraph();
                        document.getElementById('new-node-x').value = '0.0';
                        document.getElementById('new-node-y').value = '0.0';
                        document.getElementById('new-node-theta').value = '0';
                        document.getElementById('new-node-room-type').value = '';
                        document.getElementById('new-node-confidence').value = '0.0';
                        document.getElementById('new-node-description').value = '';
                        document.getElementById('new-object-name').value = '';
                        document.getElementById('new-object-position').value = '';
                    }
                } catch (e) {
                    document.getElementById('status').textContent = 'Error creating node';
                }
            }
            
            async function updateSelectedNode() {
                if (!selectedNode) return;
                
                try {
                    const updatedData = {
                        pose: {
                            x: parseFloat(document.getElementById('node-x').value) || selectedNode.pose.x,
                            y: parseFloat(document.getElementById('node-y').value) || selectedNode.pose.y,
                            theta: parseFloat(document.getElementById('node-theta').value) || selectedNode.pose.theta
                        },
                        semantic_info: {
                            room_type: document.getElementById('node-room-type').value,
                            confidence: parseFloat(document.getElementById('node-confidence').value) || 0.0,
                            description: document.getElementById('node-description').value,
                            objects: selectedNode.semantic_info?.objects || []
                        },
                        panorama_paths: selectedNode.panorama_paths || {}
                    };
                    
                    const response = await fetch(`/api/node/${selectedNode.id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(updatedData)
                    });
                    
                    if (response.ok) {
                        document.getElementById('status').textContent = 'Node updated successfully';
                        loadGraph();
                    }
                } catch (e) {
                    document.getElementById('status').textContent = 'Error updating node';
                }
            }
            
            async function deleteSelectedNode() {
                if (!selectedNode) return;
                
                if (confirm(`Delete Node ${selectedNode.id}?`)) {
                    try {
                        const response = await fetch(`/api/node/${selectedNode.id}`, { method: 'DELETE' });
                        if (response.ok) {
                            document.getElementById('status').textContent = `Node ${selectedNode.id} deleted`;
                            clearSelection();
                            loadGraph();
                        }
                    } catch (e) {
                        document.getElementById('status').textContent = 'Error deleting node';
                    }
                }
            }
            
            // ==================== EDGE FUNCTIONS ====================
            async function createEdge() {
                const fromId = parseInt(document.getElementById('edge-from').value);
                const toId = parseInt(document.getElementById('edge-to').value);
                const distance = parseFloat(document.getElementById('edge-distance').value) || 0.0;
                
                if (isNaN(fromId) || isNaN(toId)) {
                    document.getElementById('status').textContent = 'Please enter valid node IDs';
                    return;
                }
                
                try {
                    const response = await fetch('/api/edge', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ from: fromId, to: toId, distance: distance })
                    });
                    
                    if (response.ok) {
                        document.getElementById('status').textContent = 'Edge created';
                        loadGraph();
                    } else {
                        document.getElementById('status').textContent = 'Failed to create edge';
                    }
                } catch (e) {
                    document.getElementById('status').textContent = 'Error creating edge';
                }
            }
            
            async function deleteEdge() {
                const fromId = parseInt(document.getElementById('edge-from').value);
                const toId = parseInt(document.getElementById('edge-to').value);
                
                if (isNaN(fromId) || isNaN(toId)) {
                    document.getElementById('status').textContent = 'Please enter valid node IDs';
                    return;
                }
                
                try {
                    const response = await fetch('/api/edge', {
                        method: 'DELETE',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ from: fromId, to: toId })
                    });
                    
                    if (response.ok) {
                        document.getElementById('status').textContent = 'Edge deleted';
                        loadGraph();
                    } else {
                        document.getElementById('status').textContent = 'Edge not found';
                    }
                } catch (e) {
                    document.getElementById('status').textContent = 'Error deleting edge';
                }
            }
            
            setInterval(loadGraph, 2000);
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