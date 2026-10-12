# syntax=docker/dockerfile:1

# 构建上下文是仓库根目录：简历 PDF 在根目录，构建时按 RESUME_FILE 取。
# 对外环境用仓库里那份（简历-李四.pdf），自己的简历只在本地 / 服务器存在，不进 git。

# ---------- 构建阶段：装依赖 → 生成简历数据 → 打包前端 ----------
FROM node:22-alpine AS build
WORKDIR /app

ARG RESUME_FILE=简历-李四.pdf
COPY ${RESUME_FILE} /resume/

COPY frontend/package.json frontend/package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY frontend/ ./

# 生成简历数据要用的配置。只在这个构建阶段可见，不会进最终镜像。
ARG RESUME_NAME=
ARG RESUME_GEN_STRICT=0
ARG DEEPSEEK_API_KEY=
ARG DEEPSEEK_BASE_URL=https://api.deepseek.com
ARG DEEPSEEK_MODEL=deepseek-chat
ENV RESUME_DIR=/resume \
    RESUME_FILE=${RESUME_FILE} \
    RESUME_NAME=${RESUME_NAME} \
    RESUME_GEN_STRICT=${RESUME_GEN_STRICT} \
    RESUME_GEN_CACHE_DIR=/resume-cache \
    DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY} \
    DEEPSEEK_BASE_URL=${DEEPSEEK_BASE_URL} \
    DEEPSEEK_MODEL=${DEEPSEEK_MODEL}

# 生成结果按「简历内容哈希 + 生成规则版本 + 模型名」缓存在 /resume-cache：
# 简历没更新就复用上次的数据，不再调用大模型。
# npm run build 会先跑 prebuild（生成简历数据）再 tsc + vite build。
RUN --mount=type=cache,target=/resume-cache,id=resume-gen-cache \
    npm run build

# ---------- 运行阶段：nginx（入口 / 站点两种角色，启动时按环境变量渲染配置） ----------
FROM nginx:1.27-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx/ /etc/nginx/site-templates/
COPY frontend/docker-entrypoint.d/40-render-nginx-conf.sh /docker-entrypoint.d/40-render-nginx-conf.sh
RUN chmod +x /docker-entrypoint.d/40-render-nginx-conf.sh

EXPOSE 80 443
