#!/usr/bin/env bash
#
# 一键启动前后端开发服务。
#
#   ./dev.sh                 同时启动 FastAPI 与 Vite
#   ./dev.sh --no-install    跳过依赖检查，直接启动
#   ./dev.sh --help          查看说明
#
# 按 Ctrl+C 会同时关闭两个服务。

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

NODE_VERSION="$(tr -d '[:space:]' < "$ROOT_DIR/.nvmrc" 2>/dev/null || true)"
[ -n "$NODE_VERSION" ] || NODE_VERSION="22"

# ---------- 输出样式 ----------
if [ -t 1 ]; then
  C_RESET=$'\033[0m'
  C_DIM=$'\033[2m'
  C_OK=$'\033[32m'
  C_WARN=$'\033[33m'
  C_ERR=$'\033[31m'
  C_API=$'\033[36m'
  C_WEB=$'\033[35m'
else
  C_RESET=""; C_DIM=""; C_OK=""; C_WARN=""; C_ERR=""; C_API=""; C_WEB=""
fi

log()  { printf '%s%s%s\n' "$C_DIM" "$*" "$C_RESET"; }
ok()   { printf '%s✓%s %s\n' "$C_OK" "$C_RESET" "$*"; }
warn() { printf '%s!%s %s\n' "$C_WARN" "$C_RESET" "$*"; }
die()  { printf '%s✗ %s%s\n' "$C_ERR" "$*" "$C_RESET" >&2; exit 1; }

usage() {
  cat <<'EOF'
用法: ./dev.sh [选项]

同时启动后端 FastAPI 与前端 Vite 开发服务，Ctrl+C 一并关闭。

选项:
  -h, --help        显示本帮助
      --no-install  跳过依赖检查与安装，直接启动

环境变量:
  BACKEND_HOST   后端监听地址（默认 127.0.0.1，改成 0.0.0.0 可供局域网访问）
  BACKEND_PORT   后端端口（默认 8000）
  FRONTEND_PORT  前端端口（默认 5173）

说明:
  启动前会检查两个端口。如果被上次遗留的本项目进程占着，会自动清理后继续；
  如果是别的程序占用，会直接提示，不会起一半再关掉。
EOF
}

# ---------- 参数 ----------
SKIP_INSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --no-install) SKIP_INSTALL=1; shift ;;
    *) die "未知参数: ${1}（用 --help 查看用法）" ;;
  esac
done

# ---------- 日志前缀 ----------
prefix_stream() {
  local label="$1" color="$2" line
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    printf '%s[%-3s]%s %s\n' "$color" "$label" "$C_RESET" "$line"
  done
}

# ---------- 进程清理 ----------
PIDS=()

kill_tree() {
  local pid="$1" sig="${2:-TERM}" child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    kill_tree "$child" "$sig"
  done
  kill -"$sig" "$pid" 2>/dev/null || true
}

# 先发 SIGTERM 让服务优雅退出；有些进程（尤其是被孤儿化的旧进程）会忽略它，
# 所以隔几秒还没走就补 SIGKILL，否则端口会一直被占着。
terminate() {
  local pids="$1" pid i alive

  for pid in $pids; do
    kill_tree "$pid" TERM
  done

  for i in 1 2 3; do
    sleep 1
    alive=0
    for pid in $pids; do
      kill -0 "$pid" 2>/dev/null && alive=1
    done
    [ "$alive" -eq 0 ] && return 0
  done

  for pid in $pids; do
    kill -0 "$pid" 2>/dev/null && kill_tree "$pid" KILL
  done
  sleep 1
  return 0
}

cleanup() {
  local code=$?
  trap - EXIT INT TERM HUP
  printf '\n'
  log "正在关闭服务…"
  terminate "${PIDS[*]:-}"
  wait 2>/dev/null || true
  ok "已全部关闭"
  exit "$code"
}
trap cleanup EXIT INT TERM HUP

# ---------- 端口预检 ----------
# 上次的进程如果没被正常收尾（比如直接关掉终端窗口），会继续占着端口，
# 导致这次后端起不来。这里先认领并清理掉自己留下的进程。

port_owner() {
  command -v lsof >/dev/null 2>&1 || return 0
  lsof -tnP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | head -1
}

pid_command() {
  ps -o command= -p "$1" 2>/dev/null | sed 's/^[[:space:]]*//'
}

is_project_dev_proc() {
  case "$1" in
    *uvicorn*app.main:app*) return 0 ;;
    *"$FRONTEND_DIR/node_modules/"*vite*) return 0 ;;
    *) return 1 ;;
  esac
}

# 绝不误伤：init、本脚本自身、拉起本脚本的那个 shell
is_protected_pid() {
  case "$1" in
    ""|1|"$$"|"$PPID") return 0 ;;
    *) return 1 ;;
  esac
}

