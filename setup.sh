#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# Jarvis AI Remediation Service - Setup Wizard
# ═══════════════════════════════════════════════════════════════════════════════
# Interactive setup script for external homelabbers.
# Run with: ./setup.sh
#
# Flags:
#   --quick     Quick Start setup (single host, core features)
#   --full      Full setup (multi-host, all features)
#   --upgrade   Upgrade existing configuration
#   --validate  Validate current configuration only
#   --help      Show usage information
# ═══════════════════════════════════════════════════════════════════════════════

set -e

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
ENV_EXAMPLE="${SCRIPT_DIR}/.env.example"
SSH_KEY_FILE="${SCRIPT_DIR}/ssh_key"
VERSION="3.12.0"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────

print_header() {
    clear
    echo -e "${CYAN}"
    echo "═══════════════════════════════════════════════════════════════════════════════"
    echo "                    Jarvis Setup Wizard v${VERSION}"
    echo "═══════════════════════════════════════════════════════════════════════════════"
    echo -e "${NC}"
}

print_section() {
    echo ""
    echo -e "${BOLD}${1}${NC}"
    echo "───────────────────────────────────────────────────────────────────────────────"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}!${NC} $1"
}

print_info() {
    echo -e "${BLUE}→${NC} $1"
}

print_skip() {
    echo -e "${YELLOW}⊘${NC} $1"
}

# Generate a secure random password
generate_password() {
    openssl rand -base64 32 | tr -d '/+=' | head -c 32
}

# Prompt for input with default value
prompt_with_default() {
    local prompt="$1"
    local default="$2"
    local var_name="$3"
    local is_secret="${4:-false}"

    if [[ "$is_secret" == "true" ]]; then
        echo -n "$prompt"
        if [[ -n "$default" ]]; then
            echo -n " [press Enter to keep current]"
        fi
        echo -n ": "
        read -s value
        echo ""
    else
        if [[ -n "$default" ]]; then
            echo -n "$prompt [$default]: "
        else
            echo -n "$prompt: "
        fi
        read value
    fi

    if [[ -z "$value" ]]; then
        value="$default"
    fi

    eval "$var_name='$value'"
}

# Prompt for yes/no with default
prompt_yes_no() {
    local prompt="$1"
    local default="$2"  # "y" or "n"
    local var_name="$3"

    if [[ "$default" == "y" ]]; then
        echo -n "$prompt [Y/n]: "
    else
        echo -n "$prompt [y/N]: "
    fi
    read value

    value="${value:-$default}"
    value="${value,,}"  # lowercase

    if [[ "$value" == "y" || "$value" == "yes" ]]; then
        eval "$var_name=true"
    else
        eval "$var_name=false"
    fi
}

# Check if a command exists
command_exists() {
    command -v "$1" &> /dev/null
}

# Test SSH connectivity
test_ssh() {
    local host="$1"
    local user="$2"
    local key="$3"

    ssh -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
        -i "$key" "${user}@${host}" 'echo ok' &> /dev/null
}

# Test HTTP endpoint
test_http() {
    local url="$1"
    curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "$url" 2>/dev/null
}

