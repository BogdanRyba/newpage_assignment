FROM node:20-alpine

WORKDIR /app

# Install deps first for layer caching. No lockfile yet → npm install creates one.
COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev"]
