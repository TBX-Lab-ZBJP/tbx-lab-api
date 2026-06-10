FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
EXPOSE 3000
RUN npm run build
CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0"]