# Load existing .env file into variables
load_existing_env() {
    if [[ -f "$ENV_FILE" ]]; then
        # Source the file but handle special characters
        while IFS='=' read -r key value; do
            # Skip comments and empty lines
            [[ "$key" =~ ^#.*$ ]] && continue
            [[ -z "$key" ]] && continue
            # Remove leading/trailing whitespace
            key=$(echo "$key" | xargs)
            value=$(echo "$value" | sed 's/^["'\'']//' | sed 's/["'\'']$//')
            # Export the variable
            export "EXISTING_$key=$value"
        done < "$ENV_FILE"
        return 0
    fi
    return 1
}

# ─────────────────────────────────────────────────────────────────────────────
# Setup Functions
# ─────────────────────────────────────────────────────────────────────────────

setup_database() {
    print_section "Step: Database Configuration"
    echo "Jarvis needs a PostgreSQL database to track remediation attempts."
    echo "The included docker-compose.yml will create a PostgreSQL container for you."
    echo ""

    local default_pass=""
    if [[ -n "$EXISTING_POSTGRES_PASSWORD" ]]; then
        default_pass="$EXISTING_POSTGRES_PASSWORD"
        echo -e "${BLUE}Current password detected. Press Enter to keep it.${NC}"
    fi

    echo -n "Enter database password (or press Enter to "
    if [[ -n "$default_pass" ]]; then
        echo -n "keep current"
    else
        echo -n "generate one"
    fi
    echo -n "): "
    read -s DB_PASSWORD
    echo ""

    if [[ -z "$DB_PASSWORD" ]]; then
        if [[ -n "$default_pass" ]]; then
            DB_PASSWORD="$default_pass"
            print_success "Keeping existing database password"
        else
            DB_PASSWORD=$(generate_password)
            print_success "Generated secure database password"
        fi
    else
        print_success "Database password set"
    fi

    DATABASE_URL="postgresql://jarvis:${DB_PASSWORD}@postgres-jarvis:5432/jarvis"
}

setup_claude_api() {
    print_section "Step: Claude API Key"
    echo "Jarvis uses Claude AI to analyze alerts and decide on remediation actions."
    echo ""
    echo -e "Get your API key from: ${CYAN}https://console.anthropic.com/${NC}"
    echo ""

    local default_key="${EXISTING_ANTHROPIC_API_KEY:-}"

    while true; do
        if [[ -n "$default_key" ]]; then
            echo "Current key: ${default_key:0:20}..."
            prompt_with_default "Enter Claude API key (or press Enter to keep current)" "" ANTHROPIC_API_KEY true
            if [[ -z "$ANTHROPIC_API_KEY" ]]; then
                ANTHROPIC_API_KEY="$default_key"
            fi
        else
            prompt_with_default "Enter your Claude API key (starts with sk-ant-)" "" ANTHROPIC_API_KEY true
        fi

        if [[ "$ANTHROPIC_API_KEY" =~ ^sk-ant- ]]; then
            print_success "API key format valid"
            break
        else
            print_error "Invalid API key format. Must start with 'sk-ant-'"
            default_key=""
        fi
    done

    CLAUDE_MODEL="${EXISTING_CLAUDE_MODEL:-claude-3-5-haiku-20241022}"
}

setup_ssh_single() {
    print_section "Step: SSH Configuration"
    echo "Jarvis needs SSH access to the host(s) it will manage."
    echo ""

    # Primary host
    local default_host="${EXISTING_SSH_NEXUS_HOST:-}"
    local default_user="${EXISTING_SSH_NEXUS_USER:-}"

    prompt_with_default "Enter the hostname or IP of your primary server" "$default_host" SSH_NEXUS_HOST
    prompt_with_default "Enter the SSH username for this server" "$default_user" SSH_NEXUS_USER

    # SSH Key
    echo ""
    if [[ -f "$SSH_KEY_FILE" ]]; then
        print_info "Existing SSH key found at ./ssh_key"
        prompt_yes_no "Use existing SSH key?" "y" USE_EXISTING_KEY
        if [[ "$USE_EXISTING_KEY" == "true" ]]; then
            print_success "Using existing SSH key"
            return
        fi
    fi

    echo "Do you have an SSH key, or should we help you create one?"
    echo "  1) I have an existing SSH key"
    echo "  2) Generate a new SSH key for Jarvis"
    echo ""
    echo -n "Enter choice [1-2]: "
    read key_choice

    case "$key_choice" in
        1)
            echo ""
            prompt_with_default "Enter the path to your SSH private key" "~/.ssh/id_ed25519" SSH_KEY_PATH
            SSH_KEY_PATH="${SSH_KEY_PATH/#\~/$HOME}"

            if [[ -f "$SSH_KEY_PATH" ]]; then
                cp "$SSH_KEY_PATH" "$SSH_KEY_FILE"
                chmod 600 "$SSH_KEY_FILE"
                print_success "SSH key copied to ./ssh_key"
            else
                print_error "SSH key not found at $SSH_KEY_PATH"
                exit 1
            fi
            ;;
        2)
            echo ""
            echo "Generating new ED25519 SSH key..."
            ssh-keygen -t ed25519 -f "$SSH_KEY_FILE" -N "" -C "jarvis@$(hostname)"
            chmod 600 "$SSH_KEY_FILE"
            print_success "SSH key generated"
            echo ""
            echo -e "${YELLOW}IMPORTANT: Add this public key to your server's ~/.ssh/authorized_keys:${NC}"
            echo ""
            cat "${SSH_KEY_FILE}.pub"
            echo ""
            echo -n "Press Enter once you've added the key to your server..."
            read
            ;;
        *)
            print_error "Invalid choice"
            exit 1
            ;;
    esac
}

setup_ssh_multi() {
    print_section "Step: Additional SSH Hosts"
    echo "Full setup supports multiple hosts for remediation."
    echo ""

    # Home Assistant
    prompt_yes_no "Configure Home Assistant SSH?" "n" CONFIGURE_HA
    if [[ "$CONFIGURE_HA" == "true" ]]; then
        prompt_with_default "  Home Assistant Host" "${EXISTING_SSH_HOMEASSISTANT_HOST:-}" SSH_HOMEASSISTANT_HOST
        prompt_with_default "  Home Assistant User" "${EXISTING_SSH_HOMEASSISTANT_USER:-root}" SSH_HOMEASSISTANT_USER
        print_success "Home Assistant SSH configured"
    else
        SSH_HOMEASSISTANT_HOST="localhost"
        SSH_HOMEASSISTANT_USER="root"
        print_skip "Home Assistant SSH skipped"
    fi

    echo ""

    # Cloud/VPS
    prompt_yes_no "Configure Cloud/VPS SSH?" "n" CONFIGURE_VPS
    if [[ "$CONFIGURE_VPS" == "true" ]]; then
        prompt_with_default "  VPS Host" "${EXISTING_SSH_OUTPOST_HOST:-}" SSH_OUTPOST_HOST
        prompt_with_default "  VPS User" "${EXISTING_SSH_OUTPOST_USER:-}" SSH_OUTPOST_USER
        print_success "Cloud/VPS SSH configured"
    else
        SSH_OUTPOST_HOST="localhost"
        SSH_OUTPOST_USER="root"
        print_skip "Cloud/VPS SSH skipped"
    fi

    echo ""

    # Management host (Skynet)
    prompt_yes_no "Configure Management Host SSH (where Jarvis runs)?" "n" CONFIGURE_MGMT
    if [[ "$CONFIGURE_MGMT" == "true" ]]; then
        prompt_with_default "  Management Host" "${EXISTING_SSH_SKYNET_HOST:-}" SSH_SKYNET_HOST
        prompt_with_default "  Management User" "${EXISTING_SSH_SKYNET_USER:-}" SSH_SKYNET_USER
        print_success "Management host SSH configured"
    else
        SSH_SKYNET_HOST="localhost"
        SSH_SKYNET_USER="root"
        print_skip "Management host SSH skipped"
    fi
}

