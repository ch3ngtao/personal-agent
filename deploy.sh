#!/usr/bin/env bash
#
# 一键部署：把本地代码传到服务器，在服务器上构建镜像、重启容器并做健康检查。
#
#   ./deploy.sh --init        首次部署（建目录、生成 .env、构建、启动）
#   ./deploy.sh               日常更新（传代码 + 重新构建 + 重启）
#   ./deploy.sh --no-build    只传文件并重启容器，不重建镜像（例如只换了简历 PDF）
#   ./deploy.sh --restart     不传代码，只重启容器
#   ./deploy.sh --detach      上传后在服务器后台构建，关掉终端也不会中断
#   ./deploy.sh --build-log   查看后台构建的进度
#   ./deploy.sh --status      查看容器状态与健康检查
#   ./deploy.sh --logs [服务] 实时查看日志（api / web，默认全部）
#   ./deploy.sh --help        查看说明
#
# 服务器上有两个环境，用 --env 选（对应 deploy.<名字>.conf）：
#   ./deploy.sh --env hr --init        自己的（ch3ngtao.top），简历在服务器上传
#   ./deploy.sh --env public --init    对外给外人看的（lisi.ch3ngtao.top），用仓库里的简历
#   ./deploy.sh --env hr --upload-resume   把自己的简历 PDF 传到服务器（不进 git、不随代码上传）
#
# 服务器信息写在 deploy.conf（可参考 deploy.conf.example），
# 也可以用同名环境变量临时覆盖，例如：
#   DEPLOY_SSH=ubuntu@1.2.3.4 ./deploy.sh

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------- 先看有没有 --env：它决定读哪个配置文件 ----------
_args=("$@")
DEPLOY_ENV=""
_i=0
while [ "$_i" -lt "${#_args[@]}" ]; do
  if [ "${_args[$_i]}" = "--env" ]; then
    DEPLOY_ENV="${_args[$((_i + 1))]:-}"
  fi
  _i=$((_i + 1))
done

if [ -n "$DEPLOY_ENV" ]; then
  CONF_FILE="$ROOT_DIR/deploy.$DEPLOY_ENV.conf"
  if [ ! -f "$CONF_FILE" ]; then
    printf '✗ 找不到 %s\n' "$CONF_FILE" >&2
    printf '  可用的环境配置：%s\n' "$(cd "$ROOT_DIR" && ls deploy.*.conf 2>/dev/null | tr '\n' ' ')" >&2
    exit 1
  fi
else
  CONF_FILE="$ROOT_DIR/deploy.conf"
fi

# ---------- 配置（环境变量 → deploy.conf → 内置默认）----------
# 先记下环境变量里显式传入的值，读完 deploy.conf 再盖回去（环境变量优先级最高）
ENV_DEPLOY_SSH="${DEPLOY_SSH:-}"
ENV_DEPLOY_PORT="${DEPLOY_PORT:-}"
ENV_DEPLOY_DIR="${DEPLOY_DIR:-}"
ENV_DEPLOY_KEY="${DEPLOY_KEY:-}"
ENV_DEPLOY_SERVICES="${DEPLOY_SERVICES:-}"
ENV_DEPLOY_WEB_PORT="${DEPLOY_WEB_PORT:-}"
ENV_DEPLOY_API_PORT="${DEPLOY_API_PORT:-}"
ENV_DEPLOY_HF_ENDPOINT="${DEPLOY_HF_ENDPOINT:-}"
ENV_DEPLOY_ENV_FILE="${DEPLOY_ENV_FILE:-}"
ENV_DEPLOY_SITE_URL="${DEPLOY_SITE_URL:-}"
ENV_DEPLOY_RESUME_FILE="${DEPLOY_RESUME_FILE:-}"

if [ -f "$CONF_FILE" ]; then
  # shellcheck disable=SC1090
  . "$CONF_FILE"
fi

