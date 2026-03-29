# SSTG Navigation Planner - 使用指南

## 📖 概述

SSTG Navigation Planner 是一个智能导航规划模块，能够：
- 将自然语言查询（如"带我去客厅"）转换为导航目标
- 通过语义匹配在拓扑图中寻找目标位置
- 计算多维度相关度评分（语义、距离、可达性）
- 使用 Dijkstra 算法规划最短路径
- 生成详细的导航步骤和执行计划

## 🚀 快速开始

### 方式1：ROS2 节点启动

```bash
source /opt/ros/humble/setup.bash
ros2 run sstg_navigation_planner planning_node
```

### 方式2：Python 直接使用

```python
from sstg_navigation_planner import SemanticMatcher, CandidateGenerator, NavigationPlanner

# 初始化组件
matcher = SemanticMatcher()
generator = CandidateGenerator()
planner = NavigationPlanner()

# 拓扑图
nodes = {
    0: {'name': '客厅', 'room_type': 'living_room', 'pose': {...}},
    1: {'name': '卧室', 'room_type': 'bedroom', 'pose': {...}}
}

# 执行规划
matches = matcher.match_query_to_nodes(
    intent='navigate_to',
    entities=['客厅'],
    confidence=0.9,
    topological_nodes=nodes
)

candidates = generator.generate_candidates(matches, nodes)
plan = planner.plan_navigation(candidates, nodes)
```

## 🏗️ 架构

### 核心组件

#### 1. SemanticMatcher（语义匹配器）
- **功能**：将查询意图与拓扑图节点进行语义匹配
- **输入**：意图、实体、置信度、拓扑图
- **输出**：MatchResult 列表

**关键方法：**
```python
def match_query_to_nodes(intent, entities, confidence, topological_nodes)
    -> List[MatchResult]
```

**支持的意图：**
- `navigate_to`：导航到某个位置
- `locate_object`：定位某个物体
- `query_info`：查询信息
- `ask_direction`：询问方向

**示例代码：**
```python
matcher = SemanticMatcher()
matches = matcher.match_query_to_nodes(
    intent='navigate_to',
    entities=['客厅'],
    confidence=0.95,
    topological_nodes=topological_map
)

for match in matches:
    print(f"Node {match.node_id}: {match.node_name} - Score: {match.match_score}")
```

#### 2. CandidateGenerator（候选点生成器）
- **功能**：从匹配结果生成评分的候选点
- **输入**：匹配结果、拓扑图、当前位置
- **输出**：CandidatePoint 列表

**多维度评分：**
- 语义匹配得分（50%）
- 距离得分（30%）
- 可达性得分（20%）

**示例代码：**
```python
generator = CandidateGenerator(max_candidates=5)
candidates = generator.generate_candidates(
    match_results=matches,
    topological_nodes=topological_map,
    current_pose=(0.0, 0.0, 0.0)
)

# 获取最优候选
best_candidate = generator.get_top_candidate(candidates)
```

#### 3. NavigationPlanner（导航规划器）
- **功能**：从候选点生成导航计划和路径
- **输入**：候选点、拓扑图、当前位置
- **输出**：NavigationPlanResult

**算法：**
- 使用 Dijkstra 算法计算最短路径
- 生成详细的导航步骤
- 估计导航时间

**示例代码：**
```python
planner = NavigationPlanner()
plan = planner.plan_navigation(
    candidates=candidates,
    topological_nodes=topological_map,
    current_node_id=0
)

print(f"路径: {plan.path}")
print(f"距离: {plan.total_distance}m")
print(f"预计时间: {plan.estimated_time}s")

for step in plan.steps:
    print(f"步骤 {step.step_id}: {step.description}")
```

## 🔧 ROS2 服务

### PlanNavigation 服务

接收导航查询并返回规划结果。

**请求：**
```
string intent              # 意图类型
string entities           # JSON 格式的实体列表
float32 confidence        # 置信度
int32 current_node        # 当前所在节点 ID
```

**响应：**
```
bool success              # 规划是否成功
int32[] candidate_node_ids  # 候选节点 ID 列表
string reasoning          # 规划理由
string plan_json         # 完整规划 JSON
```

