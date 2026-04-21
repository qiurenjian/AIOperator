#!/bin/bash
# 多阶段对话系统快速检查脚本

set -e

DEPLOY_DIR="/Users/renjianqiu/projects/AIOperator/deploy"
cd "$DEPLOY_DIR"

echo "=========================================="
echo "AIOperator 多阶段对话系统 - 状态检查"
echo "=========================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查函数
check_service() {
    local service=$1
    local status=$(docker compose ps --format json | jq -r ".[] | select(.Service==\"$service\") | .State")

    if [ "$status" == "running" ]; then
        echo -e "${GREEN}✓${NC} $service: running"
        return 0
    else
        echo -e "${RED}✗${NC} $service: $status"
        return 1
    fi
}

check_healthy() {
    local service=$1
    local health=$(docker compose ps --format json | jq -r ".[] | select(.Service==\"$service\") | .Health")

    if [ "$health" == "healthy" ]; then
        echo -e "${GREEN}✓${NC} $service: healthy"
        return 0
    else
        echo -e "${YELLOW}⚠${NC} $service: $health"
        return 1
    fi
}

# 1. 检查 Docker Compose
echo "1. 检查 Docker Compose 服务状态"
echo "----------------------------------------"

if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗${NC} Docker 未安装或不可用"
    exit 1
fi

services=("postgres" "temporal" "temporal-ui" "ingress" "worker-cloud" "feishu-connector")
all_running=true

for service in "${services[@]}"; do
    if ! check_service "$service"; then
        all_running=false
    fi
done

echo ""

# 2. 检查健康状态
echo "2. 检查服务健康状态"
echo "----------------------------------------"

check_healthy "postgres" || true
check_healthy "temporal" || true

echo ""

# 3. 检查关键日志
echo "3. 检查关键日志"
echo "----------------------------------------"

echo "feishu-connector 启动状态："
if docker compose logs feishu-connector | grep -q "feishu connector started"; then
    echo -e "${GREEN}✓${NC} feishu-connector 已启动"
else
    echo -e "${RED}✗${NC} feishu-connector 未正常启动"
fi

echo ""
echo "worker-cloud 启动状态："
if docker compose logs worker-cloud | grep -q "worker started"; then
    echo -e "${GREEN}✓${NC} worker-cloud 已启动"
else
    echo -e "${RED}✗${NC} worker-cloud 未正常启动"
fi

echo ""

# 4. 检查最近错误
echo "4. 检查最近错误（最近 50 行）"
echo "----------------------------------------"

error_count=$(docker compose logs --tail=50 | grep -i error | wc -l)
if [ "$error_count" -eq 0 ]; then
    echo -e "${GREEN}✓${NC} 没有发现错误"
else
    echo -e "${YELLOW}⚠${NC} 发现 $error_count 条错误日志"
    echo ""
    echo "最近的错误："
    docker compose logs --tail=50 | grep -i error | tail -5
fi

echo ""

# 5. 检查 Temporal UI
echo "5. 检查 Temporal UI"
echo "----------------------------------------"

if curl -s http://localhost:8088 > /dev/null; then
    echo -e "${GREEN}✓${NC} Temporal UI 可访问: http://localhost:8088"
else
    echo -e "${RED}✗${NC} Temporal UI 不可访问"
fi

echo ""

# 6. 检查新增文件
echo "6. 检查新增的对话系统文件"
echo "----------------------------------------"

files=(
    "../apps/ingress/conversation_state.py"
    "../apps/ingress/requirement_clarifier.py"
    "../apps/ingress/prd_reviewer.py"
    "../apps/ingress/status_query.py"
    "../apps/ingress/workflow_sync.py"
)

for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo -e "${GREEN}✓${NC} $(basename $file)"
    else
        echo -e "${RED}✗${NC} $(basename $file) 不存在"
    fi
done

echo ""

# 7. 统计信息
echo "7. 系统统计"
echo "----------------------------------------"

echo "会话管理器文件大小："
ls -lh ../apps/ingress/session_manager.py | awk '{print $5, $9}'

echo ""
echo "最近 10 条 feishu-connector 日志："
docker compose logs --tail=10 feishu-connector | grep -E "(INFO|ERROR|WARNING)" | tail -5

echo ""

# 8. 快速测试建议
echo "=========================================="
echo "快速测试建议"
echo "=========================================="
echo ""
echo "1. 在飞书发送消息测试意图分类："
echo "   \"我想加个运动记录功能\""
echo ""
echo "2. 查看实时日志："
echo "   docker compose logs -f feishu-connector"
echo ""
echo "3. 查看 Temporal UI："
echo "   http://localhost:8088"
echo ""
echo "4. 查看完整验证指南："
echo "   cat ../docs/VERIFICATION_GUIDE.md"
echo ""

if [ "$all_running" = true ]; then
    echo -e "${GREEN}✓ 所有服务运行正常，可以开始测试${NC}"
    exit 0
else
    echo -e "${RED}✗ 部分服务未运行，请先启动服务${NC}"
    echo ""
    echo "启动命令："
    echo "  cd $DEPLOY_DIR"
    echo "  docker compose --env-file ../.env.cloud up -d"
    exit 1
fi