[ -n "$ENV_DEPLOY_SSH" ] && DEPLOY_SSH="$ENV_DEPLOY_SSH"
[ -n "$ENV_DEPLOY_PORT" ] && DEPLOY_PORT="$ENV_DEPLOY_PORT"
[ -n "$ENV_DEPLOY_DIR" ] && DEPLOY_DIR="$ENV_DEPLOY_DIR"
[ -n "$ENV_DEPLOY_KEY" ] && DEPLOY_KEY="$ENV_DEPLOY_KEY"
[ -n "$ENV_DEPLOY_SERVICES" ] && DEPLOY_SERVICES="$ENV_DEPLOY_SERVICES"
[ -n "$ENV_DEPLOY_WEB_PORT" ] && DEPLOY_WEB_PORT="$ENV_DEPLOY_WEB_PORT"
[ -n "$ENV_DEPLOY_API_PORT" ] && DEPLOY_API_PORT="$ENV_DEPLOY_API_PORT"
[ -n "$ENV_DEPLOY_HF_ENDPOINT" ] && DEPLOY_HF_ENDPOINT="$ENV_DEPLOY_HF_ENDPOINT"
[ -n "$ENV_DEPLOY_ENV_FILE" ] && DEPLOY_ENV_FILE="$ENV_DEPLOY_ENV_FILE"
[ -n "$ENV_DEPLOY_SITE_URL" ] && DEPLOY_SITE_URL="$ENV_DEPLOY_SITE_URL"
[ -n "$ENV_DEPLOY_RESUME_FILE" ] && DEPLOY_RESUME_FILE="$ENV_DEPLOY_RESUME_FILE"

DEPLOY_PORT="${DEPLOY_PORT:-22}"
DEPLOY_DIR="${DEPLOY_DIR:-~/ch3ngtao-web}"
DEPLOY_WEB_PORT="${DEPLOY_WEB_PORT:-5173}"
DEPLOY_API_PORT="${DEPLOY_API_PORT:-8000}"
DEPLOY_ENV_FILE="${DEPLOY_ENV_FILE:-}"
DEPLOY_SITE_URL="${DEPLOY_SITE_URL:-}"
DEPLOY_RESUME_FILE="${DEPLOY_RESUME_FILE:-}"
# 两个环境共用一张 docker 网络：入口环境的 nginx 通过它转发到对外环境
DEPLOY_EDGE_NETWORK="${DEPLOY_EDGE_NETWORK:-ch3ngtao-edge}"

