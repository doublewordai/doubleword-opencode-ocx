# ---- build: compile a static binary with dist/ embedded ----
FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod .
COPY main.go .
COPY dist ./dist
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /registry .

# ---- run: tiny image, just the binary ----
FROM gcr.io/distroless/static-debian12
COPY --from=build /registry /registry
EXPOSE 8077
ENTRYPOINT ["/registry"]