check_port() {
  local port="$1" label="$2" var="$3" pid parent cmd i

  pid="$(port_owner "$port")"
  [ -z "$pid" ] && return 0

  cmd="$(pid_command "$pid")"
  if ! is_project_dev_proc "$cmd"; then
    die "端口 ${port} 被别的程序占用了（pid ${pid}）：
  $cmd
  先关掉它，或者换端口再跑：${var}=9099 ./dev.sh"
  fi

  warn "端口 ${port} 上有上次遗留的${label}进程（pid ${pid}），先清理掉"

  # 顺着父进程往上找：uvicorn 的进程链是
  # `uv run` → reloader → server(占端口)，只收 server 会留下孤儿
  local targets="$pid" depth=0
  parent="$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')"
  while [ "$depth" -lt 3 ] && ! is_protected_pid "$parent" && is_project_dev_proc "$(pid_command "$parent")"; do
    targets="$targets $parent"
    parent="$(ps -o ppid= -p "$parent" 2>/dev/null | tr -d ' ')"
    depth=$((depth + 1))
  done

  terminate "$targets"

  for i in 1 2 3 4 5; do
    [ -z "$(port_owner "$port")" ] && return 0
    sleep 1
  done
  die "端口 ${port} 仍然被占用，请手动处理：lsof -nP -iTCP:${port} -sTCP:LISTEN"
}

# ---------- 1. 检查 uv ----------
command -v uv >/dev/null 2>&1 || die "找不到 uv，请先安装：https://docs.astral.sh/uv/getting-started/installation/"
ok "uv $(uv --version 2>/dev/null | awk '{print $2}')"

# ---------- 2. 切到 Node 22 ----------
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
if [ -s "$NVM_DIR/nvm.sh" ]; then
  # shellcheck disable=SC1090,SC1091
  . "$NVM_DIR/nvm.sh" >/dev/null 2>&1 || true
fi
command -v nvm >/dev/null 2>&1 || die "找不到 nvm，请先安装：https://github.com/nvm-sh/nvm"

if ! nvm use "$NODE_VERSION" >/dev/null 2>&1; then
  warn "本地没有 Node ${NODE_VERSION}，正在安装…"
  nvm install "$NODE_VERSION" >/dev/null 2>&1 || die "安装 Node $NODE_VERSION 失败"
  nvm use "$NODE_VERSION" >/dev/null 2>&1 || die "切换到 Node $NODE_VERSION 失败"
fi

NODE_MAJOR="$(node -v | sed 's/^v//' | cut -d. -f1)"
[ "$NODE_MAJOR" -ge 22 ] || die "当前 Node 为 $(node -v)，低于要求的 22.x"
ok "Node $(node -v) / npm $(npm -v)"

# ---------- 3. 依赖 ----------
if [ "$SKIP_INSTALL" -eq 0 ]; then
  if [ ! -x "$BACKEND_DIR/.venv/bin/python" ]; then
    log "后端依赖未安装，执行 uv sync…"
    (cd "$BACKEND_DIR" && uv sync) || die "uv sync 失败"
  fi
  if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    log "前端依赖未安装，执行 npm install…"
    (cd "$FRONTEND_DIR" && npm install) || die "npm install 失败"
  fi
fi

# ---------- 4. 环境变量 ----------
if [ ! -f "$BACKEND_DIR/.env" ]; then
  cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
  warn "已由 .env.example 生成 backend/.env，记得填入 DEEPSEEK_API_KEY"
fi
if ! grep -qE '^DEEPSEEK_API_KEY=.+' "$BACKEND_DIR/.env" 2>/dev/null; then
  warn "backend/.env 中的 DEEPSEEK_API_KEY 为空，对话接口会返回 503（向量接口不受影响）"
fi

# ---------- 5. 端口预检 ----------
check_port "$BACKEND_PORT" "后端" "BACKEND_PORT"
check_port "$FRONTEND_PORT" "前端" "FRONTEND_PORT"

# ---------- 6. 启动 ----------
log "启动后端  http://${BACKEND_HOST}:${BACKEND_PORT}/docs"
(cd "$BACKEND_DIR" && exec uv run uvicorn app.main:app \
  --reload --host "$BACKEND_HOST" --port "$BACKEND_PORT") \
  > >(prefix_stream api "$C_API") 2>&1 &
PIDS+=("$!")

log "启动前端  http://localhost:${FRONTEND_PORT}"
(cd "$FRONTEND_DIR" && exec npm run dev -- --port "$FRONTEND_PORT" --strictPort) \
  > >(prefix_stream web "$C_WEB") 2>&1 &
PIDS+=("$!")

ok "服务已启动，按 Ctrl+C 停止"

# 任一服务退出后收尾关闭另一个（兼容 bash 3.2，不使用 wait -n）
while kill -0 "${PIDS[0]}" 2>/dev/null && kill -0 "${PIDS[1]}" 2>/dev/null; do
  sleep 1
done

if kill -0 "${PIDS[0]}" 2>/dev/null; then
  warn "前端已退出，正在关闭后端"
else
  warn "后端已退出，正在关闭前端（上面的 [api] 日志里有原因）"
fi