# 允许写 ~ 或 $HOME：统一交给远程 shell 展开（本地展开会指到 Mac 的家目录）
LOCAL_HOME="$HOME"
DEPLOY_DIR="${DEPLOY_DIR/#\~/\$HOME}"
case "$DEPLOY_DIR" in
  "$LOCAL_HOME"/*) DEPLOY_DIR="\$HOME${DEPLOY_DIR#"$LOCAL_HOME"}" ;;
esac

REMOTE_COMPOSE=""
PREFLIGHT_DONE=0

# SSH 连接复用：同一次部署里的多次 ssh 复用一条连接，密码只需要输一遍。
# 最后一条用完后连接还会保持 30 秒，闲置到期自动断开。
SSH_COMMON_OPTS="-o ConnectTimeout=15 -o ControlMaster=auto -o ControlPath=/tmp/ch3ngtao-deploy-%C -o ControlPersist=30"

# ---------- 输出样式 ----------
if [ -t 1 ]; then
  C_RESET=$'\033[0m'
  C_DIM=$'\033[2m'
  C_OK=$'\033[32m'
  C_WARN=$'\033[33m'
  C_ERR=$'\033[31m'
else
  C_RESET=""; C_DIM=""; C_OK=""; C_WARN=""; C_ERR=""
fi

log()  { printf '%s%s%s\n' "$C_DIM" "$*" "$C_RESET"; }
ok()   { printf '%s✓%s %s\n' "$C_OK" "$C_RESET" "$*"; }
warn() { printf '%s!%s %s\n' "$C_WARN" "$C_RESET" "$*"; }
die()  { printf '%s✗ %s%s\n' "$C_ERR" "$*" "$C_RESET" >&2; exit 1; }

usage() {
  cat <<'EOF'
用法: ./deploy.sh [选项]

把本地代码推到服务器，在服务器上用 docker compose 重新构建并启动容器。

选项:
  -h, --help        显示本帮助
      --env <名字>  选服务器上的哪个环境，对应 deploy.<名字>.conf
      --init        首次部署：创建远程目录、生成/补齐 .env（从本地 backend/.env 取 Key），
                    然后构建并启动。可重复执行，用来把新配置同步到服务器
      --no-build    只上传文件并重启容器，不重建镜像。源码/依赖改了不会生效，
                    适用于「代码没变，只换了被挂载的文件」（如简历 PDF）
      --restart     不上传代码，只重启容器（改了 .env 时用这个）
      --force-env   同步 .env 时，用本地的值覆盖服务器上已有的同名配置
                    （默认只补缺失的键，不动已有值）
      --detach      上传后在服务器后台构建并启动，日志写到服务器上的 build.log。
                    首次构建很慢时用它，SSH 断了也不会把构建杀掉
      --build-log   跟随后台构建的日志（Ctrl+C 退出，不影响构建）
      --status      只查看容器状态与健康检查
      --logs [服务] 实时查看日志，服务可选 api 或 web，默认全部
      --only <服务> 只重建并重启指定服务（web 或 api），另一个保持不动
      --host <值>   临时指定服务器，如 ubuntu@1.2.3.4 或 ssh 别名
      --dir <路径>  临时指定服务器上的部署目录
      --upload-resume [文件]
                    把自己的简历 PDF 上传到服务器（默认取本地仓库根目录的
                    RESUME_FILE）。这份简历不进 git，也不会随代码上传
      --resume <文件> 指定简历文件名或绝对路径，配合 --upload-resume 使用
                    （服务器上会存成同名文件；和服务器 .env 的 RESUME_FILE
                     不一致时会提醒你改哪里）

配置文件:
  --env hr 读 deploy.hr.conf，--env public 读 deploy.public.conf，不带 --env 读 deploy.conf。
  这些文件都不会被提交，也不会被上传，可覆盖以下变量：
    DEPLOY_SSH        服务器地址，user@host 或 ~/.ssh/config 里的别名
    DEPLOY_PORT       SSH 端口，默认 22
    DEPLOY_DIR        部署目录，默认 ~/ch3ngtao-web
    DEPLOY_KEY        私钥路径，走密码登录就留空
    DEPLOY_SERVICES   只重建某个服务时填 web 或 api，留空表示两个都重建
    DEPLOY_WEB_PORT   网页端口，默认 5173（健康检查用）
    DEPLOY_API_PORT   接口端口，默认 8000（健康检查用）
    DEPLOY_HF_ENDPOINT 模型权重下载地址，国内填 https://hf-mirror.com
    DEPLOY_ENV_FILE   该环境的环境变量文件（如 env/hr.env），会上传到服务器成为 .env
    DEPLOY_SITE_URL   部署完提示的访问地址，如 https://ch3ngtao.top
    DEPLOY_RESUME_FILE 该环境用的简历文件名（默认取服务器 .env 里的 RESUME_FILE）
    DEPLOY_EDGE_NETWORK 两个环境共用的 docker 网络名，默认 ch3ngtao-edge
    DEPLOY_PRIVATE_PDFS 逗号或空格分隔的简历文件名，这些文件不会随代码上传
EOF
}

# ---------- 参数 ----------
MODE=deploy
BUILD_FLAG="--build"
DETACH=0
FORCE_ENV=0

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --env) [ $# -ge 2 ] || die "--env 需要一个值（如 hr / public）"; DEPLOY_ENV="$2"; shift 2 ;;
    --init) MODE=init; shift ;;
    --no-build) BUILD_FLAG=""; shift ;;
    --restart) MODE=restart; shift ;;
    --force-env) FORCE_ENV=1; shift ;;
    --detach) DETACH=1; shift ;;
    --build-log) MODE=buildlog; shift ;;
    --status) MODE=status; shift ;;
    --upload-resume)
      MODE=uploadresume; shift
      # 可选：紧跟一个文件名
      if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then
        DEPLOY_RESUME_FILE="$1"; shift
      fi
      ;;
    --resume) [ $# -ge 2 ] || die "--resume 需要一个文件名"; DEPLOY_RESUME_FILE="$2"; shift 2 ;;
    --logs)
      MODE=logs; shift
      # 可选的服务名紧跟其后
      if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then
        DEPLOY_SERVICES="$1"; shift
      fi
      ;;
    --host) [ $# -ge 2 ] || die "--host 需要一个值"; DEPLOY_SSH="$2"; shift 2 ;;
    --dir)  [ $# -ge 2 ] || die "--dir 需要一个值";  DEPLOY_DIR="$2"; shift 2 ;;
    --only)
      [ $# -ge 2 ] || die "--only 需要一个值（web 或 api）"
      case "$2" in
        web|api) DEPLOY_SERVICES="$2" ;;
        *) die "--only 只支持 web 或 api" ;;
      esac
      shift 2
      ;;
    *) die "未知参数: $1（用 --help 查看用法）" ;;
  esac
done

[ -f "$ROOT_DIR/docker-compose.yml" ] || die "在 ${ROOT_DIR} 下没找到 docker-compose.yml，请在仓库根目录运行"

# ---------- SSH ----------
require_target() {
  [ -n "$DEPLOY_SSH" ] || die "还没配置服务器地址：在 deploy.conf 里填 DEPLOY_SSH=user@host，或用 --host 指定"
}

ssh_exec() {
  # ControlMaster 复用连接：一次部署只输一遍密码
  if [ -n "$DEPLOY_KEY" ]; then
    ssh -p "$DEPLOY_PORT" -i "$DEPLOY_KEY" $SSH_COMMON_OPTS "$DEPLOY_SSH" "$1"
  else
    ssh -p "$DEPLOY_PORT" $SSH_COMMON_OPTS "$DEPLOY_SSH" "$1"
  fi
}

ssh_exec_tty() {
  if [ -n "$DEPLOY_KEY" ]; then
    ssh -t -p "$DEPLOY_PORT" -i "$DEPLOY_KEY" $SSH_COMMON_OPTS "$DEPLOY_SSH" "$1"
  else
    ssh -t -p "$DEPLOY_PORT" $SSH_COMMON_OPTS "$DEPLOY_SSH" "$1"
  fi
}

# 传单个文件（用于把简历 PDF 单独上传，不走代码包）
scp_put() {
  if [ -n "$DEPLOY_KEY" ]; then
    scp -P "$DEPLOY_PORT" -i "$DEPLOY_KEY" $SSH_COMMON_OPTS "$1" "$DEPLOY_SSH:$2"
  else
    scp -P "$DEPLOY_PORT" $SSH_COMMON_OPTS "$1" "$DEPLOY_SSH:$2"
  fi
}

preflight() {
  [ "$PREFLIGHT_DONE" = "1" ] && return 0
  require_target
  log "检查服务器连接与 Docker 环境（${DEPLOY_SSH}:${DEPLOY_PORT}）..."

  local out
  out="$(ssh_exec 'command -v docker >/dev/null 2>&1 && echo has-docker || echo no-docker
if docker compose version >/dev/null 2>&1; then echo compose:plugin
elif command -v docker-compose >/dev/null 2>&1; then echo compose:standalone
else echo compose:none
fi' 2>&1)" || die "连接 ${DEPLOY_SSH} 失败：确认地址、端口、登录方式（上面的报错信息可供排查）"

  case "$out" in
    *no-docker*) die "服务器上没找到 docker 命令" ;;
    *compose:plugin*)     REMOTE_COMPOSE="docker compose" ;;
    *compose:standalone*) REMOTE_COMPOSE="docker-compose" ;;
    *) die "服务器上没有 docker compose，需要先安装 compose 插件" ;;
  esac

  ok "服务器就绪（${REMOTE_COMPOSE}）"
  PREFLIGHT_DONE=1
}

# ---------- 打包上传 ----------
TAR_EXCLUDES=(
  --exclude='.git'
  --exclude='.DS_Store'
  --exclude='node_modules'
  --exclude='.venv'
  --exclude='dist'
  --exclude='__pycache__'
  --exclude='.pytest_cache'
  --exclude='.ruff_cache'
  --exclude='.mypy_cache'
  --exclude='.cache'
  --exclude='.env'
  --exclude='deploy.conf'
  --exclude='ch3ngtao-images.tgz'
)

pack_and_send() {
  collect_private_pdf_excludes
  COPYFILE_DISABLE=1 tar "${TAR_EXCLUDES[@]}" -czf - -C "$ROOT_DIR" . | ssh_exec "$1"
}

# 只上传 git 里跟踪的 PDF：自己的真实简历不进 git，也就不该随代码包上传，
# 需要它时用 ./deploy.sh --upload-resume 单独传（或按 deploy.conf 里的 DEPLOY_PRIVATE_PDFS 指定）
is_declared_private_pdf() {
  local needle="$1" item
  [ -n "${DEPLOY_PRIVATE_PDFS:-}" ] || return 1
  for item in $DEPLOY_PRIVATE_PDFS; do
    [ "$item" = "$needle" ] && return 0
  done
  return 1
}

collect_private_pdf_excludes() {
  local file name
  for file in "$ROOT_DIR"/*.pdf; do
    [ -e "$file" ] || continue
    name="$(basename "$file")"
    if is_declared_private_pdf "$name"; then
      TAR_EXCLUDES+=("--exclude=$name")
      continue
    fi
    if git -C "$ROOT_DIR" rev-parse --git-dir >/dev/null 2>&1 &&
       ! git -C "$ROOT_DIR" ls-files --error-unmatch -- "$name" >/dev/null 2>&1; then
      TAR_EXCLUDES+=("--exclude=$name")
    fi
  done
}

# 服务器上的简历 PDF 检查：自己的简历不进代码包，少了要在构建前说清楚
remote_resume_check() {
  cat <<EOF
resume="\$(sed -n 's/^RESUME_FILE=//p' .env 2>/dev/null | head -1 | tr -d '\r')"
resume="\${resume:-简历-李四.pdf}"
if [ ! -f "\$resume" ]; then
  echo "✗ 服务器上缺少简历 PDF：$DEPLOY_DIR/\$resume"
  echo "  自己的简历不进 git、也不随代码上传，先单独传一次："
  echo "    ./deploy.sh ${DEPLOY_ENV:+--env $DEPLOY_ENV }--upload-resume"
  exit 1
fi
echo "✓ 简历：\$resume"
EOF
}

remote_health_lines() {
  cat <<EOF
echo
echo "--- 健康检查 ---"
# 容器刚起来时端口可能还没监听，自动重试几次（-m 8 是单次超时）
curl -fsS --retry 6 --retry-delay 3 --retry-connrefused -m 8 http://127.0.0.1:$DEPLOY_API_PORT/api/health || echo "！API 健康检查未通过（用 --logs api 看日志）"
echo
curl -s -o /dev/null --retry 6 --retry-delay 3 --retry-connrefused -m 8 -w "web HTTP %{http_code}\n" http://127.0.0.1:$DEPLOY_WEB_PORT/ || true
EOF
}

compose_up_script() {
  cat <<EOF
set -e
mkdir -p $DEPLOY_DIR
tar -xzf - -C $DEPLOY_DIR
cd $DEPLOY_DIR
# 两个环境共用一张 docker 网络（入口环境的 nginx 用它转发到对外环境）
docker network create $DEPLOY_EDGE_NETWORK >/dev/null 2>&1 || true
$(remote_resume_check)
$REMOTE_COMPOSE up -d $1 $DEPLOY_SERVICES
EOF
}

show_url() {
  if [ -n "$DEPLOY_SITE_URL" ]; then
    ok "访问地址：${DEPLOY_SITE_URL}"
    return 0
  fi
  local host="${DEPLOY_SSH##*@}"
  ok "访问地址：http://${host}:${DEPLOY_WEB_PORT}"
}

# ---------- 各模式 ----------
deploy_transfer() {
  preflight

  # --detach：把构建丢到服务器后台，SSH 断了也不会中断
  if [ "$DETACH" = "1" ]; then
    transfer_detached "$1"
    return 0
  fi

  if [ -n "$1" ]; then
    log "上传代码并在服务器上重新构建（首次会比较慢）..."
  else
    log "上传文件并重启容器（不重建镜像）..."
  fi

  local script
  script="$(compose_up_script "$1")"
  script="$script
$(remote_health_lines)"

  pack_and_send "$script" || die "部署失败，请查看上面的远程输出"
  ok "部署完成"
  show_url
}

restart_only() {
  preflight
  log "重启容器（不上传代码）..."
  ssh_exec "set -e
cd $DEPLOY_DIR
docker network create $DEPLOY_EDGE_NETWORK >/dev/null 2>&1 || true
$(remote_resume_check)
$REMOTE_COMPOSE up -d $DEPLOY_SERVICES
$(remote_health_lines)" || die "重启失败，请查看上面的远程输出"
  ok "重启完成"
  show_url
}

show_status() {
  preflight
  ssh_exec "set -e
cd $DEPLOY_DIR
$REMOTE_COMPOSE ps
$(remote_health_lines)" || die "取状态失败"
}

show_logs() {
  preflight
  log "实时日志（Ctrl+C 退出，不会影响容器）..."
  ssh_exec_tty "cd $DEPLOY_DIR && $REMOTE_COMPOSE logs -f --tail=100 $DEPLOY_SERVICES"
}

# 上传后在服务器后台构建：SSH 断开也不会中断（首次构建很慢时用）
transfer_detached() {
  log "上传代码，并在服务器后台开始构建（关掉终端也不会中断）..."

  local script
  script="set -e
mkdir -p $DEPLOY_DIR
tar -xzf - -C $DEPLOY_DIR
cd $DEPLOY_DIR
docker network create $DEPLOY_EDGE_NETWORK >/dev/null 2>&1 || true
$(remote_resume_check)
nohup sh -c '$REMOTE_COMPOSE up -d $1 $DEPLOY_SERVICES' < /dev/null > build.log 2>&1 &
sleep 1
echo BUILD-STARTED"

  local out
  out="$(pack_and_send "$script")" || die "上传失败，请查看上面的输出"
  case "$out" in
    *BUILD-STARTED*) ok "已在服务器后台开始构建" ;;
    *) die "没能启动后台构建，服务器输出：$out" ;;
  esac

  log "构建过程中的输出会写进 ${DEPLOY_DIR}/build.log"
  ok "看进度：./deploy.sh --build-log"
}

show_build_log() {
  preflight
  log "跟随后台构建日志（Ctrl+C 退出，不会影响构建）..."
  ssh_exec_tty "cd $DEPLOY_DIR && tail -f build.log"
}

# ---------- 首次部署：生成 .env ----------
resolve_api_key() {
  local key="${DEEPSEEK_API_KEY:-}"

  if [ -z "$key" ] && [ -f "$ROOT_DIR/backend/.env" ]; then
    key="$(sed -n 's/^[[:space:]]*DEEPSEEK_API_KEY[[:space:]]*=[[:space:]]*//p' "$ROOT_DIR/backend/.env" | head -1)"
    key="${key%\"}"; key="${key#\"}"
    key="${key%\'}"; key="${key#\'}"
  fi

  if [ -z "$key" ] && [ -t 0 ]; then
    printf '本地没找到 DEEPSEEK_API_KEY，请直接输入（回车跳过）: ' >&2
    read -r key
  fi

  printf '%s' "$key"
}