setup_discord() {
    print_section "Step: Discord Notifications"
    echo "Jarvis can send notifications to Discord when it fixes issues."
    echo ""
    echo -e "Get a webhook URL from: ${CYAN}Server Settings -> Integrations -> Webhooks${NC}"
    echo ""

    local default_url="${EXISTING_DISCORD_WEBHOOK_URL:-}"

    prompt_with_default "Enter Discord webhook URL (or press Enter to skip)" "$default_url" DISCORD_WEBHOOK_URL

    if [[ -n "$DISCORD_WEBHOOK_URL" && "$DISCORD_WEBHOOK_URL" =~ ^https://discord\.com/api/webhooks/ ]]; then
        DISCORD_ENABLED="true"
        print_success "Discord webhook configured"
    elif [[ -n "$DISCORD_WEBHOOK_URL" ]]; then
        print_warning "Invalid Discord webhook URL format"
        DISCORD_ENABLED="false"
    else
        DISCORD_ENABLED="false"
        print_skip "Discord notifications disabled"
    fi
}

setup_webhook_auth() {
    print_section "Step: Webhook Security"
    echo "Alertmanager will authenticate to Jarvis using basic auth."
    echo ""

    local default_pass="${EXISTING_WEBHOOK_AUTH_PASSWORD:-}"

    echo -n "Enter webhook password (or press Enter to "
    if [[ -n "$default_pass" ]]; then
        echo -n "keep current"
    else
        echo -n "generate one"
    fi
    echo -n "): "
    read -s WEBHOOK_AUTH_PASSWORD
    echo ""

    if [[ -z "$WEBHOOK_AUTH_PASSWORD" ]]; then
        if [[ -n "$default_pass" ]]; then
            WEBHOOK_AUTH_PASSWORD="$default_pass"
            print_success "Keeping existing webhook password"
        else
            WEBHOOK_AUTH_PASSWORD=$(generate_password)
            print_success "Generated secure webhook password"
        fi
    else
        print_success "Webhook password set"
    fi

    WEBHOOK_AUTH_USERNAME="alertmanager"
}

setup_prometheus() {
    print_section "Step: Prometheus Integration"
    echo "Jarvis can verify fixes by querying Prometheus metrics."
    echo ""

    local default_url="${EXISTING_PROMETHEUS_URL:-}"

    prompt_with_default "Enter Prometheus URL (or press Enter to skip)" "$default_url" PROMETHEUS_URL

    if [[ -n "$PROMETHEUS_URL" ]]; then
        VERIFICATION_ENABLED="true"
        print_success "Prometheus configured"
    else
        PROMETHEUS_URL="http://localhost:9090"
        VERIFICATION_ENABLED="false"
        print_skip "Prometheus skipped (verification disabled)"
    fi
}

setup_loki() {
    print_section "Step: Loki Integration"
    echo "Jarvis can query logs for additional context."
    echo ""

    local default_url="${EXISTING_LOKI_URL:-}"

    prompt_with_default "Enter Loki URL (or press Enter to skip)" "$default_url" LOKI_URL

    if [[ -n "$LOKI_URL" ]]; then
        print_success "Loki configured"
    else
        LOKI_URL="http://localhost:3100"
        print_skip "Loki skipped"
    fi
}

setup_homeassistant() {
    print_section "Step: Home Assistant Integration"
    echo "Jarvis can restart HA addons and reload automations."
    echo ""

    local default_url="${EXISTING_HA_URL:-}"
    local default_token="${EXISTING_HA_TOKEN:-}"

    prompt_with_default "Enter Home Assistant URL (or press Enter to skip)" "$default_url" HA_URL

    if [[ -n "$HA_URL" ]]; then
        echo ""
        echo "Create a Long-Lived Access Token in HA:"
        echo -e "  ${CYAN}Profile -> Security -> Long-Lived Access Tokens -> Create Token${NC}"
        echo ""
        prompt_with_default "Enter HA Long-Lived Access Token" "$default_token" HA_TOKEN true

        if [[ -n "$HA_TOKEN" ]]; then
            print_success "Home Assistant configured"
        else
            print_warning "No HA token provided, integration may be limited"
        fi
    else
        HA_URL="http://localhost:8123"
        HA_TOKEN=""
        print_skip "Home Assistant skipped"
    fi
}

setup_n8n() {
    print_section "Step: n8n Integration"
    echo "Jarvis can trigger n8n workflows and use n8n for self-restart."
    echo ""

    local default_url="${EXISTING_N8N_URL:-}"

    prompt_with_default "Enter n8n URL (or press Enter to skip)" "$default_url" N8N_URL

    if [[ -n "$N8N_URL" ]]; then
        prompt_with_default "Enter n8n API key (optional)" "${EXISTING_N8N_API_KEY:-}" N8N_API_KEY true

        echo ""
        echo "For self-restart capability, configure the n8n webhook URL:"
        prompt_with_default "Enter n8n self-restart webhook URL (optional)" "${EXISTING_N8N_SELF_RESTART_WEBHOOK:-}" N8N_SELF_RESTART_WEBHOOK

        if [[ -n "$N8N_SELF_RESTART_WEBHOOK" ]]; then
            echo ""
            echo "Jarvis needs an external URL that n8n can reach for callbacks:"
            prompt_with_default "Enter Jarvis external URL" "${EXISTING_JARVIS_EXTERNAL_URL:-http://$(hostname -I | awk '{print $1}'):8000}" JARVIS_EXTERNAL_URL
        fi

        print_success "n8n configured"
    else
        N8N_URL="http://localhost:5678"
        N8N_API_KEY=""
        N8N_SELF_RESTART_WEBHOOK=""
        JARVIS_EXTERNAL_URL=""
        print_skip "n8n skipped (self-restart disabled)"
    fi
}

setup_advanced_features() {
    print_section "Step: Advanced Features"

    prompt_yes_no "Enable proactive monitoring?" "y" PROACTIVE_ENABLED
    if [[ "$PROACTIVE_ENABLED" == "true" ]]; then
        PROACTIVE_MONITORING_ENABLED="true"
        print_success "Proactive monitoring enabled (checks every 5 min)"
    else
        PROACTIVE_MONITORING_ENABLED="false"
        print_skip "Proactive monitoring disabled"
    fi

    echo ""

    prompt_yes_no "Enable anomaly detection?" "y" ANOMALY_ENABLED
    if [[ "$ANOMALY_ENABLED" == "true" ]]; then
        ANOMALY_DETECTION_ENABLED="true"
        print_success "Anomaly detection enabled (Z-score threshold: 3.0)"
    else
        ANOMALY_DETECTION_ENABLED="false"
        print_skip "Anomaly detection disabled"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# Configuration Generation
# ─────────────────────────────────────────────────────────────────────────────

generate_env_file() {
    print_section "Generating Configuration"

    # Backup existing .env if present
    if [[ -f "$ENV_FILE" ]]; then
        local backup="${ENV_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
        cp "$ENV_FILE" "$backup"
        print_info "Backed up existing .env to $backup"
    fi

    cat > "$ENV_FILE" << EOF
# ═══════════════════════════════════════════════════════════════════════════════
# JARVIS AI REMEDIATION SERVICE - CONFIGURATION
# Generated by setup.sh on $(date)
# ═══════════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────────────────────
DATABASE_URL=${DATABASE_URL}
POSTGRES_PASSWORD=${DB_PASSWORD}

# ─────────────────────────────────────────────────────────────────────────────
# CLAUDE API
# ─────────────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
CLAUDE_MODEL=${CLAUDE_MODEL}

# ─────────────────────────────────────────────────────────────────────────────
# SSH CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
SSH_NEXUS_HOST=${SSH_NEXUS_HOST}
SSH_NEXUS_USER=${SSH_NEXUS_USER}
SSH_HOMEASSISTANT_HOST=${SSH_HOMEASSISTANT_HOST:-localhost}
SSH_HOMEASSISTANT_USER=${SSH_HOMEASSISTANT_USER:-root}
SSH_OUTPOST_HOST=${SSH_OUTPOST_HOST:-localhost}
SSH_OUTPOST_USER=${SSH_OUTPOST_USER:-root}
SSH_SKYNET_HOST=${SSH_SKYNET_HOST:-localhost}
SSH_SKYNET_USER=${SSH_SKYNET_USER:-root}

# ─────────────────────────────────────────────────────────────────────────────
# DISCORD NOTIFICATIONS
# ─────────────────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL=${DISCORD_WEBHOOK_URL}
DISCORD_ENABLED=${DISCORD_ENABLED}

# ─────────────────────────────────────────────────────────────────────────────
# WEBHOOK SECURITY
# ─────────────────────────────────────────────────────────────────────────────
WEBHOOK_AUTH_USERNAME=${WEBHOOK_AUTH_USERNAME}
WEBHOOK_AUTH_PASSWORD=${WEBHOOK_AUTH_PASSWORD}

# ─────────────────────────────────────────────────────────────────────────────
# REMEDIATION SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
MAX_ATTEMPTS_PER_ALERT=3
ATTEMPT_WINDOW_HOURS=2
COMMAND_EXECUTION_TIMEOUT=60

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
LOG_LEVEL=INFO
LOG_FORMAT=json

# ─────────────────────────────────────────────────────────────────────────────
# PROMETHEUS & LOKI
# ─────────────────────────────────────────────────────────────────────────────
PROMETHEUS_URL=${PROMETHEUS_URL:-http://localhost:9090}
LOKI_URL=${LOKI_URL:-http://localhost:3100}
VERIFICATION_ENABLED=${VERIFICATION_ENABLED:-false}
VERIFICATION_MAX_WAIT_SECONDS=120
VERIFICATION_POLL_INTERVAL=10

# ─────────────────────────────────────────────────────────────────────────────
# HOME ASSISTANT
# ─────────────────────────────────────────────────────────────────────────────
HA_URL=${HA_URL:-http://localhost:8123}
HA_TOKEN=${HA_TOKEN:-}

# ─────────────────────────────────────────────────────────────────────────────
# N8N INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────
N8N_URL=${N8N_URL:-http://localhost:5678}
N8N_API_KEY=${N8N_API_KEY:-}
N8N_SELF_RESTART_WEBHOOK=${N8N_SELF_RESTART_WEBHOOK:-}

# ─────────────────────────────────────────────────────────────────────────────
# SELF-PRESERVATION
# ─────────────────────────────────────────────────────────────────────────────
JARVIS_EXTERNAL_URL=${JARVIS_EXTERNAL_URL:-}
SELF_RESTART_TIMEOUT_MINUTES=10
STALE_HANDOFF_CLEANUP_MINUTES=30

# ─────────────────────────────────────────────────────────────────────────────
# PROACTIVE MONITORING
# ─────────────────────────────────────────────────────────────────────────────
PROACTIVE_MONITORING_ENABLED=${PROACTIVE_MONITORING_ENABLED:-false}
PROACTIVE_CHECK_INTERVAL=300
DISK_EXHAUSTION_WARNING_HOURS=24
CERT_EXPIRY_WARNING_DAYS=30
MEMORY_LEAK_THRESHOLD_MB_PER_HOUR=5.0

# ─────────────────────────────────────────────────────────────────────────────
# ANOMALY DETECTION
# ─────────────────────────────────────────────────────────────────────────────
ANOMALY_DETECTION_ENABLED=${ANOMALY_DETECTION_ENABLED:-false}
ANOMALY_CHECK_INTERVAL=300
ANOMALY_COOLDOWN_MINUTES=30
ANOMALY_Z_SCORE_WARNING=3.0
ANOMALY_Z_SCORE_CRITICAL=4.0
EOF

    print_success "Created .env file"

    # Ensure SSH key permissions
    if [[ -f "$SSH_KEY_FILE" ]]; then
        chmod 600 "$SSH_KEY_FILE"
        print_success "Set SSH key permissions (600)"
    fi
}

show_review() {
    print_section "Review Configuration"

    echo ""
    echo -e "  ${BOLD}Database:${NC}     postgresql://jarvis:****@postgres-jarvis:5432/jarvis"
    echo -e "  ${BOLD}Claude Model:${NC} ${CLAUDE_MODEL}"
    echo -e "  ${BOLD}SSH Host:${NC}     ${SSH_NEXUS_HOST} (${SSH_NEXUS_USER})"

    if [[ "$SSH_HOMEASSISTANT_HOST" != "localhost" ]]; then
        echo -e "  ${BOLD}HA Host:${NC}      ${SSH_HOMEASSISTANT_HOST} (${SSH_HOMEASSISTANT_USER})"
    fi
    if [[ "$SSH_OUTPOST_HOST" != "localhost" ]]; then
        echo -e "  ${BOLD}VPS Host:${NC}     ${SSH_OUTPOST_HOST} (${SSH_OUTPOST_USER})"
    fi
    if [[ "$SSH_SKYNET_HOST" != "localhost" ]]; then
        echo -e "  ${BOLD}Mgmt Host:${NC}    ${SSH_SKYNET_HOST} (${SSH_SKYNET_USER})"
    fi

    echo -e "  ${BOLD}Discord:${NC}      $([ "$DISCORD_ENABLED" == "true" ] && echo "Enabled" || echo "Disabled")"
    echo -e "  ${BOLD}Prometheus:${NC}   $([ "$VERIFICATION_ENABLED" == "true" ] && echo "$PROMETHEUS_URL" || echo "Disabled")"
    echo -e "  ${BOLD}Home Assistant:${NC} $([ -n "$HA_TOKEN" ] && echo "$HA_URL" || echo "Disabled")"
    echo -e "  ${BOLD}n8n:${NC}          $([ -n "$N8N_SELF_RESTART_WEBHOOK" ] && echo "$N8N_URL" || echo "Disabled")"
    echo -e "  ${BOLD}Proactive:${NC}    $([ "$PROACTIVE_MONITORING_ENABLED" == "true" ] && echo "Enabled" || echo "Disabled")"
    echo -e "  ${BOLD}Anomaly:${NC}      $([ "$ANOMALY_DETECTION_ENABLED" == "true" ] && echo "Enabled" || echo "Disabled")"
    echo ""
}

show_next_steps() {
    print_section "Setup Complete!"

    echo ""
    echo "Next steps:"
    echo ""
    echo -e "  1. Start Jarvis:     ${CYAN}docker compose up -d${NC}"
    echo -e "  2. Check health:     ${CYAN}curl http://localhost:8000/health${NC}"
    echo -e "  3. View logs:        ${CYAN}docker logs -f jarvis${NC}"
    echo ""
    echo "Configure Alertmanager to send webhooks to Jarvis:"
    echo ""
    echo -e "${YELLOW}  receivers:"
    echo "    - name: 'jarvis'"
    echo "      webhook_configs:"
    echo "        - url: 'http://jarvis:8000/webhook'"
    echo "          send_resolved: true"
    echo "          http_config:"
    echo "            basic_auth:"
    echo "              username: '${WEBHOOK_AUTH_USERNAME}'"
    echo -e "              password: '${WEBHOOK_AUTH_PASSWORD}'${NC}"
    echo ""
    echo -e "Documentation: ${CYAN}https://github.com/PotatoRick/Jarvis-HomeLab-AI${NC}"
    echo ""
}

# ─────────────────────────────────────────────────────────────────────────────
# Validation Functions
# ─────────────────────────────────────────────────────────────────────────────

run_validation() {
    print_header
    print_section "Validating Jarvis Configuration"

    if [[ ! -f "$ENV_FILE" ]]; then
        print_error "No .env file found. Run setup first."
        exit 1
    fi

    # Load existing env
    set -a
    source "$ENV_FILE"
    set +a

    local passed=0
    local failed=0
    local total=0

    # Test 1: SSH connectivity
    echo ""
    echo "[1/6] Checking SSH connectivity..."
    ((total++))

    if [[ -f "$SSH_KEY_FILE" ]]; then
        if [[ "$SSH_NEXUS_HOST" != "localhost" ]]; then
            if test_ssh "$SSH_NEXUS_HOST" "$SSH_NEXUS_USER" "$SSH_KEY_FILE"; then
                print_success "Primary host ($SSH_NEXUS_HOST) - Connected"
                ((passed++))
            else
                print_error "Primary host ($SSH_NEXUS_HOST) - Connection failed"
                ((failed++))
            fi
        else
            print_skip "Primary host - Not configured"
        fi

        if [[ "$SSH_HOMEASSISTANT_HOST" != "localhost" ]]; then
            if test_ssh "$SSH_HOMEASSISTANT_HOST" "$SSH_HOMEASSISTANT_USER" "$SSH_KEY_FILE"; then
                print_success "Home Assistant ($SSH_HOMEASSISTANT_HOST) - Connected"
            else
                print_warning "Home Assistant ($SSH_HOMEASSISTANT_HOST) - Connection failed"
            fi
        fi

        if [[ "$SSH_OUTPOST_HOST" != "localhost" ]]; then
            if test_ssh "$SSH_OUTPOST_HOST" "$SSH_OUTPOST_USER" "$SSH_KEY_FILE"; then
                print_success "Cloud/VPS ($SSH_OUTPOST_HOST) - Connected"
            else
                print_warning "Cloud/VPS ($SSH_OUTPOST_HOST) - Connection failed"
            fi
        fi
    else
        print_error "SSH key not found at ./ssh_key"
        ((failed++))
    fi

    # Test 2: Database
    echo ""
    echo "[2/6] Checking database..."
    ((total++))

    if docker ps --format '{{.Names}}' | grep -q 'postgres-jarvis'; then
        print_success "PostgreSQL container running"
        if docker exec postgres-jarvis pg_isready -U jarvis &> /dev/null; then
            print_success "Database connection - Ready"
            ((passed++))
        else
            print_warning "Database not ready yet (may need to start)"
        fi
    else
        print_warning "PostgreSQL container not running (will start with docker compose up)"
        ((passed++))  # Not a failure if not started yet
    fi

    # Test 3: Claude API
    echo ""
    echo "[3/6] Checking Claude API..."
    ((total++))

    if [[ "$ANTHROPIC_API_KEY" =~ ^sk-ant- ]]; then
        print_success "API key format - Valid"

        # Optional: Actually test the API
        prompt_yes_no "Test Claude API connectivity? (costs ~\$0.001)" "y" TEST_API
        if [[ "$TEST_API" == "true" ]]; then
            response=$(curl -s -w "\n%{http_code}" -X POST https://api.anthropic.com/v1/messages \
                -H "x-api-key: $ANTHROPIC_API_KEY" \
                -H "anthropic-version: 2023-06-01" \
                -H "content-type: application/json" \
                -d '{"model":"claude-3-5-haiku-20241022","max_tokens":10,"messages":[{"role":"user","content":"hi"}]}' 2>/dev/null)

            http_code=$(echo "$response" | tail -n1)

            if [[ "$http_code" == "200" ]]; then
                print_success "API connectivity - Working"
                ((passed++))
            else
                print_error "API connectivity - Failed (HTTP $http_code)"
                ((failed++))
            fi
        else
            print_skip "API connectivity test skipped"
            ((passed++))
        fi
    else
        print_error "API key format - Invalid"
        ((failed++))
    fi

    # Test 4: Discord
    echo ""
    echo "[4/6] Checking Discord webhook..."
    ((total++))

    if [[ "$DISCORD_ENABLED" == "true" && -n "$DISCORD_WEBHOOK_URL" ]]; then
        print_success "Webhook URL format - Valid"

        prompt_yes_no "Send test message to Discord?" "y" TEST_DISCORD
        if [[ "$TEST_DISCORD" == "true" ]]; then
            http_code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$DISCORD_WEBHOOK_URL" \
                -H "Content-Type: application/json" \
                -d '{"content":"Jarvis setup test - Configuration validated successfully!"}' 2>/dev/null)

            if [[ "$http_code" == "204" || "$http_code" == "200" ]]; then
                print_success "Discord webhook - Message sent"
                print_info "Check your Discord channel for the test message"
                ((passed++))
            else
                print_error "Discord webhook - Failed (HTTP $http_code)"
                ((failed++))
            fi
        else
            print_skip "Discord test skipped"
            ((passed++))
        fi
    else
        print_skip "Discord not configured"
        ((passed++))
    fi

    # Test 5: Prometheus
    echo ""
    echo "[5/6] Checking Prometheus..."
    ((total++))

    if [[ "$VERIFICATION_ENABLED" == "true" && "$PROMETHEUS_URL" != "http://localhost:9090" ]]; then
        http_code=$(test_http "${PROMETHEUS_URL}/-/healthy")
        if [[ "$http_code" == "200" ]]; then
            print_success "Prometheus - Reachable"
            ((passed++))
        else
            print_warning "Prometheus - Not reachable (HTTP $http_code)"
            ((passed++))  # Not critical
        fi
    else
        print_skip "Prometheus not configured"
        ((passed++))
    fi

    # Test 6: Home Assistant
    echo ""
    echo "[6/6] Checking Home Assistant..."
    ((total++))

    if [[ -n "$HA_TOKEN" && "$HA_URL" != "http://localhost:8123" ]]; then
        http_code=$(curl -s -o /dev/null -w "%{http_code}" -X GET "${HA_URL}/api/" \
            -H "Authorization: Bearer $HA_TOKEN" 2>/dev/null)
        if [[ "$http_code" == "200" || "$http_code" == "201" ]]; then
            print_success "Home Assistant - Connected"
            ((passed++))
        else
            print_warning "Home Assistant - Connection issue (HTTP $http_code)"
            ((passed++))  # Not critical
        fi
    else
        print_skip "Home Assistant not configured"
        ((passed++))
    fi

    # Summary
    echo ""
    echo "═══════════════════════════════════════════════════════════════════════════════"
    if [[ $failed -eq 0 ]]; then
        echo -e "${GREEN}Validation Results: ${passed}/${total} passed${NC}"
    else
        echo -e "${YELLOW}Validation Results: ${passed}/${total} passed, ${failed} failed${NC}"
    fi
    echo "═══════════════════════════════════════════════════════════════════════════════"
    echo ""

    if [[ $failed -eq 0 ]]; then
        echo "Your configuration is ready! Start Jarvis with:"
        echo -e "  ${CYAN}docker compose up -d${NC}"
    else
        echo "Please fix the issues above and run validation again:"
        echo -e "  ${CYAN}./setup.sh --validate${NC}"
    fi
    echo ""
}

# ─────────────────────────────────────────────────────────────────────────────
# Main Menu
# ─────────────────────────────────────────────────────────────────────────────

show_menu() {
    print_header

    local env_exists=false
    if [[ -f "$ENV_FILE" ]]; then
        env_exists=true
    fi

    echo "What would you like to do?"
    echo ""
    echo -e "  ${BOLD}1)${NC} Quick Start Setup"
    echo "     Single host, core features only"
    echo -e "     ${CYAN}(Recommended for beginners)${NC}"
    echo ""
    echo -e "  ${BOLD}2)${NC} Full Setup"
    echo "     Multi-host, all features"
    echo "     (Prometheus, n8n, anomaly detection)"
    echo ""

    if [[ "$env_exists" == "true" ]]; then
        echo -e "  ${BOLD}3)${NC} Upgrade Existing Config"
        echo "     Add advanced features to current setup"
        echo ""
        echo -e "  ${BOLD}4)${NC} Validate Configuration"
        echo "     Test SSH, API, database, Discord connectivity"
        echo ""
        echo -e "  ${BOLD}5)${NC} Exit"
        echo ""
        echo -n "Enter choice [1-5]: "
    else
        echo -e "  ${BOLD}3)${NC} Validate Configuration"
        echo "     Test SSH, API, database, Discord connectivity"
        echo ""
        echo -e "  ${BOLD}4)${NC} Exit"
        echo ""
        echo -n "Enter choice [1-4]: "
    fi

    read choice

    case "$choice" in
        1)
            run_quick_setup
            ;;
        2)
            run_full_setup
            ;;
        3)
            if [[ "$env_exists" == "true" ]]; then
                run_upgrade
            else
                run_validation
            fi
            ;;
        4)
            if [[ "$env_exists" == "true" ]]; then
                run_validation
            else
                echo "Goodbye!"
                exit 0
            fi
            ;;
        5)
            if [[ "$env_exists" == "true" ]]; then
                echo "Goodbye!"
                exit 0
            else
                echo "Invalid choice"
                exit 1
            fi
            ;;
        *)
            echo "Invalid choice"
            exit 1
            ;;
    esac
}

run_quick_setup() {
    print_header
    echo -e "${BOLD}Quick Start Setup${NC} - Single host, core features"
    echo ""

    load_existing_env || true

    setup_database
    setup_claude_api
    setup_ssh_single
    setup_discord
    setup_webhook_auth

    # Set defaults for advanced features (disabled)
    SSH_HOMEASSISTANT_HOST="localhost"
    SSH_HOMEASSISTANT_USER="root"
    SSH_OUTPOST_HOST="localhost"
    SSH_OUTPOST_USER="root"
    SSH_SKYNET_HOST="localhost"
    SSH_SKYNET_USER="root"
    PROMETHEUS_URL="http://localhost:9090"
    LOKI_URL="http://localhost:3100"
    VERIFICATION_ENABLED="false"
    HA_URL="http://localhost:8123"
    HA_TOKEN=""
    N8N_URL="http://localhost:5678"
    N8N_API_KEY=""
    N8N_SELF_RESTART_WEBHOOK=""
    JARVIS_EXTERNAL_URL=""
    PROACTIVE_MONITORING_ENABLED="false"
    ANOMALY_DETECTION_ENABLED="false"

    show_review

    prompt_yes_no "Proceed with this configuration?" "y" PROCEED
    if [[ "$PROCEED" != "true" ]]; then
        echo "Setup cancelled."
        exit 0
    fi

    generate_env_file
    show_next_steps

    prompt_yes_no "Would you like to validate the configuration now?" "y" RUN_VALIDATION
    if [[ "$RUN_VALIDATION" == "true" ]]; then
        run_validation
    fi
}

run_full_setup() {
    print_header
    echo -e "${BOLD}Full Setup${NC} - Multi-host, all features"
    echo ""

    load_existing_env || true

    setup_database
    setup_claude_api
    setup_ssh_single
    setup_ssh_multi
    setup_discord
    setup_webhook_auth
    setup_prometheus
    setup_loki
    setup_homeassistant
    setup_n8n
    setup_advanced_features

    show_review

    prompt_yes_no "Proceed with this configuration?" "y" PROCEED
    if [[ "$PROCEED" != "true" ]]; then
        echo "Setup cancelled."
        exit 0
    fi

    generate_env_file
    show_next_steps

    prompt_yes_no "Would you like to validate the configuration now?" "y" RUN_VALIDATION
    if [[ "$RUN_VALIDATION" == "true" ]]; then
        run_validation
    fi
}

run_upgrade() {
    print_header
    echo -e "${BOLD}Upgrade Existing Configuration${NC}"
    echo ""

    if ! load_existing_env; then
        print_error "No existing .env file found"
        exit 1
    fi

    # Load current values as defaults
    DB_PASSWORD="${EXISTING_POSTGRES_PASSWORD:-}"
    DATABASE_URL="${EXISTING_DATABASE_URL:-}"
    ANTHROPIC_API_KEY="${EXISTING_ANTHROPIC_API_KEY:-}"
    CLAUDE_MODEL="${EXISTING_CLAUDE_MODEL:-claude-3-5-haiku-20241022}"
    SSH_NEXUS_HOST="${EXISTING_SSH_NEXUS_HOST:-localhost}"
    SSH_NEXUS_USER="${EXISTING_SSH_NEXUS_USER:-root}"
    SSH_HOMEASSISTANT_HOST="${EXISTING_SSH_HOMEASSISTANT_HOST:-localhost}"
    SSH_HOMEASSISTANT_USER="${EXISTING_SSH_HOMEASSISTANT_USER:-root}"
    SSH_OUTPOST_HOST="${EXISTING_SSH_OUTPOST_HOST:-localhost}"
    SSH_OUTPOST_USER="${EXISTING_SSH_OUTPOST_USER:-root}"
    SSH_SKYNET_HOST="${EXISTING_SSH_SKYNET_HOST:-localhost}"
    SSH_SKYNET_USER="${EXISTING_SSH_SKYNET_USER:-root}"
    DISCORD_WEBHOOK_URL="${EXISTING_DISCORD_WEBHOOK_URL:-}"
    DISCORD_ENABLED="${EXISTING_DISCORD_ENABLED:-false}"
    WEBHOOK_AUTH_USERNAME="${EXISTING_WEBHOOK_AUTH_USERNAME:-alertmanager}"
    WEBHOOK_AUTH_PASSWORD="${EXISTING_WEBHOOK_AUTH_PASSWORD:-}"

    echo "Current configuration detected. Select features to add/update:"
    echo ""

    # Only prompt for features not already configured
    if [[ "$SSH_HOMEASSISTANT_HOST" == "localhost" ]]; then
        setup_ssh_multi
    else
        print_info "Multi-host SSH already configured"
    fi

    if [[ "${EXISTING_VERIFICATION_ENABLED:-false}" != "true" ]]; then
        setup_prometheus
    else
        PROMETHEUS_URL="${EXISTING_PROMETHEUS_URL:-http://localhost:9090}"
        VERIFICATION_ENABLED="true"
        print_info "Prometheus already configured"
    fi

    LOKI_URL="${EXISTING_LOKI_URL:-http://localhost:3100}"

    if [[ -z "${EXISTING_HA_TOKEN:-}" ]]; then
        setup_homeassistant
    else
        HA_URL="${EXISTING_HA_URL:-http://localhost:8123}"
        HA_TOKEN="${EXISTING_HA_TOKEN:-}"
        print_info "Home Assistant already configured"
    fi

    if [[ -z "${EXISTING_N8N_SELF_RESTART_WEBHOOK:-}" ]]; then
        setup_n8n
    else
        N8N_URL="${EXISTING_N8N_URL:-http://localhost:5678}"
        N8N_API_KEY="${EXISTING_N8N_API_KEY:-}"
        N8N_SELF_RESTART_WEBHOOK="${EXISTING_N8N_SELF_RESTART_WEBHOOK:-}"
        JARVIS_EXTERNAL_URL="${EXISTING_JARVIS_EXTERNAL_URL:-}"
        print_info "n8n already configured"
    fi

    setup_advanced_features

    show_review

    prompt_yes_no "Proceed with this configuration?" "y" PROCEED
    if [[ "$PROCEED" != "true" ]]; then
        echo "Upgrade cancelled."
        exit 0
    fi

    generate_env_file
    show_next_steps

    prompt_yes_no "Would you like to validate the configuration now?" "y" RUN_VALIDATION
    if [[ "$RUN_VALIDATION" == "true" ]]; then
        run_validation
    fi
}

show_usage() {
    echo "Jarvis Setup Wizard v${VERSION}"
    echo ""
    echo "Usage: ./setup.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --quick      Run Quick Start setup (single host, core features)"
    echo "  --full       Run Full setup (multi-host, all features)"
    echo "  --upgrade    Upgrade existing configuration"
    echo "  --validate   Validate current configuration only"
    echo "  --help       Show this help message"
    echo ""
    echo "Without options, an interactive menu is displayed."
}

# ─────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────

main() {
    # Check for required commands
    if ! command_exists curl; then
        print_error "curl is required but not installed"
        exit 1
    fi

    if ! command_exists docker; then
        print_error "docker is required but not installed"
        exit 1
    fi

    # Parse command line arguments
    case "${1:-}" in
        --quick)
            run_quick_setup
            ;;
        --full)
            run_full_setup
            ;;
        --upgrade)
            run_upgrade
            ;;
        --validate)
            run_validation
            ;;
        --help|-h)
            show_usage
            ;;
        "")
            show_menu
            ;;
        *)
            echo "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
}

main "$@"
