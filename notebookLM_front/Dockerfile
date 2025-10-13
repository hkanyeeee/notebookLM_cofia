FROM node:20-slim AS build

WORKDIR /app

# 可配置国内/自定义 Registry 与代理，以提高构建稳定性
ARG NPM_REGISTRY=https://registry.npmmirror.com
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ARG VITE_API_BASE_URL
ENV HTTP_PROXY=$HTTP_PROXY
ENV HTTPS_PROXY=$HTTPS_PROXY
ENV NO_PROXY=$NO_PROXY

COPY package.json pnpm-lock.yaml ./
# 使用 npm 装 pnpm，避免 corepack 在部分环境下无法下载
RUN npm config set registry ${NPM_REGISTRY} \
 && npm i -g pnpm@9.12.0 \
 && pnpm config set registry ${NPM_REGISTRY}

# 安装依赖，使用 shamefully-hoist 来扁平化依赖结构
RUN pnpm install --frozen-lockfile --shamefully-hoist

COPY . .
# 允许通过构建参数覆盖，未传参时默认为空字符串（走同源反代）
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL:-""}
RUN pnpm build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]