# 组成要写到服务器 .env 的内容：
# 有 DEPLOY_ENV_FILE 就用它（每个环境一份，如 env/hr.env），否则退回旧的拼法
build_env_payload() {
  local key="$1"

  if [ -n "$DEPLOY_ENV_FILE" ]; then
    local file="$DEPLOY_ENV_FILE"
    case "$file" in
      /*) ;;
      *) file="$ROOT_DIR/$file" ;;
    esac
    [ -f "$file" ] || die "DEPLOY_ENV_FILE 指向的文件不存在：$file"
    cat "$file"
    [ -n "$key" ] && printf '\nDEEPSEEK_API_KEY=%s\n' "$key"
    return 0
  fi

  printf 'DEEPSEEK_API_KEY=%s\n' "$key"
  printf 'DEEPSEEK_BASE_URL=https://api.deepseek.com\n'
  printf 'DEEPSEEK_MODEL=deepseek-chat\n'
  printf 'TZ=Asia/Shanghai\n'
  printf 'TIMEZONE=Asia/Shanghai\n'
  [ -n "$DEPLOY_HF_ENDPOINT" ] && printf 'HF_ENDPOINT=%s\n' "$DEPLOY_HF_ENDPOINT"
  return 0
}

write_remote_env() {
  local key="$1"
  local payload
  payload="$(build_env_payload "$key")"

  log "检查服务器上的 .env ..."
  local out
  out="$(printf '%s\n' "$payload" | ssh_exec "set -e
mkdir -p $DEPLOY_DIR
if [ ! -f $DEPLOY_DIR/.env ]; then
  umask 077
  cat > $DEPLOY_DIR/.env
  echo 'ENV-WROTE'
  exit 0
fi
# 已有 .env：只补齐缺失的键，绝不改动已有的值
tmp=\$(mktemp)
cat > \$tmp
added=''
updated=''
while IFS= read -r line; do
  case \"\$line\" in ''|'#'*) continue ;; esac
  key=\${line%%=*}
  value=\${line#*=}
  if ! grep -q \"^\$key=\" $DEPLOY_DIR/.env; then
    printf '%s\n' \"\$line\" >> $DEPLOY_DIR/.env
    added=\"\$added \$key\"
  elif [ \"$FORCE_ENV\" = '1' ]; then
    awk -v k=\"\$key\" -v v=\"\$value\" 'index(\$0, k \"=\") == 1 { print k \"=\" v; next } { print }' $DEPLOY_DIR/.env > \$tmp.out
    cat \$tmp.out > $DEPLOY_DIR/.env
    updated=\"\$updated \$key\"
  fi
done < \$tmp
rm -f \$tmp \$tmp.out
echo \"ENV-ADDED:\$added\"
echo \"ENV-UPDATED:\$updated\"")" || die "写入 .env 失败"

  case "$out" in
    *ENV-WROTE*)
      ok "已生成 ${DEPLOY_DIR}/.env"
      ;;
    *)
      local added updated
      added="$(printf '%s\n' "$out" | sed -n 's/.*ENV-ADDED:[[:space:]]*//p' | head -1)"
      updated="$(printf '%s\n' "$out" | sed -n 's/.*ENV-UPDATED:[[:space:]]*//p' | head -1)"
      if [ -n "${added// /}" ]; then
        ok "服务器 .env 补充了缺失的配置：${added}"
      fi
      if [ -n "${updated// /}" ]; then
        ok "服务器 .env 已按本地配置覆盖：${updated}"
      fi
      if [ -z "${added// /}" ] && [ -z "${updated// /}" ]; then
        log "服务器上的 .env 已是最新，保持不动"
      else
        log ".env 改动要等容器重建后才生效（本次流程会顺带处理）"
      fi
      ;;
  esac
}

