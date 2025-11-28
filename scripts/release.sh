#!/bin/bash
# Jarvis Release Script
# Builds and pushes a new version to the registry
#
# Usage: ./scripts/release.sh [version]
#   e.g.: ./scripts/release.sh 3.0.1
#         ./scripts/release.sh        # Uses version from VERSION file

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
REGISTRY="registry.theburrow.casa"
IMAGE_NAME="jarvis"

cd "$PROJECT_DIR"

# Get version
if [ -n "$1" ]; then
    VERSION="$1"
    echo "$VERSION" > VERSION
else
    VERSION=$(cat VERSION)
fi

echo "==================================="
echo " Jarvis Release v${VERSION}"
echo "==================================="
echo ""

# Login to registry for push access
echo "Logging into registry..."
if [ -f "$HOME/.jarvis-registry-token" ]; then
    cat "$HOME/.jarvis-registry-token" | docker login "$REGISTRY" -u jarvis-admin --password-stdin
elif [ -n "$JARVIS_REGISTRY_TOKEN" ]; then
    echo "$JARVIS_REGISTRY_TOKEN" | docker login "$REGISTRY" -u jarvis-admin --password-stdin
else
    echo "Error: Registry token not found."
    echo "Set JARVIS_REGISTRY_TOKEN env var or create ~/.jarvis-registry-token"
    exit 1
fi

# Build the image
echo "Building image..."
docker build \
    -t "${REGISTRY}/${IMAGE_NAME}:${VERSION}" \
    -t "${REGISTRY}/${IMAGE_NAME}:latest" \
    .

# Push both tags
echo ""
echo "Pushing ${VERSION}..."
docker push "${REGISTRY}/${IMAGE_NAME}:${VERSION}"

echo ""
echo "Pushing latest..."
docker push "${REGISTRY}/${IMAGE_NAME}:latest"

# Update local deployment
echo ""
echo "Restarting local Jarvis..."
docker compose down jarvis 2>/dev/null || true
docker compose up -d jarvis

# Update changelog on Hub
echo ""
echo "Syncing changelog to Hub..."
scp CHANGELOG.md outpost:/opt/burrow/jarvis-hub/changelog.md 2>/dev/null || echo "Warning: Could not sync changelog"

echo ""
echo "==================================="
echo " Release v${VERSION} complete!"
echo "==================================="
echo ""
echo "Images pushed:"
echo "  - ${REGISTRY}/${IMAGE_NAME}:${VERSION}"
echo "  - ${REGISTRY}/${IMAGE_NAME}:latest"
echo ""
echo "Users can update with:"
echo "  docker pull ${REGISTRY}/${IMAGE_NAME}:latest"
echo ""
