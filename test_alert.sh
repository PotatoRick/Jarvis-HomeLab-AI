#!/bin/bash
#
# Test script for AI Remediation Service
# Sends simulated alerts to test the service
#

set -e

# Configuration
SERVICE_URL="${SERVICE_URL:-http://localhost:8000}"
USERNAME="${USERNAME:-alertmanager}"
PASSWORD="${PASSWORD:-}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}AI Remediation Service - Test Suite${NC}"
echo "=================================="
echo ""

# Check if password is set
if [ -z "$PASSWORD" ]; then
    echo -e "${RED}Error: PASSWORD environment variable not set${NC}"
    echo "Usage: PASSWORD=your_password ./test_alert.sh"
    exit 1
fi

# Test 1: Health Check
echo -e "${YELLOW}Test 1: Health Check${NC}"
HEALTH_RESPONSE=$(curl -s "${SERVICE_URL}/health")
echo "$HEALTH_RESPONSE" | jq .

if echo "$HEALTH_RESPONSE" | jq -e '.status == "healthy"' > /dev/null; then
    echo -e "${GREEN}✓ Health check passed${NC}"
else
    echo -e "${RED}✗ Health check failed${NC}"
    exit 1
fi
echo ""

# Test 2: Simple Test Alert
echo -e "${YELLOW}Test 2: Simple Test Alert${NC}"
RESPONSE=$(curl -s -X POST "${SERVICE_URL}/webhook/alertmanager" \
  -u "${USERNAME}:${PASSWORD}" \
  -H "Content-Type: application/json" \
  -d '{
    "version": "4",
    "groupKey": "test-simple",
    "status": "firing",
    "receiver": "ai-remediation",
    "groupLabels": {},
    "commonLabels": {},
    "commonAnnotations": {},
    "externalURL": "http://localhost:9093",
    "alerts": [{
      "status": "firing",
      "labels": {
        "alertname": "TestAlert",
        "instance": "test:8080",
        "severity": "info"
      },
      "annotations": {
        "description": "Simple test alert to verify webhook processing"
      },
      "startsAt": "2025-11-10T12:00:00Z",
      "fingerprint": "test-simple-001"
    }]
  }')

echo "$RESPONSE" | jq .

if echo "$RESPONSE" | jq -e '.status == "processed"' > /dev/null; then
    echo -e "${GREEN}✓ Simple alert processed${NC}"
else
    echo -e "${RED}✗ Simple alert failed${NC}"
fi
echo ""

# Test 3: Container Down Alert (Nexus)
echo -e "${YELLOW}Test 3: Container Down Alert (Nexus)${NC}"
RESPONSE=$(curl -s -X POST "${SERVICE_URL}/webhook/alertmanager" \
  -u "${USERNAME}:${PASSWORD}" \
  -H "Content-Type: application/json" \
  -d '{
    "version": "4",
    "groupKey": "test-container",
    "status": "firing",
    "receiver": "ai-remediation",
    "groupLabels": {},
    "commonLabels": {},
    "commonAnnotations": {},
    "externalURL": "http://localhost:9093",
    "alerts": [{
      "status": "firing",
      "labels": {
        "alertname": "ContainerDown",
        "instance": "nexus:9090",
        "severity": "warning",
        "container_name": "prometheus"
      },
      "annotations": {
        "description": "Container prometheus on nexus is not running",
        "summary": "Prometheus container is down"
      },
      "startsAt": "2025-11-10T12:05:00Z",
      "fingerprint": "test-container-001"
    }]
  }')

echo "$RESPONSE" | jq .

if echo "$RESPONSE" | jq -e '.status == "processed"' > /dev/null; then
    echo -e "${GREEN}✓ Container alert processed${NC}"
else
    echo -e "${RED}✗ Container alert failed${NC}"
fi
echo ""

# Test 4: WireGuard VPN Down (Outpost)
echo -e "${YELLOW}Test 4: WireGuard VPN Down Alert${NC}"
RESPONSE=$(curl -s -X POST "${SERVICE_URL}/webhook/alertmanager" \
  -u "${USERNAME}:${PASSWORD}" \
  -H "Content-Type: application/json" \
  -d '{
    "version": "4",
    "groupKey": "test-wireguard",
    "status": "firing",
    "receiver": "ai-remediation",
    "groupLabels": {},
    "commonLabels": {},
    "commonAnnotations": {},
    "externalURL": "http://localhost:9093",
    "alerts": [{
      "status": "firing",
      "labels": {
        "alertname": "WireGuardVPNDown",
        "instance": "outpost:51820",
        "severity": "critical"
      },
      "annotations": {
        "description": "WireGuard VPN tunnel is not responding",
        "summary": "VPN connectivity lost to Nexus"
      },
      "startsAt": "2025-11-10T12:10:00Z",
      "fingerprint": "test-wireguard-001"
    }]
  }')