init_deploy() {
  preflight

  local key
  key="$(resolve_api_key)"
  if [ -z "$key" ]; then
    warn "没有 DEEPSEEK_API_KEY，部署后对话和 FAQ 不可用；之后可在服务器的 .env 里补上再跑 ./deploy.sh --restart"
  fi

  write_remote_env "$key"
  deploy_transfer "--build"
}

# ---------- 单独上传简历 ----------
# 自己的简历不进 git，也不随代码包上传，用这个命令单独传一次；
# 传完要重建前端镜像才会生效（简历数据是构建时生成的）。
upload_resume() {
  preflight

  # 服务器 .env 里配置的是哪一份（用来校验名字对不对）
  local configured
  configured="$(ssh_exec "sed -n 's/^RESUME_FILE=//p' $DEPLOY_DIR/.env 2>/dev/null | head -1" | tr -d '\r')"

  # 本地源文件：--resume 可以给文件名，也可以给绝对路径
  local source="${DEPLOY_RESUME_FILE:-$configured}"
  [ -n "$source" ] || source="简历-李四.pdf"

  local local_path="$source"
  case "$local_path" in
    /*) ;;
    *) local_path="$ROOT_DIR/$source" ;;
  esac

  [ -f "$local_path" ] || die "本地找不到简历：${local_path}（用 --resume <文件名或绝对路径> 指定，或在 deploy.conf 里配 DEPLOY_RESUME_FILE）"

  # 服务器上只保留文件本身的名字（传绝对路径时不要跟着目录走）
  local name
  name="$(basename "$local_path")"

  log "上传简历：$local_path → ${DEPLOY_SSH}:${DEPLOY_DIR}/$name"
  ssh_exec "mkdir -p $DEPLOY_DIR" || die "连接服务器失败"
  scp_put "$local_path" "$DEPLOY_DIR/$name" || die "上传失败"
  ok "已上传 $name"

  if [ -n "$configured" ] && [ "$configured" != "$name" ]; then
    local env_file_hint="配置文件"
    [ -n "$DEPLOY_ENV" ] && env_file_hint="env/$DEPLOY_ENV.env"
    warn "注意：服务器 .env 里 RESUME_FILE=${configured}，跟你刚传的 ${name} 名字不一样，这份不会生效"
    warn "  要用它就把 ${env_file_hint} 里的 RESUME_FILE 改成 ${name}，"
    warn "  再执行 ./deploy.sh${DEPLOY_ENV:+ --env $DEPLOY_ENV} --init --force-env"
  fi

  warn "换了简历要让它生效：先重建前端（页面数据是构建时生成的），再重启让后端重新读简历——"
  warn "  ./deploy.sh${DEPLOY_ENV:+ --env $DEPLOY_ENV} --only web"
  warn "  ./deploy.sh${DEPLOY_ENV:+ --env $DEPLOY_ENV} --restart"
}

# ---------- 入口 ----------
case "$MODE" in
  init)    init_deploy ;;
  deploy)  deploy_transfer "$BUILD_FLAG" ;;
  restart) restart_only ;;
  buildlog) show_build_log ;;
  status)  show_status ;;
  logs)    show_logs ;;
  uploadresume) upload_resume ;;
esac