**调用示例：**
```bash
ros2 service call /plan_navigation sstg_msgs/srv/PlanNavigation \
  '{intent: "navigate_to", entities: "[\"客厅\"]", confidence: 0.95, current_node: 0}'
```

### navigation_plans 话题

发布规划结果。

**消息类型：** `sstg_msgs/NavigationPlan`

**监听示例：**
```bash
ros2 topic echo /navigation_plans
```

## ⚙️ 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_candidates` | 5 | 最多返回的候选点数 |
| `min_match_score` | 0.3 | 最小匹配得分阈值 |
| `map_service_name` | `/manage_map` | 地图管理服务名称 |

**配置方式：**
```bash
ros2 run sstg_navigation_planner planning_node \
  --ros-args \
  -p max_candidates:=10 \
  -p min_match_score:=0.5
```

## 📊 数据结构

### MatchResult（匹配结果）
```python
@dataclass
class MatchResult:
    node_id: int              # 节点 ID
    node_name: str            # 节点名称
    room_type: str            # 房间类型
    semantic_tags: List[str]  # 语义标签
    match_score: float        # 匹配得分 (0.0-1.0)
    match_reason: str         # 匹配原因
```

### CandidatePoint（候选点）
```python
@dataclass
class CandidatePoint:
    node_id: int              # 节点 ID
    node_name: str            # 节点名称
    pose_x/y/z: float         # 位置坐标
    room_type: str            # 房间类型
    relevance_score: float    # 综合相关度得分
    semantic_score: float     # 语义匹配得分
    distance_score: float     # 距离得分
    accessibility_score: float  # 可达性得分
    match_reason: str         # 匹配原因
```

### NavigationPlanResult（规划结果）
```python
@dataclass
class NavigationPlanResult:
    plan_id: str              # 规划 ID
    start_node_id: int        # 起始节点
    goal_node_id: int         # 目标节点
    path: List[int]           # 路径上的节点列表
    steps: List[NavigationStep]  # 导航步骤
    total_distance: float     # 路径总距离 (m)
    estimated_time: float     # 估计时间 (s)
    success: bool             # 规划是否成功
    reasoning: str            # 规划理由
```

## 🧪 测试

运行模块测试：

```bash
cd ~/sstg_nav/sstg_nav_ws/src/sstg_navigation_planner
python3 test/test_navigation_planner.py
```

预期结果：**4/4 tests PASSED** ✅

## 🐛 故障排除

### 1. 语义匹配失败
**症状：** 无法找到匹配的位置
**解决方案：**
- 检查实体名称是否与拓扑图中的节点名称对应
- 调整 `min_match_score` 参数降低阈值
- 确保拓扑图已正确初始化

### 2. 路径规划失败
**症状：** 两个节点之间无法规划路径
**解决方案：**
- 验证拓扑图的连接性（是否有孤立节点）
- 检查当前节点是否有效
- 确保目标节点在拓扑图中

### 3. 性能问题
**症状：** 规划耗时过长
**解决方案：**
- 减少 `max_candidates` 参数
- 使用启发式算法（A* 而不是 Dijkstra）
- 优化拓扑图结构（减少边数）

## 📝 开发者注意事项

### 添加新的意图类型

1. 更新 `SemanticMatcher.INTENT_TO_ROOM_MAPPING`
2. 添加对应的匹配逻辑到 `_generate_candidates()`
3. 更新文档和测试

### 自定义匹配算法

```python
class CustomMatcher(SemanticMatcher):
    def _calculate_match_score(self, intent, entity, node_info, query_confidence):
        # 自定义得分计算逻辑
        return custom_score
```

### 性能优化

- 预计算节点间的距离矩阵
- 使用缓存存储常用查询结果
- 实现基于位置的过滤（只考虑附近节点）

## 🔗 依赖关系

- rclpy (ROS2 Python 库)
- sstg_msgs (消息定义)
- sstg_map_manager (拓扑图管理)

## 📚 相关文档

- [NLP Interface](../sstg_nlp_interface/doc/MODULE_GUIDE.md) - 自然语言理解
- [Map Manager](../sstg_map_manager/MODULE_GUIDE.md) - 拓扑图管理
- [Navigation Executor](../sstg_navigation_executor/doc/MODULE_GUIDE.md) - 导航执行（待开发）