echo "$RESPONSE" | jq .

if echo "$RESPONSE" | jq -e '.status == "processed"' > /dev/null; then
    echo -e "${GREEN}✓ WireGuard alert processed${NC}"
else
    echo -e "${RED}✗ WireGuard alert failed${NC}"
fi
echo ""

# Test 5: High Memory Alert (should escalate - high risk)
echo -e "${YELLOW}Test 5: High Memory Alert (System-level)${NC}"
RESPONSE=$(curl -s -X POST "${SERVICE_URL}/webhook/alertmanager" \
  -u "${USERNAME}:${PASSWORD}" \
  -H "Content-Type: application/json" \
  -d '{
    "version": "4",
    "groupKey": "test-memory",
    "status": "firing",
    "receiver": "ai-remediation",
    "groupLabels": {},
    "commonLabels": {},
    "commonAnnotations": {},
    "externalURL": "http://localhost:9093",
    "alerts": [{
      "status": "firing",
      "labels": {
        "alertname": "HighMemoryUsage",
        "instance": "nexus:9100",
        "severity": "warning"
      },
      "annotations": {
        "description": "System memory usage is at 95%",
        "summary": "High memory usage detected on nexus"
      },
      "startsAt": "2025-11-10T12:15:00Z",
      "fingerprint": "test-memory-001"
    }]
  }')

echo "$RESPONSE" | jq .

if echo "$RESPONSE" | jq -e '.status == "processed"' > /dev/null; then
    echo -e "${GREEN}✓ Memory alert processed${NC}"
else
    echo -e "${RED}✗ Memory alert failed${NC}"
fi
echo ""

# Test 6: Statistics Endpoint
echo -e "${YELLOW}Test 6: Statistics Endpoint${NC}"
STATS=$(curl -s "${SERVICE_URL}/statistics?days=1")
echo "$STATS" | jq .

if echo "$STATS" | jq -e '.statistics' > /dev/null; then
    echo -e "${GREEN}✓ Statistics endpoint working${NC}"
else
    echo -e "${RED}✗ Statistics endpoint failed${NC}"
fi
echo ""

# Test 7: Multiple Alerts in Single Webhook
echo -e "${YELLOW}Test 7: Batch Alerts (Multiple in One Webhook)${NC}"
RESPONSE=$(curl -s -X POST "${SERVICE_URL}/webhook/alertmanager" \
  -u "${USERNAME}:${PASSWORD}" \
  -H "Content-Type: application/json" \
  -d '{
    "version": "4",
    "groupKey": "test-batch",
    "status": "firing",
    "receiver": "ai-remediation",
    "groupLabels": {},
    "commonLabels": {},
    "commonAnnotations": {},
    "externalURL": "http://localhost:9093",
    "alerts": [
      {
        "status": "firing",
        "labels": {
          "alertname": "ContainerDown",
          "instance": "nexus:9090",
          "severity": "warning"
        },
        "annotations": {
          "description": "Container 1 down"
        },
        "startsAt": "2025-11-10T12:20:00Z",
        "fingerprint": "batch-001"
      },
      {
        "status": "firing",
        "labels": {
          "alertname": "ContainerDown",
          "instance": "nexus:3000",
          "severity": "warning"
        },
        "annotations": {
          "description": "Container 2 down"
        },
        "startsAt": "2025-11-10T12:20:00Z",
        "fingerprint": "batch-002"
      }
    ]
  }')

echo "$RESPONSE" | jq .

PROCESSED_COUNT=$(echo "$RESPONSE" | jq -r '.alerts_processed')
if [ "$PROCESSED_COUNT" -eq 2 ]; then
    echo -e "${GREEN}✓ Batch alerts processed (${PROCESSED_COUNT} alerts)${NC}"
else
    echo -e "${RED}✗ Batch alerts failed (expected 2, got ${PROCESSED_COUNT})${NC}"
fi
echo ""

# Summary
echo -e "${YELLOW}=================================="
echo "Test Suite Complete"
echo -e "==================================${NC}"
echo ""
echo "Next steps:"
echo "1. Check Discord for notifications"
echo "2. Query database for logged attempts:"
echo "   ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c \"SELECT * FROM remediation_log ORDER BY timestamp DESC LIMIT 5;\"'"
echo "3. Check service logs:"
echo "   docker-compose logs -f ai-remediation"
echo ""
