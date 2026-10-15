#!/usr/bin/env sh
# Windows 실행 파일(proposal.exe) 빌드. Go 1.24+ 필요, 어느 OS에서든 크로스 컴파일 가능.
set -e
cd "$(dirname "$0")"
mkdir -p dist
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags "-s -w -H=windowsgui" -o dist/proposal.exe .
echo "built dist/proposal.exe"
