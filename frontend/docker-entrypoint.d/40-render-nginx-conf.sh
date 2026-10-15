#!/bin/sh
#
# 启动时按环境变量渲染 nginx 配置。同一份镜像有两种角色：
#
#   入口（HTTP_ONLY != 1）：自己收 HTTPS，可选再把一个子域名转发给另一个环境；
#   站点（HTTP_ONLY = 1）：只监听 80，HTTPS 交给入口，适合被入口转发的对外环境。
#
# 变量：
#   SERVER_NAME        本环境的主域名，可写多个，空格分隔
#   HTTP_ONLY          1 = 只监听 80
#   API_UPSTREAM       /api 的转发目标，默认 api:8000（同 compose 项目内）
#   SSL_CERT/SSL_KEY   入口模式下的证书路径
#   EXTRA_SERVER_NAME  要额外转发的子域名，留空表示不转发
#   EXTRA_UPSTREAM     子域名转发的目标，如 public-web:80
#   EXTRA_SSL_CERT/EXTRA_SSL_KEY  子域名的证书路径
set -eu

TEMPLATE_DIR=/etc/nginx/site-templates
CONF_DIR=/etc/nginx/conf.d
SNIPPET=/etc/nginx/snippets/app-locations.inc

: "${SERVER_NAME:=ch3ngtao.top}"
: "${HTTP_ONLY:=0}"
: "${API_UPSTREAM:=api:8000}"
: "${SSL_CERT:=/etc/nginx/certs/fullchain.pem}"
: "${SSL_KEY:=/etc/nginx/certs/privkey.pem}"
: "${EXTRA_SERVER_NAME:=}"
: "${EXTRA_UPSTREAM:=}"
: "${EXTRA_SSL_CERT:=/etc/nginx/certs/extra-fullchain.pem}"
: "${EXTRA_SSL_KEY:=/etc/nginx/certs/extra-privkey.pem}"

# render <模板> <输出> KEY=VALUE ...
# 把模板里的 {{KEY}} 换成对应值；nginx 自己的 $变量 不受影响。
render() {
  template="$1"
  out="$2"
  shift 2
  cat "$template" > "$out"
  for pair in "$@"; do
    key="${pair%%=*}"
    value="${pair#*=}"
    escaped="$(printf '%s' "$value" | sed -e 's/[\\&|]/\\&/g')"
    sed -i "s|{{${key}}}|${escaped}|g" "$out"
  done
}

mkdir -p "$CONF_DIR" "$(dirname "$SNIPPET")"
# 清掉镜像自带的 default.conf，配置全部由这里生成
rm -f "$CONF_DIR"/*.conf

render "$TEMPLATE_DIR/app-locations.conf.template" "$SNIPPET" "API_UPSTREAM=$API_UPSTREAM"

if [ "$HTTP_ONLY" = "1" ]; then
  render "$TEMPLATE_DIR/http-only.conf.template" "$CONF_DIR/default.conf" "SERVER_NAME=$SERVER_NAME"
  echo "[nginx] 站点模式：只监听 80（HTTPS 由入口环境负责），server_name=${SERVER_NAME}"
else
  render "$TEMPLATE_DIR/http-redirect.conf.template" "$CONF_DIR/default.conf" "SERVER_NAME=$SERVER_NAME"
  render "$TEMPLATE_DIR/https-site.conf.template" "$CONF_DIR/https-site.conf" \
    "SERVER_NAME=$SERVER_NAME" "SSL_CERT=$SSL_CERT" "SSL_KEY=$SSL_KEY"
  echo "[nginx] 入口模式：${SERVER_NAME}（HTTPS，证书 ${SSL_CERT}）"
fi

if [ -n "$EXTRA_SERVER_NAME" ] && [ -n "$EXTRA_UPSTREAM" ]; then
  # 证书没放好就先不渲染这段：否则 nginx -t 会失败，连主域名一起起不来
  if [ -f "$EXTRA_SSL_CERT" ] && [ -f "$EXTRA_SSL_KEY" ]; then
    render "$TEMPLATE_DIR/extra-domain.conf.template" "$CONF_DIR/extra-domain.conf" \
      "EXTRA_SERVER_NAME=$EXTRA_SERVER_NAME" \
      "EXTRA_UPSTREAM=$EXTRA_UPSTREAM" \
      "EXTRA_SSL_CERT=$EXTRA_SSL_CERT" \
      "EXTRA_SSL_KEY=$EXTRA_SSL_KEY"
    echo "[nginx] 另外把 ${EXTRA_SERVER_NAME} 转发到 ${EXTRA_UPSTREAM}"
  else
    echo "[nginx] ⚠ 有配置子域名 ${EXTRA_SERVER_NAME}，但证书不在（${EXTRA_SSL_CERT} / ${EXTRA_SSL_KEY}），本次先不转发"
  fi
fi

# 配置写错了就直接启动失败，别让容器带着坏配置跑起来
nginx -t
