# WireGuardVPNDown Remediation Runbook

<!-- risk_level: medium -->
<!-- estimated_duration: 5-10 minutes -->

## Overview

This alert fires when the WireGuard VPN tunnel between Nexus (192.168.0.11) and Outpost (72.60.163.242) fails.
This is a **cross-system issue** - you must check BOTH endpoints to determine root cause.

## Investigation Steps

1. Check WireGuard service status on BOTH hosts
2. Verify handshake times to identify which side lost connection
3. Check for interface name changes (wg0 vs wg-quick@wg0)
4. Verify UDP port 51820 is accessible through firewalls
5. Check for public IP changes on Outpost (DDNS)

## Common Causes

- Service crashed on one endpoint
- Network change (ISP, router reboot, IP change)
- Firewall blocking UDP 51820
- Key mismatch after config change
- Interface naming conflict
- Memory pressure causing service restart

## Remediation Steps

1. **Check Nexus first** (it's the most common failure point): `systemctl status wg-quick@wg0`
2. **Then check Outpost**: `systemctl status wg-quick@wg0`
3. **Check handshake timing**: `wg show wg0` - last handshake >2min ago indicates issue
4. **Restart the failed service** on the appropriate host
5. **Verify tunnel is up** by pinging the other endpoint's VPN IP
6. **If restart fails**, check for config errors or key issues

## Commands

```bash
# Check service status
systemctl status wg-quick@wg0

# Show WireGuard interface details and handshake times
wg show wg0

# Check if interface exists
ip link show wg0

# Check for recent errors in journal
journalctl -u wg-quick@wg0 --since "10 minutes ago"

# Restart WireGuard on the affected host
sudo systemctl restart wg-quick@wg0

# Verify tunnel after restart
ping -c 3 10.99.0.1  # From Outpost, ping Nexus VPN IP
ping -c 3 10.99.0.2  # From Nexus, ping Outpost VPN IP

# If interface is stuck, bring down and up
wg-quick down wg0 && wg-quick up wg0
```

## Cross-System Check

**IMPORTANT**: This is a site-to-site VPN. Always check BOTH sides:

| Endpoint | Host | VPN IP | Commands to Check |
|----------|------|--------|-------------------|
| Nexus | 192.168.0.11 | 10.99.0.1 | `ssh nexus 'wg show wg0'` |
| Outpost | 72.60.163.242 | 10.99.0.2 | `ssh outpost 'wg show wg0'` |

If handshake is old on both sides, the tunnel is down. Restart the side that shows errors in journal first.

## Notes

- VPN down affects Prometheus metrics scraping from Outpost
- n8n, Headscale, and other Outpost services become unreachable
- Nexus is typically the more stable side - start troubleshooting at Outpost
- Check Cloudflare DDNS if Outpost's public IP might have changed
