# Host-Level Service Risk Acceptance

- **Date:** 2026-11-19
- **Scope:** Home Assistant, Scrutiny, AdGuard Home, WireGuard
- **Companion finding:** ARC-05 in `docs/reviews/2026-11-17-platform-health-review.md`

These services intentionally run with host-level access because their function
requires it. This document records the residual risk and the controls that keep
it bounded.

## Accepted services

| Service | Host-level capability | Why it is required |
| --- | --- | --- |
| Home Assistant | `privileged`, `network_mode: host` | Device discovery, mDNS, Bluetooth/USB integrations, and direct access to home-automation hardware. |
| Scrutiny | `privileged`, `SYS_RAWIO`, block-device mounts | Reads SMART data directly from the host's disks. |
| AdGuard Home | `network_mode: host` | Binds DNS :53 and DHCP on the physical LAN interface. |
| WireGuard | `NET_ADMIN`, `SYS_MODULE`, `/lib/modules` | Creates the tunnel interface and loads the kernel module. |

## Residual risk

A compromise of one of these images is effectively a host-level compromise:
it can read host devices, change host networking, or reach the LAN directly.
This is accepted because the functions cannot run in an unprivileged bridge
container.

## Controls

- Images are pinned in `versions.env`; upgrades are reviewed before merge.
- No new `privileged`, host-network, `cap_add` or device mount is added without
  an explicit review recorded here.
- Home Assistant and AdGuard stay on the host network only where required.
- WireGuard's capabilities are limited to `NET_ADMIN` and `SYS_MODULE`; no
  additional capabilities are granted.
- The platform's network segmentation keeps application containers away from
  the data-store networks; these host-level services are the documented
  exception.
- Container healthchecks and the host healthcheck timer alert on failures.
- The host is backed up nightly; a restore drill is still an open item.

## External containers

The two `epaper-scribe-*` containers were removed on 2026-11-19, together with
their anonymous volumes. They were never part of `docker-compose.platform.yml`,
the platform healthchecks, or the nightly restic payload. Their external Compose
files remain under `/srv/` but are no longer running; remove
them if the e-paper project is retired.

## Review

Review this acceptance whenever one of these services changes its image,
capabilities, or network mode. A new host-level capability requires a new
entry here before merge.
