#!/bin/bash
# 多阶段对话系统代码检查脚本（不依赖 Docker）

set -e

PROJECT_DIR="/Users/renjianqiu/projects/AIOperator"
cd "$PROJECT_DIR"

echo "=========================================="
echo "AIOperator 多阶段对话系统 - 代码检查"
echo "=========================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 1. 检查新增文件
echo "1. 检查新增的对话系统文件"
echo "----------------------------------------"

files=(
    "apps/ingress/conversation_state.py"
    "apps/ingress/requirement_clarifier.py"
    "apps/ingress/prd_reviewer.py"
    "apps/ingress/status_query.py"
    "apps/ingress/workflow_sync.py"
)

all_exist=true
for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        lines=$(wc -l < "$file")
        echo -e "${GREEN}✓${NC} $file (${lines} 行)"
    else
        echo -e "${RED}✗${NC} $file 不存在"
        all_exist=false
    fi
done

echo ""

# 2. 检查修改的文件
echo "2. 检查修改的核心文件"
echo "----------------------------------------"

modified_files=(
    "apps/ingress/session_manager.py"
    "apps/feishu_connector/main.py"
    "workflows/requirement.py"
)

for file in "${modified_files[@]}"; do
    if [ -f "$file" ]; then
        lines=$(wc -l < "$file")
        echo -e "${GREEN}✓${NC} $file (${lines} 行)"
    else
        echo -e "${RED}✗${NC} $file 不存在"
    fi
done

echo ""

# 3. 检查关键代码片段
echo "3. 检查关键代码集成"
echo "----------------------------------------"

# 检查 session_manager 是否导入 ConversationContext
if grep -q "from apps.ingress.conversation_state import ConversationContext" apps/ingress/session_manager.py; then
    echo -e "${GREEN}✓${NC} SessionManager 已集成 ConversationContext"
else
    echo -e "${RED}✗${NC} SessionManager 未集成 ConversationContext"
fi

# 检查 feishu_connector 是否导入新模块
if grep -q "from apps.ingress.requirement_clarifier import" apps/feishu_connector/main.py; then
    echo -e "${GREEN}✓${NC} feishu_connector 已导入 requirement_clarifier"
else
    echo -e "${RED}✗${NC} feishu_connector 未导入 requirement_clarifier"
fi

if grep -q "from apps.ingress.prd_reviewer import" apps/feishu_connector/main.py; then
    echo -e "${GREEN}✓${NC} feishu_connector 已导入 prd_reviewer"
else
    echo -e "${RED}✗${NC} feishu_connector 未导入 prd_reviewer"
fi

if grep -q "from apps.ingress.status_query import" apps/feishu_connector/main.py; then
    echo -e "${GREEN}✓${NC} feishu_connector 已导入 status_query"
else
    echo -e "${RED}✗${NC} feishu_connector 未导入 status_query"
fi

if grep -q "from apps.ingress.workflow_sync import" apps/feishu_connector/main.py; then
    echo -e "${GREEN}✓${NC} feishu_connector 已导入 workflow_sync"
else
    echo -e "${RED}✗${NC} feishu_connector 未导入 workflow_sync"
fi

# 检查阶段处理逻辑
if grep -q "ConversationPhase.REQUIREMENT_CLARIFYING" apps/feishu_connector/main.py; then
    echo -e "${GREEN}✓${NC} feishu_connector 已实现需求澄清阶段处理"
else
    echo -e "${RED}✗${NC} feishu_connector 未实现需求澄清阶段处理"
fi

if grep -q "ConversationPhase.PRD_REVIEW" apps/feishu_connector/main.py; then
    echo -e "${GREEN}✓${NC} feishu_connector 已实现 PRD 审查阶段处理"
else
    echo -e "${RED}✗${NC} feishu_connector 未实现 PRD 审查阶段处理"
fi

# 检查 workflow 是否添加通知
if grep -q "notify_websocket" workflows/requirement.py; then
    echo -e "${GREEN}✓${NC} workflow 已添加 WebSocket 通知"
else
    echo -e "${YELLOW}⚠${NC} workflow 未添加 WebSocket 通知"
fi

echo ""

# 4. 检查会话状态机定义
echo "4. 检查会话状态机定义"
echo "----------------------------------------"

