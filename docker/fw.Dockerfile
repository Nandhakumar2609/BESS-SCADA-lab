# OT edge firewall / router: nftables + WireGuard on Alpine.
FROM alpine:3.20

RUN apk add --no-cache nftables iproute2 wireguard-tools tcpdump conntrack-tools bash iputils

COPY docker/fw-init.sh /usr/local/sbin/fw-init.sh
RUN chmod 0755 /usr/local/sbin/fw-init.sh && mkdir -p /var/log/fw /etc/wireguard

HEALTHCHECK --interval=15s --timeout=3s CMD nft list table inet bess_fw >/dev/null || exit 1
ENTRYPOINT ["/usr/local/sbin/fw-init.sh"]