phases=(
    "IDLE"
    "REQUIREMENT_CLARIFYING"
    "REQUIREMENT_CONFIRMED"
    "PRD_REVIEW"
    "DESIGN_DISCUSSION"
    "IMPLEMENTATION"
    "CODE_REVIEW"
)

for phase in "${phases[@]}"; do
    if grep -q "$phase" apps/ingress/conversation_state.py; then
        echo -e "${GREEN}✓${NC} $phase"
    else
        echo -e "${RED}✗${NC} $phase 未定义"
    fi
done

echo ""

# 5. 代码质量检查
echo "5. 代码质量检查"
echo "----------------------------------------"

# 检查是否有语法错误（简单检查）
echo "检查 Python 语法..."

syntax_errors=0
for file in "${files[@]}" "${modified_files[@]}"; do
    if [ -f "$file" ]; then
        if python3 -m py_compile "$file" 2>/dev/null; then
            echo -e "${GREEN}✓${NC} $(basename $file) 语法正确"
        else
            echo -e "${RED}✗${NC} $(basename $file) 语法错误"
            syntax_errors=$((syntax_errors + 1))
        fi
    fi
done

echo ""

# 6. 统计信息
echo "6. 代码统计"
echo "----------------------------------------"

total_lines=0
for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        lines=$(wc -l < "$file")
        total_lines=$((total_lines + lines))
    fi
done

echo "新增代码总行数: $total_lines"
echo ""

echo "各模块行数："
for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        lines=$(wc -l < "$file")
        printf "  %-40s %5d 行\n" "$(basename $file)" "$lines"
    fi
done

echo ""

# 7. 文档检查
echo "7. 文档检查"
echo "----------------------------------------"

docs=(
    "docs/VERIFICATION_GUIDE.md"
    "docs/TEST_CHECKLIST.md"
)

for doc in "${docs[@]}"; do
    if [ -f "$doc" ]; then
        lines=$(wc -l < "$doc")
        echo -e "${GREEN}✓${NC} $doc (${lines} 行)"
    else
        echo -e "${RED}✗${NC} $doc 不存在"
    fi
done

echo ""

# 8. Git 状态
echo "8. Git 状态"
echo "----------------------------------------"

if git status &>/dev/null; then
    echo "未提交的更改："
    git status --short | head -10

    echo ""
    echo "新增文件数: $(git status --short | grep '^??' | wc -l)"
    echo "修改文件数: $(git status --short | grep '^ M' | wc -l)"
else
    echo -e "${YELLOW}⚠${NC} 不在 Git 仓库中"
fi

echo ""

# 9. 依赖检查
echo "9. 依赖检查"
echo "----------------------------------------"

if [ -f "pyproject.toml" ]; then
    echo -e "${GREEN}✓${NC} pyproject.toml 存在"

    # 检查关键依赖
    if grep -q "anthropic" pyproject.toml; then
        echo -e "${GREEN}✓${NC} anthropic 依赖已配置"
    else
        echo -e "${RED}✗${NC} anthropic 依赖未配置"
    fi

    if grep -q "temporalio" pyproject.toml; then
        echo -e "${GREEN}✓${NC} temporalio 依赖已配置"
    else
        echo -e "${RED}✗${NC} temporalio 依赖未配置"
    fi
else
    echo -e "${RED}✗${NC} pyproject.toml 不存在"
fi

echo ""

# 10. 总结
echo "=========================================="
echo "检查总结"
echo "=========================================="
echo ""

if [ "$all_exist" = true ] && [ "$syntax_errors" -eq 0 ]; then
    echo -e "${GREEN}✓ 代码检查通过${NC}"
    echo ""
    echo "下一步："
    echo "1. 查看测试清单: cat docs/TEST_CHECKLIST.md"
    echo "2. 查看验证指南: cat docs/VERIFICATION_GUIDE.md"
    echo "3. 启动服务进行实际测试"
    echo ""
    echo -e "${BLUE}启动命令（需要 Docker）：${NC}"
    echo "  cd deploy"
    echo "  docker compose --env-file ../.env.cloud up -d"
    echo ""
    exit 0
else
    echo -e "${RED}✗ 发现问题，请检查上述错误${NC}"
    exit 1
fi
